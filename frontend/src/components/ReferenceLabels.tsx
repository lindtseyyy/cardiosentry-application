import { useEffect, useState } from "react";
import { api, friendlyMessage, isApiError } from "../api/client";
import type { AnnotationRecord, CaptureRecord } from "../api/types";
import { btn, field, fieldLabel, msg, panel, panelTitle } from "../ui";

const TRUTH_SOURCES = [
  "cardiologist report",
  "PTB-XL metadata",
  "visual inspection",
  "unknown",
];

export interface ReferenceLabelsProps {
  captureId: string;
  labels: string[];
  displayNames: Record<string, string>;
  annotation: AnnotationRecord;
  blindMode?: boolean;
  onSaved: (record: CaptureRecord) => void;
}

/**
 * Reference-label panel (§17.6): four checkboxes matching the model heads,
 * truth source, notes, and the labels_entered_before_prediction safeguard.
 */
export default function ReferenceLabels({
  captureId,
  labels,
  displayNames,
  annotation,
  blindMode = false,
  onSaved,
}: ReferenceLabelsProps) {
  const [refLabels, setRefLabels] = useState<Record<string, boolean>>(
    annotation.reference_labels ?? {}
  );
  const [truthSource, setTruthSource] = useState<string>(
    annotation.truth_source ?? ""
  );
  const [notes, setNotes] = useState<string>(annotation.notes ?? "");
  const [beforePrediction, setBeforePrediction] = useState<boolean>(
    annotation.labels_entered_before_prediction ?? blindMode
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Re-sync if the record changes underneath us (e.g. after a save elsewhere).
  useEffect(() => {
    setRefLabels(annotation.reference_labels ?? {});
    setTruthSource(annotation.truth_source ?? "");
    setNotes(annotation.notes ?? "");
    setBeforePrediction(annotation.labels_entered_before_prediction ?? blindMode);
  }, [annotation, blindMode]);

  function toggleLabel(label: string, value: boolean) {
    setRefLabels((prev) => {
      const next = { ...prev };
      if (value) next[label] = true;
      else delete next[label];
      return next;
    });
  }

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const record = await api.patchAnnotation(captureId, {
        reference_labels: refLabels,
        labels_entered_before_prediction: beforePrediction,
        truth_source: truthSource || null,
        notes: notes || null,
      });
      setSaved(true);
      onSaved(record);
    } catch (e) {
      setError(isApiError(e) ? friendlyMessage(e.code, e.message) : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={`${panel} mb-4.5`}>
      <h2 className={`${panelTitle} mx-0 mt-0`}>Reference labels</h2>

      <div className="grid grid-cols-[1fr_1fr] gap-2 max-phone:grid-cols-[1fr]">
        {labels.map((label) => (
          <label key={label} className="flex items-center gap-2.5 bg-panel-2 border border-line rounded-control px-3 py-2.5 min-h-11">
            <input
              type="checkbox"
              className="size-5 accent-accent m-[3px_3px_3px_4px]"
              checked={!!refLabels[label]}
              onChange={(e) => toggleLabel(label, e.target.checked)}
            />
            <span>{displayNames[label] ?? label}</span>
          </label>
        ))}
      </div>

      <div className="flex flex-col gap-3 mt-3">
        <div className={field}>
          <label htmlFor="truth-source" className={fieldLabel}>Truth source</label>
          <select
            id="truth-source"
            value={truthSource}
            onChange={(e) => setTruthSource(e.target.value)}
          >
            <option value="">— select —</option>
            {TRUTH_SOURCES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        <div className={field}>
          <label htmlFor="ref-notes" className={fieldLabel}>Notes</label>
          <textarea
            id="ref-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Optional"
          />
        </div>

        <div className="flex items-center justify-between gap-3 bg-panel-2 border border-line rounded-control px-3.5 py-3">
          <div className="flex flex-col">
            <span className="font-semibold">Labels entered before prediction</span>
          </div>
          <span className="relative w-13 h-7.5 flex-none">
            <input
              type="checkbox"
              className="peer opacity-0 size-0 m-[3px_3px_3px_4px]"
              id="before-prediction"
              checked={beforePrediction}
              onChange={(e) => setBeforePrediction(e.target.checked)}
            />
            <span className="absolute inset-0 bg-panel-3 border border-line rounded-full [transition:background_0.15s] before:content-[''] before:absolute before:size-5.5 before:left-0.75 before:top-0.75 before:bg-ink-muted before:rounded-full before:[transition:translate_0.15s,background_0.15s] peer-checked:bg-accent-strong peer-checked:border-accent-strong peer-checked:before:translate-x-5.5 peer-checked:before:bg-white" />
          </span>
        </div>
      </div>

      {error ? <div className={`${msg.error} mt-3`}>{error}</div> : null}
      {saved ? (
        <div className={`${msg.info} mt-3`}>Reference labels saved.</div>
      ) : null}

      <div className="mt-3">
        <button type="button" className={btn.primary} onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save labels"}
        </button>
      </div>
    </div>
  );
}
