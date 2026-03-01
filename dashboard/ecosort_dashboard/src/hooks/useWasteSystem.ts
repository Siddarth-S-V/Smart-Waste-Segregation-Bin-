import { useState, useEffect, useRef } from 'react';
import { io, Socket } from 'socket.io-client';

export type AppState = 
  | "BOOT" 
  | "HOME" 
  | "DETECTING" 
  | "RESULT_DEGRADABLE" 
  | "RESULT_NON_DEGRADABLE" 
  | "RESULT_MIXED" 
  | "PAYMENT_REQUIRED" 
  | "PAYMENT_VERIFYING"
  | "PAYMENT_SUCCESS" 
  | "PAYMENT_FAILED"
  | "ERROR_BIN_FULL"; // <--- Handles the 4kg limit screen

export function useWasteSystem() {
  const [state, setState] = useState<AppState>("BOOT");
  const [isOnline, setIsOnline] = useState(false);

  // Data States
  const [binLevelOrganic, setBinLevelOrganic] = useState(0);
  const [binLevelRecycle, setBinLevelRecycle] = useState(0);
  const [processingFee, setProcessingFee] = useState(100);
  const [capturedImage, setCapturedImage] = useState<string | null>(null);
  const [detectedItem, setDetectedItem] = useState<string>("");
  const [razorpayReady, setRazorpayReady] = useState(false); 
  
  // New Weight State for Load Cell
  const [binWeight, setBinWeight] = useState(0.0);
  
  const socketRef = useRef<Socket | null>(null);

  // ========================================================================
  // 🧙‍♂️ WIZARD OF OZ: KEYBOARD SHORTCUTS FOR DEMO
  // ========================================================================
  useEffect(() => {
    const handleKeyPress = (event: KeyboardEvent) => {
      // Only listen if we are in a Payment-related state
      if (state === "PAYMENT_REQUIRED" || state === "PAYMENT_VERIFYING") {
        
        // SECRET KEY: SHIFT + S -> Force Success
        if (event.shiftKey && (event.key === 'S' || event.key === 's')) {
          console.log("🧙‍♂️ Wizard Trigger: PAYMENT SUCCESS");
          setState("PAYMENT_SUCCESS");
          setTimeout(() => setState("HOME"), 4000);
        }

        // SECRET KEY: SHIFT + F -> Force Fail
        if (event.shiftKey && (event.key === 'F' || event.key === 'f')) {
          console.log("🧙‍♂️ Wizard Trigger: PAYMENT FAILED");
          setState("PAYMENT_FAILED");
        }
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [state]);

  // ========================================================================
  // 🔌 SOCKET LOGIC (SENSORS + AI)
  // ========================================================================
  useEffect(() => {
    socketRef.current = io('http://localhost:8000');
    const socket = socketRef.current;

    socket.on('connect', () => setIsOnline(true));
    socket.on('disconnect', () => setIsOnline(false));
    socket.on('connect_error', () => setIsOnline(false));

    // Existing Sensor Updates
    socket.on('sensor_update', (data) => {
      setBinLevelOrganic(data.organic);
      setBinLevelRecycle(data.recycle);
    });

    // --- ⚖️ NEW: LOAD CELL WEIGHT UPDATES ---
    socket.on('weight_update', (data) => {
        setBinWeight(data.weight);
    });

    // --- ⚠️ NEW: BIN FULL EVENT ---
    socket.on('bin_full', (data) => {
        setBinWeight(data.weight);
        setState("ERROR_BIN_FULL"); // Triggers the red warning screen
    });

    // AI Scan Results
    socket.on('scan_result', (data) => {
      setCapturedImage(data.image); 
      setDetectedItem(data.item);

      if (data.type === 'clean') {
        setState(data.bin === 'Organic Bin' ? "RESULT_DEGRADABLE" : "RESULT_NON_DEGRADABLE");
        setTimeout(() => setState("HOME"), 5000);
      } else {
        setProcessingFee(data.fee > 0 ? data.fee : 100); 
        setState("RESULT_MIXED");
        setTimeout(() => setState("PAYMENT_REQUIRED"), 3000);
      }
    });

    socket.on('payment_success', () => {
      setState("PAYMENT_SUCCESS");
      setTimeout(() => setState("HOME"), 4000);
    });

    return () => { socket.disconnect(); };
  }, []);

  // --- ACTIONS ---

  const triggerScan = async () => {
    if (!isOnline) {
      alert("System Offline.");
      return;
    }
    try {
      setState("DETECTING");
      await fetch('http://localhost:8000/trigger-scan/auto');
    } catch (e) {
      setState("HOME");
    }
  };

  // ========================================================================
  // 🎭 DEMO HANDLE RAZORPAY (Real Logic Commented Out)
  // ========================================================================
  const handleRazorpay = async (userName: string) => {
    console.log("⚠️ DEMO MODE ACTIVATED: Real Payment Gateway is Disabled.");
    console.log("👉 Waiting for Wizard Keys: Shift+S (Success) or Shift+F (Fail)");

    // 1. Simulate "Verifying" state so the UI shows the QR Code or Loading
    setState("PAYMENT_VERIFYING");

    // 2. We do NOTHING else. We wait for you to press the keys.
  };

  /* // --- 🔴 REAL IMPLEMENTATION (SAVED FOR LATER) ---
  const handleRazorpayReal = async (userName: string) => {
    if (!razorpayReady) { ... loadScript ... }
    try {
      const response = await fetch('http://localhost:8000/create_order', ...);
      const order = await response.json();
      const options = {
        key: "rzp_test_S9FDHOw26GqKnF",
        amount: order.amount,
        currency: "INR",
        name: "EcoSort AI",
        order_id: order.id,
        prefill: { name: userName, contact: "9999999999", email: "demo@ecosort.com" },
        config: { display: { sequence: ["block.priority_upi", "block.other_methods"], preferences: { show_default_blocks: false } } },
        handler: async (response) => { ... verify ... }
      };
      const rzp1 = new (window as any).Razorpay(options);
      rzp1.open();
    } catch (e) { setState("PAYMENT_FAILED"); }
  };
  */

  const resetSystem = () => setState("HOME");

  return { 
    state, 
    setState, 
    isOnline, 
    processingFee, 
    capturedImage, 
    detectedItem, 
    triggerScan, 
    handleRazorpay, 
    resetSystem,
    binWeight // <--- Exported for the UI to use
  };
}

// Helper function (Kept to prevent build errors)
function loadScript(src: string) {
  return new Promise((resolve) => {
    if (document.querySelector(`script[src="${src}"]`)) { resolve(true); return; }
    const script = document.createElement('script');
    script.src = src;
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.body.appendChild(script);
  });
}