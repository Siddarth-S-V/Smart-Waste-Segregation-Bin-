# ♻️ Smart Waste Bin & Classification System

![Status](https://img.shields.io/badge/Status-In%20Development-yellow)
![Platform](https://img.shields.io/badge/Hardware-Raspberry%20Pi%20%7C%20ESP32-green)
![AI Engine](https://img.shields.io/badge/AI-TensorFlow%20Lite-orange)

> **An automated waste segregation system using Computer Vision, differential drive mechanics, and IoT monitoring.**

---

## 📖 Project Overview
The Smart Waste Bin is an automated system designed to identify and segregate waste at the source. It utilizes a **Raspberry Pi** with an AI model to classify waste as degradable or non-degradable and an **ESP32** controller to physically sort the items using a differential mechanism.

### 🌟 Key Features
* **AI Classification:** Identifies waste type (Degradable/Non-Degradable/Mixed) using a camera and PyTorch/TensorFlow Lite model.
* **Auto-Segregation:** Differential rotating plate mechanism directs waste into the correct bin.
* **Smart Payments:** Detects mixed/heavy waste and requests processing fees via UPI/App.
* **IoT Monitoring:** Real-time bin fill-level monitoring with ultrasonic sensors and mobile app alerts.
* **User Interface:** Interactive 7-inch touch display for user guidance and payment status.

---

## 🛠 Hardware Stack

| Component | Specification | Function |
| :--- | :--- | :--- |
| **Main Computer** | Raspberry Pi 4 / 5 | Runs AI Model, UI, and Cloud API |
| **Controller** | ESP32 | Controls motors, reads sensors, and communicates with Pi |
| **Vision** | Pi Camera v3 / HQ Camera | Captures waste images for classification |
| **Actuators** | High Torque Gear Motors | Drives the differential segregation plate |
| **Sensors** | Ultrasonic / ToF | Measures bin fill levels |

---

## ⚙️ Functional Workflow

1.  **Detection:** Camera captures waste image; AI model classifies it (Accuracy target ≥ 90%).
2.  **Segregation:** ESP32 rotates the plate to the specific bin angle based on classification.
3.  **Validation:** Load cells check for weight limits (< 3kg); heavy items trigger a payment request.
4.  **Completion:** If payment is verified or waste is valid, it drops; otherwise, it is ejected.

---

## 🔌 Communication Protocol
* **Internal:** UART communication between Raspberry Pi and ESP32 (Commands: `MOVE_DEGRADABLE`, `READ_WEIGHT`, etc.).
* **External:** MQTT / HTTP API for sending logs and alerts to the Cloud/Mobile App.

---

## 🧑‍💻 Author
**S V Siddarth**
*Bachelor of Engineering in Electronics and Communication Engineering*
*St. Joseph's College of Engineering*

---
*Based on the Technical Design Document for Smart Waste Bin Automation.*
