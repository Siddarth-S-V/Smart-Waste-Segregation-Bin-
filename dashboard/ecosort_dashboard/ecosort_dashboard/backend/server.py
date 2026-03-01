import socketio
import uvicorn
from fastapi import FastAPI, Body, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import cv2
import numpy as np
import torch
from torchvision import transforms
from PIL import Image
import timm
import base64
from io import BytesIO
import os
import sys
from pathlib import Path
from threading import Thread  # <--- REQUIRED FOR MULTI-THREADING
import time

# --- I2C LIBRARY FOR LOAD CELL ---
try:
    import smbus2 as smbus
except ImportError:
    import smbus

# --- DATABASE & PAYMENT IMPORTS ---
import razorpay
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import serial

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "latest.pth"
DB_PATH = f"sqlite:///{BASE_DIR}/waste_transactions.db"
CLASS_NAMES = ['Biodegradable', 'Non-Biodegradable']

# RAZORPAY KEYS
RAZORPAY_KEY_ID = "rzp_test_S9FDHOw26GqKnF"
RAZORPAY_KEY_SECRET = "S5BaAV4wrA1V3f5CcM9BsPFQ"
MERCHANT_UPI_ID = "ecosort@razorpay"

# PRICING & LIMITS
PRICE_PER_KG = 100
DEFAULT_WEIGHT = 1.0
MAX_BIN_CAPACITY = 5.0   # kg
BIN_FULL_THRESHOLD = 4.0 # kg

# --- LOAD CELL CONFIGURATION ---
I2C_BUS = 1
DEVICE_ADDR = 0x26
CALIBRATION_FACTOR = 200.0  # <--- YOUR CALIBRATED VALUE

# SERIAL CONFIG (For Servo)
SERIAL_PORT = '/dev/ttyUSB0' if sys.platform.startswith('linux') else 'COM3'
BAUD_RATE = 9600

# ==========================================
# 🏎️ MULTI-THREADED CAMERA CLASS
# ==========================================
class ThreadedCamera:
    def __init__(self, src=0):
        self.capture = None
        self.status = False
        self.frame = None
        self.stopped = False
        self.src = src

    def start(self):
        # 1. Try to find a working camera (Indices 0, 1, 2)
        for index in range(4):
            print(f"📷 Testing Camera Index {index}...")
            temp_cap = cv2.VideoCapture(index)
            
            if temp_cap.isOpened():
                # WARMUP: Read 20 frames to clear black buffer & auto-expose
                for _ in range(20):
                    temp_cap.read()
                
                ret, frame = temp_cap.read()
                if ret and frame is not None and np.sum(frame) > 0:
                    print(f"✅ Camera FOUND at Index {index}!")
                    self.capture = temp_cap
                    self.status = True
                    self.frame = frame
                    
                    # Set standard resolution
                    self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    self.capture.set(cv2.CAP_PROP_FPS, 30)
                    break
                else:
                    temp_cap.release()
        
        # 2. Handle Case: No Camera Found
        if self.capture is None:
            print("❌ FATAL: No working camera found. Using placeholder.")
            self.frame = np.zeros((480, 640, 3), dtype=np.uint8)
            self.frame[:] = (0, 0, 255) # Red screen to indicate error
        else:
            # 3. START THE THREAD (This enables Multi-threading)
            # Daemon=True means it kills the thread when the app stops
            Thread(target=self.update, args=(), daemon=True).start()
        
        return self

    def update(self):
        # This runs in the background constantly!
        while not self.stopped:
            if self.capture and self.capture.isOpened():
                (self.status, self.frame) = self.capture.read()
            else:
                time.sleep(0.1)

    def read(self):
        # Returns the latest frame from the background thread
        if self.frame is None:
             return False, np.zeros((480, 640, 3), dtype=np.uint8)
        return self.status, self.frame.copy()

    def stop(self):
        self.stopped = True
        if self.capture: self.capture.release()

camera = None

# ==========================================
# 🗄️ DATABASE SETUP
# ==========================================
Base = declarative_base()
engine = create_engine(DB_PATH, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(String, unique=True, index=True)
    order_id = Column(String)
    name = Column(String)
    amount = Column(Float)
    weight_kg = Column(Float)
    waste_type = Column(String)
    sender_upi_id = Column(String, nullable=True)
    receiver_upi_id = Column(String)
    status = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ==========================================
# ⚖️ HARDWARE VARIABLES
# ==========================================
arduino = None      # For Servo Control
bus = None          # For I2C Scale
zero_offset = 0     # For Taring
current_bin_weight = 0.0

# --- 1. READ RAW I2C DATA (Helper) ---
def read_raw_weight_data():
    try:
        # Read 4 bytes from Register 0x00
        data = bus.read_i2c_block_data(DEVICE_ADDR, 0x00, 4)
        # Combine Little Endian
        raw_value = data[0] | (data[1] << 8) | (data[2] << 16) | (data[3] << 24)
        return raw_value
    except Exception as e:
        return None

# --- 2. ASYNC BACKGROUND MONITOR (Runs alongside server) ---
async def weight_monitor_task():
    global current_bin_weight
    print("⚖️  Weight Monitor Background Task Started...")
    
    while True:
        if bus:
            raw_val = read_raw_weight_data()
            if raw_val is not None:
                # LOGIC: (Zero - Current)
                raw_diff = zero_offset - raw_val
                weight_grams = raw_diff / CALIBRATION_FACTOR
                weight_kg = weight_grams / 1000.0

                # Noise Filter (< 2g becomes 0)
                if abs(weight_grams) < 2.0:
                    weight_grams = 0.0
                    weight_kg = 0.0
                
                current_bin_weight = weight_kg

                # PRINT TO TERMINAL (Visual Check)
                sys.stdout.write(f"\r⚖️  Weight: {weight_kg:.3f} kg | Limit: {BIN_FULL_THRESHOLD} kg")
                sys.stdout.flush()

                # A. Broadcast to UI (Async)
                await sio.emit('weight_update', {'weight': weight_kg})

                # B. Check for BIN FULL
                if weight_kg >= BIN_FULL_THRESHOLD:
                    print(f"\n⚠️ BIN FULL DETECTED! Weight: {weight_kg:.3f} kg") 
                    await sio.emit('bin_full', {'weight': weight_kg})
        
        # Async Sleep (Non-blocking)
        await asyncio.sleep(0.5)

# ==========================================
# 🚀 APP SETUP
# ==========================================
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

socket_app = socketio.ASGIApp(sio, app)
client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ==========================================
# 🧠 AI MODEL LOADING
# ==========================================
print(f"⏳ Loading PyTorch Model from: {MODEL_PATH}...")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = None

if not MODEL_PATH.exists():
    print(f"❌ ERROR: Model file not found at {MODEL_PATH}")
else:
    try:
        model = timm.create_model('mobilenetv4_conv_small.e2400_r224_in1k', pretrained=False, num_classes=len(CLASS_NAMES))
        model.load_state_dict(torch.load(MODEL_PATH, map_location=device))
        model.eval()
        print("✅ PyTorch Model Loaded!")
    except Exception as e:
        print(f"❌ Model Error: {e}")

preprocess = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

# ==========================================
# 🔄 LIFECYCLE EVENTS
# ==========================================
@app.on_event("startup")
async def startup_event():
    global camera, bus, zero_offset, arduino
    print("\n🚀 System Starting...")

    # 1. Start Multi-threaded Camera
    camera = ThreadedCamera().start()

    # 2. Init I2C Load Cell
    try:
        bus = smbus.SMBus(I2C_BUS)
        print("⚖️  Calibrating Scale (Zeroing)... Please wait 2s.")
        
        readings = []
        for _ in range(20):
            val = read_raw_weight_data()
            if val is not None: readings.append(val)
            time.sleep(0.05)
        
        if readings:
            zero_offset = sum(readings) // len(readings)
            print(f"✅ Zero Point Set: {zero_offset}")
            
            # 🔥 START THE ASYNC BACKGROUND TASK 🔥
            sio.start_background_task(weight_monitor_task)
            
        else:
            print("❌ Scale Calibration Failed. Check Wiring!")
            
    except Exception as e:
        print(f"❌ Failed to init I2C Load Cell: {e}")

    # 3. Init Serial (Servo)
    try:
        arduino = serial.Serial(port=SERIAL_PORT, baudrate=BAUD_RATE, timeout=0.1)
        time.sleep(2)
        print(f"✅ Arduino Serial Connected on {SERIAL_PORT}")
    except Exception as e:
        print(f"⚠️ Arduino NOT Connected (Running without sorting)")

@app.on_event("shutdown")
def shutdown_event():
    global camera
    if camera: camera.stop()

# ==========================================
# 🎥 ROUTES
# ==========================================
def generate_frames():
    while True:
        if camera:
            success, frame = camera.read()
            if success and frame is not None:
                frame_resized = cv2.resize(frame, (640, 480))
                ret, buffer = cv2.imencode('.jpg', frame_resized)
                if ret:
                    yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        time.sleep(0.03)

@app.get("/video_feed")
def video_feed():
    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/trigger-scan/auto")
async def trigger_auto_scan():
    # 1. Check Bin Full status
    if current_bin_weight >= BIN_FULL_THRESHOLD:
        print("\n⛔ Scan Blocked: Bin is Full")
        await sio.emit('bin_full', {'weight': current_bin_weight})
        return {"status": "error", "message": "Bin Full"}

    if model is None or camera is None: return {"status": "error"}
    
    await sio.emit('scan_start')
    await asyncio.sleep(2)
    
    # READ FRESH FRAME FROM THREAD
    success, frame = camera.read()
    
    # Retry once if frame is somehow missing
    if not success or frame is None:
        print("⚠️ Camera Frame missing, retrying...")
        time.sleep(0.1)
        success, frame = camera.read()

    if success and frame is not None:
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        input_batch = preprocess(pil_img).unsqueeze(0).to(device)
        
        with torch.no_grad():
            output = model(input_batch)
            probabilities = torch.nn.functional.softmax(output[0], dim=0)
            
        confidence, class_idx = torch.max(probabilities, 0)
        detected_class = CLASS_NAMES[class_idx.item()]
        
        # PREVIEW IMAGE FOR FRONTEND
        preview_frame = cv2.resize(frame, (400, 300))
        _, buffer = cv2.imencode('.jpg', preview_frame)
        base64_image = base64.b64encode(buffer).decode('utf-8')
        image_data_url = f"data:image/jpeg;base64,{base64_image}"

        fee = 0 if detected_class == 'Biodegradable' else int(DEFAULT_WEIGHT * PRICE_PER_KG)
        
        # Servo Logic
        if arduino:
            if detected_class == 'Biodegradable':
                arduino.write(b'BIO\n')
            else:
                arduino.write(b'MIXED\n')

        await sio.emit('scan_result', {
            'type': 'clean' if detected_class == 'Biodegradable' else 'mixed',
            'item': detected_class,
            'bin': 'Organic Bin' if detected_class == 'Biodegradable' else 'Rejected',
            'fee': fee,
            'image': image_data_url # Sends the image to the UI
        })
    return {"status": "processed"}

# ==========================================
# 💳 PAYMENT ROUTES
# ==========================================
@app.post("/create_order")
async def create_order(data: dict = Body(...)):
    amount_paise = int(data.get('amount') * 100)
    order = client.order.create(data={
        "amount": amount_paise, "currency": "INR", "receipt": f"order_{int(time.time())}"
    })
    return order

@app.post("/verify_payment")
async def verify_payment(data: dict = Body(...)):
    try:
        client.utility.verify_payment_signature({
            'razorpay_order_id': data['razorpay_order_id'],
            'razorpay_payment_id': data['razorpay_payment_id'],
            'razorpay_signature': data['razorpay_signature']
        })
        
        db = SessionLocal()
        payment_details = client.payment.fetch(data['razorpay_payment_id'])
        new_txn = Transaction(
            payment_id = data['razorpay_payment_id'],
            order_id = data['razorpay_order_id'],
            name = data.get('user_name', 'Guest'),
            amount = float(payment_details['amount']) / 100,
            weight_kg = DEFAULT_WEIGHT,
            waste_type = "Mixed Waste",
            sender_upi_id = payment_details.get('vpa', 'Unknown'),
            receiver_upi_id = MERCHANT_UPI_ID,
            status = "Success"
        )
        db.add(new_txn)
        db.commit()
        db.close()

        if arduino: arduino.write(b'MIXED\n')
        
        await sio.emit('payment_success')
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("server:socket_app", host="0.0.0.0", port=8000, reload=False)