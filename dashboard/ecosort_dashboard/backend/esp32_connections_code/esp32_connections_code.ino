#include "HX711.h"
#include <ESP32Servo.h>

// ==========================================
// ⚙️ PIN DEFINITIONS
// ==========================================
const int LOADCELL_DOUT_PIN = 21;
const int LOADCELL_SCK_PIN = 22;
const int SERVO_PIN = 13;

// ==========================================
// 🔧 CALIBRATION & CONFIG
// ==========================================
// You must adjust this factor to get accurate kg readings!
// 1. Put a known weight (e.g. 1kg) on scale.
// 2. Adjust this number until the output matches 1.0
float CALIBRATION_FACTOR = 420.0; 

// SERVO ANGLES
const int ANGLE_CENTER = 90; // Neutral position
const int ANGLE_BIO = 45;    // Left for Biodegradable
const int ANGLE_MIXED = 135; // Right for Non-Bio/Mixed

HX711 scale;
Servo sorterServo;
unsigned long lastWeightTime = 0;

void setup() {
  Serial.begin(9600);
  
  // --- SETUP SERVO ---
  sorterServo.attach(SERVO_PIN);
  sorterServo.write(ANGLE_CENTER); // Start at neutral
  delay(500);

  // --- SETUP SCALE ---
  Serial.println("Initializing Scale...");
  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  scale.set_scale(CALIBRATION_FACTOR);
  scale.tare(); // Reset scale to 0 assuming bin is empty at boot
  
  Serial.println("✅ ESP32 Ready. Waiting for commands...");
}

void loop() {
  // -------------------------------------------------
  // 1. READ & SEND WEIGHT (Every 500ms)
  // -------------------------------------------------
  if (millis() - lastWeightTime > 500) {
    if (scale.is_ready()) {
      float weight = scale.get_units(5); // Average of 5 readings
      if (weight < 0) weight = 0.0;      // Ignore negative noise
      
      // SEND FORMAT: "Weight: 4.50"
      // The Python server looks for this exact string!
      Serial.print("Weight: ");
      Serial.println(weight, 2); 
    } else {
      Serial.println("Weight: Error");
    }
    lastWeightTime = millis();
  }

  // -------------------------------------------------
  // 2. LISTEN FOR PYTHON COMMANDS
  // -------------------------------------------------
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim(); // Remove whitespace

    if (command == "BIO") {
      // Sort to Organic Bin
      Serial.println("ACT: Sorting BIO");
      sorterServo.write(ANGLE_BIO);
      delay(2000); // Wait for waste to fall
      sorterServo.write(ANGLE_CENTER); // Return to neutral
    }
    else if (command == "MIXED") {
      // Sort to Mixed/Rejected Bin
      Serial.println("ACT: Sorting MIXED");
      sorterServo.write(ANGLE_MIXED);
      delay(2000);
      sorterServo.write(ANGLE_CENTER);
    }
  }
}