import { type RefObject, useEffect, useMemo, useRef, useState } from "react";
import { api, friendlyMessage, isApiError } from "../api/client";
import type { CaptureRecord, PredictionResponse } from "../api/types";
import { useApp } from "../AppContext";
import ExplainPanel from "../components/ExplainPanel";
import GuidancePanel from "../components/GuidancePanel";
import PredictionLabels from "../components/PredictionLabels";
import { formatDateTime } from "../utils/date";
import { btn, loadingBlock, msg, sectionTitle } from "../ui";

const printMetaLabel = "text-[7.5pt] font-bold tracking-[0.06em] uppercase text-[#555]";
const printMetaValue = "mt-px mx-0 mb-0 text-[9.5pt] [overflow-wrap:anywhere]";

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
    <div ref={rootRef}>
      <div className="flex items-center justify-between gap-3 flex-wrap mb-4.5 print:hidden">
        <h1 className={`${sectionTitle} mt-0 mx-0 mb-1`}>Result</h1>
        {!recordLoading && !blind ? (
          <button type="button" className={`${btn.small} ${btn.matteBlue} print:hidden`} onClick={() => window.print()}>
            Print Report
          </button>
        ) : null}
      </div>

      {record && !blind ? (
        <section className="hidden print:block print:mb-3.5" aria-hidden="true">
          <div className="flex items-center gap-2.5 pb-2 border-b-2 border-[#111]">
            <img className="size-6.5" src="/favicon.png" alt="" />
            <div>
              <strong className="block text-[15pt]">CardioSentry ECG screening report</strong>
              <span className="text-[9pt] text-[#444]">Screening support only — not a diagnosis</span>
            </div>
          </div>
          <dl className="grid grid-cols-3 gap-x-4 gap-y-1.5 mt-2.5 mx-0 mb-3">
            <div className="min-w-0">
              <dt className={printMetaLabel}>ECG captured</dt>
              <dd className={printMetaValue}>{formatDateTime(record.created_utc)}</dd>
            </div>
            <div className="min-w-0">
              <dt className={printMetaLabel}>Analysed</dt>
              <dd className={printMetaValue}>{formatDateTime(prediction.created_utc)}</dd>
            </div>
            <div className="min-w-0">
              <dt className={printMetaLabel}>Printed</dt>
              <dd className={printMetaValue}>{formatDateTime(new Date().toISOString())}</dd>
            </div>
            {record.session?.sheet_id ? (
              <div className="min-w-0">
                <dt className={printMetaLabel}>Sheet ID</dt>
                <dd className={printMetaValue}>{record.session.sheet_id}</dd>
              </div>
            ) : null}
            <div className="min-w-0">
              <dt className={printMetaLabel}>Capture</dt>
              <dd className="mt-px mx-0 mb-0 text-[8.5pt] [overflow-wrap:anywhere] tabular-nums">{captureId}</dd>
            </div>
          </dl>
          {sheetImage ? (
            <figure className="m-0 break-inside-avoid">
              <img className="block w-full max-h-[95mm] object-contain border border-[#bbb]" src={sheetImage} alt="ECG sheet analysed" />
            </figure>
          ) : null}
        </section>
      ) : null}

      {recordError ? <div className={msg.warn}>{recordError}</div> : null}

      {recordLoading ? (
        <div className={loadingBlock}>Loading result…</div>
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
        <footer className="hidden print:block print:mt-4 print:pt-2 print:border-t print:border-[#999] print:text-[8pt] print:text-[#444]">
          {config?.guidance.disclaimer ??
            "Screening and decision support only. This experimental image-model output is not a diagnosis and does not replace a clinician-interpreted ECG."}
        </footer>
      ) : null}
    </div>
  );
}
