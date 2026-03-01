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
  | "ERROR_BIN_FULL"
  | "TIMEOUT"; 

// ==========================================
// ⚙️ TIMEOUT CONFIGURATION 
// ==========================================
// CHANGE THIS TO 5000 (5 seconds) TO TEST QUICKLY, THEN CHANGE IT BACK TO 100000
const PAYMENT_WAIT_TIMEOUT_MS = 100000; 
const MAX_PAYMENT_FAILURES = 3;         

export function useWasteSystem() {
  const [state, setState] = useState<AppState>("BOOT");
  const [isOnline, setIsOnline] = useState(false);

  const [binLevelOrganic, setBinLevelOrganic] = useState(0);
  const [binLevelRecycle, setBinLevelRecycle] = useState(0);
  const [processingFee, setProcessingFee] = useState(100);
  const [capturedImage, setCapturedImage] = useState<string | null>(null);
  const [detectedItem, setDetectedItem] = useState<string>("");
  const [binWeight, setBinWeight] = useState(0.0);
  
  const [paymentAttempts, setPaymentAttempts] = useState(0);

  const socketRef = useRef<Socket | null>(null);
  const stateRef = useRef(state);
  
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  // ========================================================================
  // ⏱️ TIMEOUT LOGIC
  // ========================================================================
  useEffect(() => {
    let timer: NodeJS.Timeout;

    if (state === "PAYMENT_VERIFYING") {
        timer = setTimeout(() => {
            console.log("⏳ Time limit reached! Forcing Timeout.");
            setPaymentAttempts(0);
            setState("TIMEOUT");
        }, PAYMENT_WAIT_TIMEOUT_MS);
        
    } else if (state === "TIMEOUT") {
        timer = setTimeout(() => {
            setPaymentAttempts(0);
            setState("HOME");
        }, 5000);
        
    } else if (state === "HOME") {
        setPaymentAttempts(0);
    }

    return () => clearTimeout(timer);
  }, [state]);

  // ========================================================================
  // 🎯 CENTRALIZED SUCCESS/FAILURE TRIGGERS
  // ========================================================================
  const triggerPaymentSuccess = () => {
      console.log("✅ Payment Success Triggered");
      setPaymentAttempts(0);
      setState("PAYMENT_SUCCESS");
      setTimeout(() => setState("HOME"), 4000);
  };

  const triggerPaymentFailure = () => {
      const newAttempts = paymentAttempts + 1;
      if (newAttempts >= MAX_PAYMENT_FAILURES) {
          console.log("🚨 3 Strikes Reached! Forcing Timeout.");
          setPaymentAttempts(0);
          setState("TIMEOUT"); 
      } else {
          console.log(`❌ Payment failed. Attempt ${newAttempts}/${MAX_PAYMENT_FAILURES}`);
          setPaymentAttempts(newAttempts);
          setState("PAYMENT_FAILED");
      }
  };

  // ========================================================================
  // 🧙‍♂️ KEYBOARD SHORTCUTS
  // ========================================================================
  useEffect(() => {
    const handleKeyPress = (event: KeyboardEvent) => {
      if (stateRef.current === "PAYMENT_REQUIRED" || stateRef.current === "PAYMENT_VERIFYING") {
        if (event.shiftKey && (event.key === 'S' || event.key === 's')) {
          triggerPaymentSuccess();
        }
        if (event.shiftKey && (event.key === 'F' || event.key === 'f')) {
          triggerPaymentFailure();
        }
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [paymentAttempts]);

  // ========================================================================
  // 🔌 SOCKET LOGIC
  // ========================================================================
  useEffect(() => {
    socketRef.current = io('http://localhost:8000');
    const socket = socketRef.current;

    socket.on('connect', () => setIsOnline(true));
    socket.on('disconnect', () => setIsOnline(false));

    socket.on('sensor_update', (data) => {
      setBinLevelOrganic(data.organic);
      setBinLevelRecycle(data.recycle);
    });

    socket.on('weight_update', (data) => {
        setBinWeight(data.weight);
        if (stateRef.current === "ERROR_BIN_FULL" && data.weight < 4.0) {
            setState("HOME");
        }
    });

    socket.on('bin_full', (data) => {
        setBinWeight(data.weight);
        if (stateRef.current !== "ERROR_BIN_FULL") setState("ERROR_BIN_FULL");
    });

    socket.on('scan_start', () => {
        if (stateRef.current !== "ERROR_BIN_FULL") setState("DETECTING");
    });

    socket.on('scan_result', (data) => {
      if (stateRef.current === "ERROR_BIN_FULL") return;
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

    // Uses the central success function now
    socket.on('payment_success', () => triggerPaymentSuccess());

    return () => { socket.disconnect(); };
  }, []); 

  // --- ACTIONS ---
  const triggerScan = async () => {
    if (!isOnline) { alert("System Offline."); return; }
    if (stateRef.current === "ERROR_BIN_FULL") return;

    try {
      setState("DETECTING");
      await fetch('http://localhost:8000/trigger-scan/auto');
    } catch (e) {
      setState("HOME");
    }
  };

  const handleRazorpay = async (userName: string) => {
    setState("PAYMENT_VERIFYING");
  };

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
    binWeight,
    triggerPaymentSuccess, // <--- EXPORTED SO APP.TSX CAN USE THEM
    triggerPaymentFailure  // <--- EXPORTED SO APP.TSX CAN USE THEM
  };
}