#include <Wire.h>

#define SDA_PIN 21
#define SCL_PIN 22
#define SCALE_ADDR 0x26

// 🔧 NEW CALIBRATION FACTOR
// I calculated this based on your 108g vs 200g data.
// This should make it show ~200g now.
float CALIBRATION_FACTOR = 200.0; 

long zeroOffset = 0;

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);
  
  Serial.println("\n\n==================================");
  Serial.println("⚖️ M5Stack Scale (Corrected)");
  Serial.println("==================================");
  Serial.println("1. Remove all items.");
  Serial.println("2. Zeroing in 3 seconds...");
  delay(3000);

  // 1. AUTO-TARE
  long sum = 0;
  for (int i = 0; i < 20; i++) {
    sum += readRawData();
    delay(50);
  }
  zeroOffset = sum / 20;
  
  Serial.print("✅ Zero Point: ");
  Serial.println(zeroOffset);
  Serial.println("👉 NOW Place your phone (200g).");
}

void loop() {
  // 1. GET RAW DATA
  long currentRaw = readRawData();
  
  // 2. CALCULATE GRAMS (Fixed Math)
  // We use (Zero - Current) to fix the negative sign
  float rawDiff = zeroOffset - currentRaw; 
  
  // If your unit works the other way, use abs() to be safe
  // float rawDiff = abs(currentRaw - zeroOffset);

  float weightGrams = rawDiff / CALIBRATION_FACTOR;
  float weightKG = weightGrams / 1000.0;

  // 3. NOISE FILTER (Ignore < 5g)
  if (weightGrams < 5.0 && weightGrams > -5.0) {
    weightGrams = 0.0;
    weightKG = 0.0;
  }

  // 4. PRINT RESULT
  Serial.print("Grams: ");
  Serial.print(weightGrams, 1);
  Serial.print(" g  |  Kilograms: ");
  Serial.print(weightKG, 3);
  Serial.println(" kg");

  // Format specifically for Python:
  // Serial.print("Weight: "); Serial.println(weightKG, 2);

  delay(200);
}

// --- HELPER ---
long readRawData() {
  Wire.beginTransmission(SCALE_ADDR);
  Wire.write(0x00);
  Wire.endTransmission();
  
  Wire.requestFrom(SCALE_ADDR, 4);
  
  long value = 0;
  if (Wire.available() == 4) {
    uint8_t data[4];
    data[0] = Wire.read();
    data[1] = Wire.read();
    data[2] = Wire.read();
    data[3] = Wire.read();
    value = ((long)data[3] << 24) | ((long)data[2] << 16) | ((long)data[1] << 8) | (long)data[0];
  }
  return value;
}