import { useEffect, useMemo, useState } from "react";
import { api, friendlyMessage, isApiError } from "../api/client";
import type { CaptureRecord, PredictionRecord } from "../api/types";
import { useApp } from "../AppContext";
import ExplainPanel from "../components/ExplainPanel";
import GuidancePanel from "../components/GuidancePanel";
import PredictionLabels from "../components/PredictionLabels";
import { formatDateTime } from "../utils/date";

export interface CaptureDetailScreenProps {
  captureId: string;
  onDeleted: () => void;
}

function RunView({
  run,
  fallbackDisplayNames,
  blind,
  guidanceModelIds,
  captureId,
  isAdmin,
}: {
  run: PredictionRecord;
  fallbackDisplayNames: Record<string, string>;
  blind: boolean;
  guidanceModelIds: string[];
  captureId: string;
  isAdmin?: boolean;
}) {
  const scoreLabels = Object.keys(run.scores);
  const labels = (run.descriptor_snapshot?.labels ?? scoreLabels).filter(
    (label) => label in run.scores
  );
  const displayNames = run.descriptor_snapshot?.display_names ?? fallbackDisplayNames;
  return (
    <div className="panel">
      <h2>Prediction · {formatDateTime(run.created_utc)}</h2>
      <PredictionLabels
        labels={labels}
        displayNames={displayNames}
        scores={run.scores}
        positive={run.positive}
        blind={blind}
        isAdmin={isAdmin}
      />
      {!blind && guidanceModelIds.includes(run.model.id) ? (
        <GuidancePanel captureId={captureId} runId={run.run_id} />
      ) : null}
    </div>
  );
}

export default function CaptureDetailScreen({
  captureId,
  onDeleted,
}: CaptureDetailScreenProps) {
  const { config, isAdmin } = useApp();

  const [record, setRecord] = useState<CaptureRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const configDisplayNames = config?.active_model.display_names ?? {};

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getCapture(captureId)
      .then((r) => {
        if (!cancelled) setRecord(r);
      })
      .catch((e) => {
        if (!cancelled)
          setError(isApiError(e) ? friendlyMessage(e.code, e.message) : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [captureId]);

  // The run the attribution maps should explain: the newest one from the model
  // the panel will actually call (the active model), so the scores shown beside
  // a map came from the same checkpoint that produced it.
  const latestRun = useMemo(() => {
    const runs = record?.prediction_runs ?? [];
    const activeId = config?.active_model.id;
    const mine = runs.filter((r) => r.model.id === activeId);
    return (mine.length ? mine : runs)[Math.max(0, (mine.length ? mine : runs).length - 1)];
  }, [record, config]);

  async function deleteCapture() {
    if (!window.confirm("Delete this capture? It moves to the trash on the server."))
      return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteCapture(captureId);
      onDeleted();
    } catch (e) {
      setDeleteError(isApiError(e) ? friendlyMessage(e.code, e.message) : String(e));
      setDeleting(false);
    }
  }

  if (loading) {
    return <div className="loading-block">Loading capture…</div>;
  }
  if (error && !record) {
    return <div className="msg error">{error}</div>;
  }
  if (!record) return null;

  return (
    <div>
      <div className="spread">
        <h1 className="section-title" style={{ marginBottom: 0 }}>
          Capture details
        </h1>
        <button
          type="button"
          className="danger small"
          onClick={deleteCapture}
          disabled={deleting}
        >
          {deleting ? "Deleting…" : "Delete capture"}
        </button>
      </div>
      <p className="capture-id mono">{captureId}</p>

      {error ? <div className="msg error">{error}</div> : null}
      {deleteError ? <div className="msg error">{deleteError}</div> : null}

      {(record.prediction_runs ?? []).length === 0 ? (
        <div className="panel muted">No prediction runs yet.</div>
      ) : (
        (record.prediction_runs ?? []).map((run) => (
          <RunView
            key={run.run_id}
            run={run}
            fallbackDisplayNames={configDisplayNames}
            blind={
              !!record.session?.blind_mode && !record.annotation?.labels_entered_utc
            }
            guidanceModelIds={config?.guidance.model_ids ?? []}
            captureId={captureId}
            isAdmin={isAdmin}
          />
        ))
      )}

      {record.preprocess ? (
        <ExplainPanel
          captureId={captureId}
          runId={latestRun?.run_id ?? null}
          positive={latestRun?.positive ?? []}
          blind={
            !!record.session?.blind_mode && !record.annotation?.labels_entered_utc
          }
        />
      ) : null}
    </div>
  );
}
