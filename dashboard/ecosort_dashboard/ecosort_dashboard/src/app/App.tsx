import { useEffect } from "react";
import { useWasteSystem } from "../hooks/useWasteSystem";

import { ScreenBoot } from "./components/bin/ScreenBoot";
import { ScreenHome } from "./components/bin/ScreenHome";
import { ScreenDetecting } from "./components/bin/ScreenDetecting";
import { ScreenResult } from "./components/bin/ScreenResult";
import { ScreenPayment } from "./components/bin/ScreenPayment";
import { ScreenPaymentFailed } from "./components/bin/ScreenPaymentFailed"; 
import { ScreenBinFull } from "./components/bin/ScreenBinFull";
import { ScreenTimeout } from "./components/bin/ScreenTimeout";

export default function App() {
  const { 
    state, 
    setState, 
    triggerScan, 
    handleRazorpay, 
    processingFee, 
    capturedImage, 
    detectedItem,
    isOnline,
    binWeight,
    triggerPaymentSuccess, // <--- GRAB IT FROM THE HOOK
    triggerPaymentFailure  // <--- GRAB IT FROM THE HOOK
  } = useWasteSystem();

  useEffect(() => {
    if (state === "BOOT") {
      const timer = setTimeout(() => setState("HOME"), 4000);
      return () => clearTimeout(timer);
    }
  }, [state, setState]);

  return (
    <div className="w-full h-screen overflow-hidden bg-slate-950 text-white font-sans selection:bg-blue-500/30">
      
      {state === "BOOT" && <ScreenBoot />}

      {state === "HOME" && (
        <ScreenHome 
          onDetect={triggerScan} 
          isOnline={isOnline}
        />
      )}

      {state === "DETECTING" && <ScreenDetecting />}

      {state === "RESULT_DEGRADABLE" && <ScreenResult type="degradable" />}
      {state === "RESULT_NON_DEGRADABLE" && <ScreenResult type="non-degradable" />}
      {state === "RESULT_MIXED" && <ScreenResult type="mixed" />}

      {(state === "PAYMENT_REQUIRED" || state === "PAYMENT_VERIFYING") && (
        <ScreenPayment 
          onPay={() => handleRazorpay("Student")} 
          
          // 🔥 FIXED: Now it routes through the strike counter!
          onBypassSuccess={triggerPaymentSuccess}
          onBypassFail={triggerPaymentFailure}

          fee={processingFee}
          image={capturedImage}
          item={detectedItem}
          isVerifying={state === "PAYMENT_VERIFYING"}
        />
      )}

      {state === "PAYMENT_FAILED" && (
        <ScreenPaymentFailed 
          onRetry={() => handleRazorpay("Student")} 
        />
      )}
      
      {state === "PAYMENT_SUCCESS" && <ScreenResult type="payment-success" />}
      
      {state === "ERROR_BIN_FULL" && (
        <ScreenBinFull 
           currentWeight={binWeight} 
           maxWeight={5.0} 
        />
      )}

      {state === "TIMEOUT" && <ScreenTimeout />}

    </div>
  );
}