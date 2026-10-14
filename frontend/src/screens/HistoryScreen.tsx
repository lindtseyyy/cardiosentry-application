import { useEffect, useState } from "react";
import { api, friendlyMessage, isApiError } from "../api/client";
import type { CaptureSummary } from "../api/types";
import { useApp } from "../AppContext";
import { formatDateTime } from "../utils/date";
import { btn, loadingBlock, msg, panel, sectionSub, sectionTitle } from "../ui";

export interface HistoryScreenProps {
  onOpenCapture: (id: string) => void;
  onNewCapture?: () => void;
}

export default function HistoryScreen({
  onOpenCapture,
}: HistoryScreenProps) {
  const { config } = useApp();
  const [captures, setCaptures] = useState<CaptureSummary[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const displayNames = config?.active_model.display_names ?? {};

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .listCaptures(1)
      .then((r) => {
        if (cancelled) return;
        setCaptures(r.captures);
        setPage(r.page);
        setHasMore(r.has_more);
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
  }, []);

  async function loadMore() {
    setLoadingMore(true);
    setError(null);
    try {
      const r = await api.listCaptures(page + 1);
      setCaptures((prev) => [...prev, ...r.captures]);
      setPage(r.page);
      setHasMore(r.has_more);
    } catch (e) {
      setError(isApiError(e) ? friendlyMessage(e.code, e.message) : String(e));
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div>
      <h1 className={`${sectionTitle} mt-0 mx-0 mb-1`}>History</h1>
      <p className={`${sectionSub} mt-0 mx-0`}>
        {captures.length} capture{captures.length === 1 ? "" : "s"}
      </p>

      {error ? <div className={msg.error}>{error}</div> : null}

      {loading ? (
        <div className={loadingBlock}>Loading history…</div>
      ) : captures.length === 0 ? (
        <div className={`${panel} mb-4.5 text-center text-ink-muted`}>No captures yet.</div>
      ) : (
        <div className="flex flex-col gap-3">
          {captures.map((c) => (
            <button
              key={c.capture_id}
              type="button"
              className="flex gap-3.5 items-center bg-panel border-line rounded-card p-3 text-left min-h-11 hover:border-line-strong hover:bg-panel-hover"
              onClick={() => onOpenCapture(c.capture_id)}
            >
              <div className="size-19 rounded-control overflow-hidden bg-black flex-none">
                {c.thumbnail_url ? (
                  <img className="size-full object-cover" src={c.thumbnail_url} alt="" loading="lazy" />
                ) : (
                  <span className="size-full flex items-center justify-center text-ink-faint text-[1.4rem]">ECG</span>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold flex items-center gap-2">
                  <span className="tabular-nums">{c.capture_id}</span>
                </div>
                <div className="text-ink-muted text-[0.8rem] mt-0.5">{formatDateTime(c.created_utc)}</div>
                {c.sheet_id ? (
                  <div className="text-ink-muted text-[0.8rem] mt-0.5">sheet {c.sheet_id}</div>
                ) : null}
                {c.latest_positive.length ? (
                  <div className="flex items-center gap-3 flex-wrap mt-1.5">
                    {c.latest_positive.map((l) => (
                      <span key={l} className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.75 text-[0.78rem] font-semibold whitespace-nowrap bg-positive-wash text-positive-ink">
                        {displayNames[l] ?? l}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </button>
          ))}
        </div>
      )}

      {hasMore ? (
        <div className="flex justify-center mt-4.5">
          <button
            type="button"
            className={btn.ghost}
            onClick={loadMore}
            disabled={loadingMore}
          >
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
