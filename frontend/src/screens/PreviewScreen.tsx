import { useCallback, useEffect, useRef, useState } from "react";
import { api, friendlyMessage, isApiError } from "../api/client";
import type { PredictionResponse, RectifyResponse } from "../api/types";

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
      <div className="loading-block screen-center" aria-live="polite">
        {error ? (
          <>
            <div className="msg error">{error}</div>
            <div className="hstack mt" style={{ justifyContent: "center" }}>
              <button type="button" className="primary" onClick={() => void run()}>
                Try again
              </button>
              <button type="button" className="ghost" onClick={onBack}>
                Re-adjust corners
              </button>
            </div>
          </>
        ) : (
          <>
            <span className="spinner" />
            {running ? "Classifying ECG findings…" : "Preparing ECG analysis…"}
          </>
        )}
      </div>
    );
  }

  return (
    <div>
      <h1 className="section-title">Preview</h1>

      <div className="preview-grid">
        <div className="preview-cell">
          <img src={rectify.files.corrected} alt="Corrected sheet" />
          <div className="cell-cap">Corrected</div>
        </div>
        <div className="preview-cell">
          <img src={rectify.files.model_input} alt="Model input" />
          <div className="cell-cap exact">Model input</div>
        </div>
      </div>

      <div className="panel mt">
        {error ? <div className="msg error">{error}</div> : null}

        <div className="hstack mt">
          <button
            type="button"
            className="primary"
            onClick={() => void run()}
            disabled={running}
          >
            {running ? (
              <>
                <span className="spinner" /> Running model…
              </>
            ) : (
              "Run model"
            )}
          </button>
          <button type="button" className="ghost" onClick={onBack} disabled={running}>
            Re-adjust corners
          </button>
        </div>
      </div>
    </div>
  );
}
