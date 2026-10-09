import { type RefObject, useEffect, useMemo, useRef, useState } from "react";
import { api, friendlyMessage, isApiError } from "../api/client";
import type { CaptureRecord, PredictionResponse } from "../api/types";
import { useApp } from "../AppContext";
import ExplainPanel from "../components/ExplainPanel";
import GuidancePanel from "../components/GuidancePanel";
import PredictionLabels from "../components/PredictionLabels";
import { formatDateTime } from "../utils/date";

export interface ResultScreenProps {
  prediction: PredictionResponse;
}


/** Open every collapsed section marked for print, and close them again after. */
function usePrintExpansion(root: RefObject<HTMLElement>) {
  useEffect(() => {
    let opened: HTMLDetailsElement[] = [];
    const before = () => {
      opened = Array.from(
        root.current?.querySelectorAll<HTMLDetailsElement>("details[data-print-open]:not([open])") ?? []
      );
      opened.forEach((el) => (el.open = true));
    };
    const after = () => {
      opened.forEach((el) => (el.open = false));
      opened = [];
    };
    window.addEventListener("beforeprint", before);
    window.addEventListener("afterprint", after);
    return () => {
      window.removeEventListener("beforeprint", before);
      window.removeEventListener("afterprint", after);
    };
  }, [root]);
}

export default function ResultScreen({ prediction }: ResultScreenProps) {
  const { config, isAdmin } = useApp();
  const [record, setRecord] = useState<CaptureRecord | null>(null);
  const [recordLoading, setRecordLoading] = useState(true);
  const [recordError, setRecordError] = useState<string | null>(null);
  const captureId = prediction.capture_id;
  const rootRef = useRef<HTMLDivElement>(null);
  usePrintExpansion(rootRef);

  useEffect(() => {
    let cancelled = false;
    setRecordLoading(true);
    setRecordError(null);
    api
      .getCapture(captureId)
      .then((r) => {
        if (!cancelled) setRecord(r);
      })
      .catch((e) => {
        if (!cancelled)
          setRecordError(isApiError(e) ? friendlyMessage(e.code, e.message) : String(e));
      })
      .finally(() => {
        if (!cancelled) setRecordLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [captureId]);

  const configLabels = config?.active_model.labels ?? [];
  const displayNames = config?.active_model.display_names ?? {};
  const orderedLabels = useMemo(() => {
    const scoreKeys = Object.keys(prediction.scores);
    const inOrder = configLabels.filter((label) => label in prediction.scores);
    const extra = scoreKeys.filter((label) => !configLabels.includes(label));
    return [...inOrder, ...extra];
  }, [configLabels, prediction.scores]);

  const labelsEntered = !!record?.annotation?.labels_entered_utc;
  const blind = !record || (!!record.session?.blind_mode && !labelsEntered);

  const sheetImage = record
    ? `/api/captures/${encodeURIComponent(captureId)}/files/${
        record.correction ? "corrected.png" : "original.jpg"
      }`
    : null;

  return (
    <div ref={rootRef} className="result-screen">
      <div className="spread page-heading">
        <h1 className="section-title">Result</h1>
        {!recordLoading && !blind ? (
          <button type="button" className="small matte-blue no-print" onClick={() => window.print()}>
            Print Report
          </button>
        ) : null}
      </div>

      {record && !blind ? (
        <section className="print-only print-report-head" aria-hidden="true">
          <div className="print-report-title">
            <img src="/favicon.png" alt="" />
            <div>
              <strong>CardioSentry ECG screening report</strong>
              <span>Screening support only — not a diagnosis</span>
            </div>
          </div>
          <dl className="print-meta">
            <div>
              <dt>ECG captured</dt>
              <dd>{formatDateTime(record.created_utc)}</dd>
            </div>
            <div>
              <dt>Analysed</dt>
              <dd>{formatDateTime(prediction.created_utc)}</dd>
            </div>
            <div>
              <dt>Printed</dt>
              <dd>{formatDateTime(new Date().toISOString())}</dd>
            </div>
            {record.session?.sheet_id ? (
              <div>
                <dt>Sheet ID</dt>
                <dd>{record.session.sheet_id}</dd>
              </div>
            ) : null}
            <div>
              <dt>Capture</dt>
              <dd className="mono">{captureId}</dd>
            </div>
          </dl>
          {sheetImage ? (
            <figure className="print-sheet">
              <img src={sheetImage} alt="ECG sheet analysed" />
            </figure>
          ) : null}
        </section>
      ) : null}

      {recordError ? <div className="msg warn">{recordError}</div> : null}

      {recordLoading ? (
        <div className="loading-block">Loading result…</div>
      ) : (
        <>
          <PredictionLabels
            labels={orderedLabels}
            displayNames={displayNames}
            scores={prediction.scores}
            positive={prediction.positive}
            blind={blind}
            isAdmin={isAdmin}
          />

          {!blind && config?.guidance.model_ids.includes(prediction.model.id) ? (
            <GuidancePanel captureId={captureId} runId={prediction.run_id} />
          ) : null}

          <ExplainPanel
            captureId={captureId}
            runId={prediction.run_id}
            positive={prediction.positive}
            blind={blind}
            autoGenerate
          />
        </>
      )}

      {record && !blind ? (
        <footer className="print-only print-footer">
          {config?.guidance.disclaimer ??
            "Screening and decision support only. This experimental image-model output is not a diagnosis and does not replace a clinician-interpreted ECG."}
        </footer>
      ) : null}
    </div>
  );
}
