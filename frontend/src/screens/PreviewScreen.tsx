import { useCallback, useEffect, useRef, useState } from "react";
import { api, friendlyMessage, isApiError } from "../api/client";
import type { PredictionResponse, RectifyResponse } from "../api/types";
import { btn, loadingScreen, msg, panel, sectionTitle, spinnerInline, spinnerLarge } from "../ui";

export interface PreviewScreenProps {
  rectify: RectifyResponse;
  showPreview?: boolean;
  onBack: () => void;
  onPredicted: (prediction: PredictionResponse) => void;
}

export default function PreviewScreen({
  rectify,
  showPreview = true,
  onBack,
  onPredicted,
}: PreviewScreenProps) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const autoRunStarted = useRef(false);

  const run = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      // Always the server's active model: the UI does not name or pick models.
      const prediction = await api.predict(rectify.capture_id, { model_id: null });
      onPredicted(prediction);
    } catch (e) {
      setError(isApiError(e) ? friendlyMessage(e.code, e.message) : String(e));
    } finally {
      setRunning(false);
    }
  }, [onPredicted, rectify.capture_id]);

  useEffect(() => {
    if (showPreview || autoRunStarted.current) return;
    autoRunStarted.current = true;
    void run();
  }, [run, showPreview]);

  if (!showPreview) {
    return (
      <div className={loadingScreen} aria-live="polite">
        {error ? (
          <>
            <div className={msg.error}>{error}</div>
            <div className="flex items-center justify-center gap-3 flex-wrap mt-3">
              <button type="button" className={btn.primary} onClick={() => void run()}>
                Try again
              </button>
              <button type="button" className={btn.ghost} onClick={onBack}>
                Re-adjust corners
              </button>
            </div>
          </>
        ) : (
          <>
            <span className={spinnerLarge} />
            {running ? "Classifying ECG findings…" : "Preparing ECG analysis…"}
          </>
        )}
      </div>
    );
  }

  return (
    <div>
      <h1 className={`${sectionTitle} mt-0 mx-0 mb-1`}>Preview</h1>

      <div className="grid grid-cols-2 gap-3.5 max-narrow:grid-cols-1">
        <div className="border border-line rounded-card overflow-hidden bg-black">
          <img className="w-full block" src={rectify.files.corrected} alt="Corrected sheet" />
          <div className="py-2 px-3 text-[0.8rem] text-ink-muted bg-panel border-t border-line">Corrected</div>
        </div>
        <div className="border border-line rounded-card overflow-hidden bg-black">
          <img className="w-full block" src={rectify.files.model_input} alt="Model input" />
          <div className="py-2 px-3 text-[0.8rem] text-accent font-semibold bg-panel border-t border-line">Model input</div>
        </div>
      </div>

      <div className={`${panel} mb-4.5 mt-3`}>
        {error ? <div className={msg.error}>{error}</div> : null}

        <div className="flex items-center gap-3 flex-wrap mt-3">
          <button
            type="button"
            className={btn.primary}
            onClick={() => void run()}
            disabled={running}
          >
            {running ? (
              <>
                <span className={spinnerInline} /> Running model…
              </>
            ) : (
              "Run model"
            )}
          </button>
          <button type="button" className={btn.ghost} onClick={onBack} disabled={running}>
            Re-adjust corners
          </button>
        </div>
      </div>
    </div>
  );
}
