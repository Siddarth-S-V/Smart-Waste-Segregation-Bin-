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
from threading import Thread
import time

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
MAX_BIN_CAPACITY = 5.0  # kg
BIN_FULL_THRESHOLD = 4.0 # kg

# SERIAL CONFIG
# Note: Ensure your ESP32 is connected to this port
SERIAL_PORT = '/dev/ttyUSB0' if sys.platform.startswith('linux') else 'COM3'
BAUD_RATE = 9600

# ==========================================
# 🏎️ CAMERA CLASS
# ==========================================
class ThreadedCamera:
    def __init__(self, src=0):
        self.capture = None
        self.status = False
        self.frame = None
        self.stopped = False
        self.src = src

    def start(self):
        for index in range(4):
            # print(f"🔍 Testing Camera Index {index}...") 
            temp_cap = cv2.VideoCapture(index)
            if temp_cap.isOpened():
                ret, frame = temp_cap.read()
                if ret and frame is not None:
                    print(f"✅ Camera FOUND at Index {index}!")
                    self.capture = temp_cap
                    self.status = True
                    self.frame = frame
                    self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    self.capture.set(cv2.CAP_PROP_FPS, 30)
                    break
                else:
                    temp_cap.release()
            
        if self.capture is None:
            print("❌ FATAL: No working camera found. Using placeholder.")
            self.frame = np.zeros((480, 640, 3), dtype=np.uint8)
        else:
            Thread(target=self.update, args=(), daemon=True).start()
        
        return self

    def update(self):
        while not self.stopped:
            if self.capture and self.capture.isOpened():
                (self.status, self.frame) = self.capture.read()
            else:
                time.sleep(0.1)

    def read(self):
        if self.frame is None:
             return False, np.zeros((480, 640, 3), dtype=np.uint8)
        return self.status, self.frame

    def stop(self):
        self.stopped = True
        if self.capture:
            self.capture.release()

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
# 🔌 HARDWARE CONNECTION (ESP32 / LOAD CELL)
# ==========================================
arduino = None
current_bin_weight = 0.0

def read_serial_data():
    global current_bin_weight
    while True:
        if arduino and arduino.in_waiting > 0:
            try:
                # Expecting data like: "4.12" or "Weight: 4.12"
                line = arduino.readline().decode('utf-8').strip()
                
                # Simple parsing logic (adjust based on your ESP32 code)
                # If ESP32 sends "W:4.5", split it. If just "4.5", float it.
                raw_weight = line.replace("Weight:", "").strip()
                weight = float(raw_weight)
                
                current_bin_weight = weight
                
                # Broadcast weight to UI (Real-time update)
                asyncio.run_coroutine_threadsafe(
                    sio.emit('weight_update', {'weight': weight}), 
                    loop
                )

                # TRIGGER BIN FULL
                if weight >= BIN_FULL_THRESHOLD:
                    print(f"⚠️ BIN FULL DETECTED: {weight}kg")
                    asyncio.run_coroutine_threadsafe(
                        sio.emit('bin_full', {'weight': weight}), 
                        loop
                    )

            except ValueError:
                pass # Ignore non-numeric lines
            except Exception as e:
                print(f"Serial Error: {e}")
        time.sleep(0.5) # Read twice a second

try:
    arduino = serial.Serial(port=SERIAL_PORT, baudrate=BAUD_RATE, timeout=0.1)
    time.sleep(2)
    print(f"✅ Hardware Connected on {SERIAL_PORT}")
    # Start the Serial Reader Thread
    Thread(target=read_serial_data, daemon=True).start()
except Exception as e:
    print(f"⚠️ Hardware NOT Connected (Software Mode)")

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

# Helper to get the main event loop for threadsafe calls
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

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
        try:
            model = torch.load(MODEL_PATH, map_location=device)
            model.eval()
            print("✅ PyTorch Model Loaded (Full)!")
        except Exception as e2:
             print(f"❌ FATAL ERROR LOADING MODEL: {e2}")

preprocess = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

# ==========================================
# 🔄 LIFECYCLE EVENTS
# ==========================================
@app.on_event("startup")
def startup_event():
    global camera
    print("🚀 Starting Up...")
    camera = ThreadedCamera().start()

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
            if not success or frame is None:
                time.sleep(0.1)
                continue     
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
    # If bin is full, reject scan!
    if current_bin_weight >= BIN_FULL_THRESHOLD:
        await sio.emit('bin_full', {'weight': current_bin_weight})
        return {"status": "error", "message": "Bin Full"}

    if model is None or camera is None: return {"status": "error"}
    
    await sio.emit('scan_start')
    await asyncio.sleep(2)
    
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
        
        preview_frame = cv2.resize(frame, (400, 300))
        _, buffer = cv2.imencode('.jpg', preview_frame)
        base64_image = base64.b64encode(buffer).decode('utf-8')
        image_data_url = f"data:image/jpeg;base64,{base64_image}"

        fee = 0 if detected_class == 'Biodegradable' else int(DEFAULT_WEIGHT * PRICE_PER_KG)
        
        # Hardware Sort Trigger
        if arduino:
            if detected_class == 'Biodegradable':
                arduino.write(b'BIO\n')
            else:
                arduino.write(b'MIXED\n') # Or NONBIO

        await sio.emit('scan_result', {
            'type': 'clean' if detected_class == 'Biodegradable' else 'mixed',
            'item': detected_class,
            'bin': 'Organic Bin' if detected_class == 'Biodegradable' else 'Rejected',
            'fee': fee,
            'image': image_data_url
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
        
        # DB Logic Here (Abbreviated for brevity, same as before)
        if arduino: arduino.write(b'MIXED\n') # Unlock bin
        
        await sio.emit('payment_success')
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("server:socket_app", host="0.0.0.0", port=8000, reload=False)