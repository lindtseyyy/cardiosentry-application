import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, AUTH_REQUIRED_EVENT, friendlyMessage, isApiError } from "./api/client";
import { AppContext, type AppData } from "./AppContext";
import type {
  AppConfig,
  CaptureRecord,
  CaptureUploadResponse,
  HealthResponse,
  ModelsResponse,
  PredictionResponse,
  RectifyResponse,
} from "./api/types";
import AccountScreen from "./screens/AccountScreen";
import AuthScreen from "./screens/AuthScreen";
import CaptureScreen from "./screens/CaptureScreen";
import CaptureDetailScreen from "./screens/CaptureDetailScreen";
import CornerEditScreen from "./screens/CornerEditScreen";
import HistoryScreen from "./screens/HistoryScreen";
import PreviewScreen from "./screens/PreviewScreen";
import PrivacyScreen from "./screens/PrivacyScreen";
import PrivacyModal from "./components/PrivacyModal";
import ResultScreen from "./screens/ResultScreen";
import { btn, loadingScreen, msg, spinnerLarge } from "./ui";

// Keep the preview implementation available, but skip it in the patient flow.
// Flip this flag to restore the corrected/model-input review step.
const SHOW_PREVIEW_STEP = false;

// Every step after the upload is addressable by URL (#/scan/<capture id>…),
// so a reload re-opens the same capture from the server instead of dropping
// back to an empty capture screen. The capture itself already lives on disk;
// only the in-memory screen state was being lost.
type Screen =
  | { name: "capture" }
  | { name: "history" }
  | { name: "privacy" }
  | { name: "account" }
  | { name: "detail"; captureId: string }
  | { name: "corner"; captureId: string }
  | { name: "preview"; rectify: RectifyResponse }
  | { name: "result"; captureId: string; runId: string; prediction?: PredictionResponse };

const ID = "[A-Za-z0-9_.-]+";
const menuItem = "flex items-center w-full px-3.5 py-2.5 min-h-11 border-0 rounded-control text-[0.92rem] text-left [transition:background_0.12s_ease,color_0.12s_ease]";
const menuItemActive = "bg-accent/12 text-accent-strong font-semibold";
const menuItemInactive = "bg-transparent text-ink font-medium hover:bg-panel-3 focus-visible:bg-panel-3";
// Desktop topbar links: thin outline, quiet by default, tinted when they are the current page.
const navLink = "min-h-9 px-3 border border-line rounded-control bg-panel text-[0.9rem] font-medium text-ink-muted hover:bg-panel-3 hover:border-line-strong hover:text-ink aria-[current=page]:bg-accent/12 aria-[current=page]:border-accent/45 aria-[current=page]:text-accent-strong focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-accent focus-visible:outline-offset-2 max-nav:hidden";

function screenFromHash(): Screen {
  const h = window.location.hash;
  if (/^#\/history$/.test(h)) return { name: "history" };
  if (/^#\/privacy$/.test(h)) return { name: "privacy" };
  if (/^#\/(account|settings)$/.test(h)) return { name: "account" };
  const detail = h.match(new RegExp(`^#/capture/(${ID})$`));
  if (detail) return { name: "detail", captureId: detail[1] };
  const result = h.match(new RegExp(`^#/scan/(${ID})/result/(${ID})$`));
  if (result) return { name: "result", captureId: result[1], runId: result[2] };
  const corner = h.match(new RegExp(`^#/scan/(${ID})$`));
  if (corner) return { name: "corner", captureId: corner[1] };
  return { name: "capture" };
}

function hashFor(screen: Screen): string {
  switch (screen.name) {
    case "capture":
      return "";
    case "history":
      return "#/history";
    case "privacy":
      return "#/privacy";
    case "account":
      return "#/account";
    case "detail":
      return `#/capture/${screen.captureId}`;
    case "corner":
      return `#/scan/${screen.captureId}`;
    // Classifying is transient: a reload there returns to the corner step
    // rather than silently starting a second prediction run.
    case "preview":
      return `#/scan/${screen.rectify.capture_id}`;
    case "result":
      return `#/scan/${screen.captureId}/result/${screen.runId}`;
  }
}

/** Rebuild the upload response the corner editor needs from the stored record. */
function uploadFromRecord(rec: CaptureRecord): CaptureUploadResponse | null {
  if (!rec.detection) return null;
  const base = `/api/captures/${encodeURIComponent(rec.capture_id)}`;
  return {
    capture_id: rec.capture_id,
    original: rec.original,
    ecg_gate: rec.ecg_gate ?? null,
    detection: rec.detection,
    quality: rec.quality_original ?? ({} as CaptureUploadResponse["quality"]),
    files: { preview: `${base}/files/preview.jpg`, overlay: `${base}/files/overlay.jpg` },
  };
}

function Restoring({ error, onNew }: { error: string | null; onNew: () => void }) {
  if (!error) {
    return (
      <div className={loadingScreen} aria-live="polite">
        <span className={spinnerLarge} />
        Restoring your capture…
      </div>
    );
  }
  return (
    <div className={loadingScreen}>
      <div className={msg.error}>{error}</div>
      <div className="flex items-center justify-center gap-3 flex-wrap mt-3">
        <button type="button" className={btn.primary} onClick={onNew}>
          Start a new ECG
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const [screen, setScreen] = useState<Screen>(() => screenFromHash());
  const [user, setUser] = useState<string | null | undefined>(undefined);
  const [isAdmin, setIsAdmin] = useState(false);
  const [upload, setUpload] = useState<CaptureUploadResponse | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  const [privacyOpen, setPrivacyOpen] = useState(false);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    // Config + health are critical (labels, model status, and feature flags).
    try {
      const [c, h] = await Promise.all([api.getConfig(), api.getHealth()]);
      setConfig(c);
      setHealth(h);
    } catch (e) {
      setError(isApiError(e) ? friendlyMessage(e.code, e.message) : String(e));
    }
    // Models are best-effort: screens fall back to config.active_model.
    try {
      setModels(await api.getModels());
    } catch {
      setModels(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    const onAuthRequired = () => {
      setUser(null);
      setIsAdmin(false);
      setUpload(null);
      setScreen(screenFromHash());
    };
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    api.me()
      .then((resp) => {
        if (!cancelled) {
          setUser(resp.username);
          setIsAdmin(!!resp.is_admin || resp.username.toLowerCase() === "admin");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUser(null);
          setIsAdmin(false);
        }
      });
    return () => {
      cancelled = true;
      window.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    };
  }, []);

  useEffect(() => {
    // Our own navigation already set the richer in-memory screen; only a
    // hash we did not produce (back/forward, a typed URL) replaces it.
    const onHash = () =>
      setScreen((prev) =>
        hashFor(prev) === window.location.hash ? prev : screenFromHash()
      );
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const navigate = useCallback((next: Screen) => {
    setScreen(next);
    const hash = hashFor(next);
    if (window.location.hash !== hash) {
      if (hash) window.location.hash = hash;
      else history.pushState(null, "", window.location.pathname + window.location.search);
    }
  }, []);

  // After a reload (or a pasted link) the corner/result screens have only a
  // capture id; fetch the stored record and rebuild what they need.
  const needsUpload = screen.name === "corner" && upload?.capture_id !== screen.captureId;
  const needsPrediction = screen.name === "result" && !screen.prediction;
  const restoreId =
    screen.name === "corner" || screen.name === "result" ? screen.captureId : null;
  const restoreRunId = screen.name === "result" ? screen.runId : null;
  useEffect(() => {
    if (!user || !restoreId || !(needsUpload || needsPrediction)) return;
    let cancelled = false;
    setRestoreError(null);
    api
      .getCapture(restoreId)
      .then((rec) => {
        if (cancelled) return;
        if (restoreRunId) {
          const run = rec.prediction_runs?.find((r) => r.run_id === restoreRunId);
          if (!run) throw new Error("This result is no longer available.");
          setScreen({ name: "result", captureId: restoreId, runId: restoreRunId, prediction: run });
        } else {
          const restored = uploadFromRecord(rec);
          if (!restored) throw new Error("This capture has no paper detection to edit.");
          setUpload(restored);
        }
      })
      .catch((e) => {
        if (!cancelled)
          setRestoreError(isApiError(e) ? friendlyMessage(e.code, e.message) : String(e.message ?? e));
      });
    return () => {
      cancelled = true;
    };
  }, [user, restoreId, restoreRunId, needsUpload, needsPrediction]);

  const ctx = useMemo<AppData>(
    () => ({
      config,
      health,
      models,
      loading,
      error,
      reload: load,
      user: user ?? null,
      isAdmin,
    }),
    [config, health, models, loading, error, load, user, isAdmin]
  );

  const goCapture = useCallback(() => {
    setUpload(null);
    navigate({ name: "capture" });
  }, [navigate]);

  const goHistory = useCallback(() => navigate({ name: "history" }), [navigate]);
  const openPrivacy = useCallback(() => setPrivacyOpen(true), []);
  const closePrivacy = useCallback(() => setPrivacyOpen(false), []);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const hamburgerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setMenuOpen(false);
  }, [screen]);

  useEffect(() => {
    if (!menuOpen) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    function onPointerDown(e: MouseEvent) {
      if (
        menuRef.current &&
        !menuRef.current.contains(e.target as Node) &&
        hamburgerRef.current &&
        !hamburgerRef.current.contains(e.target as Node)
      ) {
        setMenuOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, [menuOpen]);

  useEffect(() => {
    if (screen.name === "privacy") {
      setPrivacyOpen(true);
      navigate({ name: "capture" });
    }
  }, [screen.name, navigate]);
  const goAccount = useCallback(() => navigate({ name: "account" }), [navigate]);

  const goDetail = useCallback(
    (id: string) => navigate({ name: "detail", captureId: id }),
    [navigate]
  );

  async function signOut() {
    try {
      await api.logout();
    } catch {
      /* Clear local state even when the backend is unreachable. */
    }
    setUser(null);
    setIsAdmin(false);
    setUpload(null);
    navigate({ name: "capture" });
  }

  function renderScreen() {
    if (user === undefined) {
      return (
        <div className={loadingScreen} aria-live="polite">
          <span className={spinnerLarge} />
          Checking login…
        </div>
      );
    }
    if (user === null) {
      return screen.name === "privacy" ? (
        <PrivacyScreen onBack={goCapture} />
      ) : (
        <AuthScreen
          onAuthenticated={(username, isAdminVal) => {
            setUser(username);
            setIsAdmin(isAdminVal ?? username.toLowerCase() === "admin");
            void load();
          }}
        />
      );
    }
    switch (screen.name) {
      case "capture":
        return (
          <CaptureScreen
            onUploaded={(resp) => {
              setUpload(resp);
              navigate({ name: "corner", captureId: resp.capture_id });
            }}
            onOpenPrivacy={openPrivacy}
          />
        );
      case "privacy":
        return <PrivacyScreen onBack={goCapture} />;
      case "account":
        return <AccountScreen username={user} onUpdated={setUser} onSignOut={signOut} />;
      case "history":
        return <HistoryScreen onOpenCapture={goDetail} />;
      case "detail":
        return (
          <CaptureDetailScreen
            captureId={screen.captureId}
            onDeleted={goHistory}
          />
        );
      case "corner":
        if (!upload || upload.capture_id !== screen.captureId) {
          return <Restoring error={restoreError} onNew={goCapture} />;
        }
        return (
          <CornerEditScreen
            upload={upload}
            onBack={goCapture}
            onRectified={(rect) => navigate({ name: "preview", rectify: rect })}
          />
        );
      case "preview":
        return (
          <PreviewScreen
            rectify={screen.rectify}
            showPreview={SHOW_PREVIEW_STEP}
            onBack={() =>
              navigate({ name: "corner", captureId: screen.rectify.capture_id })
            }
            onPredicted={(p) =>
              navigate({
                name: "result",
                captureId: p.capture_id,
                runId: p.run_id,
                prediction: p,
              })
            }
          />
        );
      case "result":
        if (!screen.prediction) {
          return <Restoring error={restoreError} onNew={goCapture} />;
        }
        return <ResultScreen prediction={screen.prediction} />;
    }
  }

  return (
    <AppContext.Provider value={ctx}>
      <div className="max-w-[720px] wide:max-w-[880px] min-h-dvh mx-auto px-4 pb-[calc(8px_+_env(safe-area-inset-bottom))] flex flex-col print:max-w-none print:min-h-0 print:p-0">
        <div className="relative flex items-center justify-between gap-3 py-3.5 border-b border-line mb-4.5 print:hidden">
          <button
            type="button"
            className="flex items-center gap-2 min-h-11 p-0 bg-transparent border-0 rounded-control text-ink text-[1.15rem] font-bold tracking-[0.2px] hover:text-accent focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-accent focus-visible:outline-offset-4"
            onClick={goCapture}
            aria-label="CardioSentry — Classify ECG"
          >
            <img className="size-6 object-contain flex-none" src="/favicon.png" alt="" />
            CardioSentry
          </button>
          {user ? (
            <nav className="flex items-center gap-1.5" aria-label="Main">
              <button
                type="button"
                className={navLink}
                onClick={goCapture}
                aria-current={screen.name === "capture" ? "page" : undefined}
              >
                Classify ECG
              </button>
              <button
                type="button"
                className={navLink}
                onClick={goHistory}
                aria-current={screen.name === "history" ? "page" : undefined}
              >
                History
              </button>
              <button
                type="button"
                className={navLink}
                onClick={goAccount}
                aria-current={screen.name === "account" ? "page" : undefined}
              >
                Settings
              </button>
              <span className="w-px h-5 mx-2 bg-line-strong max-nav:hidden" aria-hidden="true" />
              <span className="inline-flex items-center gap-1.5 px-1 min-h-9 min-w-0 text-ink-muted text-[0.88rem] font-medium cursor-default select-text max-nav:text-[0.82rem] max-nav:mr-1 max-tiny:text-[0.78rem]" title={`Logged in as ${user}`}>
                <svg
                  className="size-5 flex-none max-tiny:size-4.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <circle cx="12" cy="12" r="10" />
                  <circle cx="12" cy="10" r="3" />
                  <path d="M7 20.66V19a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v1.66" />
                </svg>
                <span className="max-w-35 truncate max-nav:max-w-27.5 max-tiny:max-w-20">{user}</span>
              </span>
              <button
                ref={hamburgerRef}
                type="button"
                className="hidden max-nav:inline-flex items-center justify-center size-11 min-h-11 min-w-11 p-0 bg-transparent border-line rounded-control text-ink [transition:background_0.15s_ease,border-color_0.15s_ease] hover:bg-panel-3 aria-expanded:bg-panel-3 focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-accent focus-visible:outline-offset-2 max-tiny:size-10 max-tiny:min-w-10 max-tiny:min-h-10"
                onClick={() => setMenuOpen((open) => !open)}
                aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"}
                aria-expanded={menuOpen}
                aria-controls="topbar-menu"
              >
                <svg
                  width="22"
                  height="22"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  {menuOpen ? (
                    <>
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </>
                  ) : (
                    <>
                      <line x1="3" y1="6" x2="21" y2="6" />
                      <line x1="3" y1="12" x2="21" y2="12" />
                      <line x1="3" y1="18" x2="21" y2="18" />
                    </>
                  )}
                </svg>
              </button>
              {menuOpen ? (
                <div id="topbar-menu" ref={menuRef} className="absolute top-[calc(100%+6px)] right-0 min-w-48 bg-panel border border-line rounded-card shadow-menu p-1.5 flex flex-col gap-0.5 z-100 animate-menu-in" role="menu">
                  <button
                    type="button"
                    className={`${menuItem} ${screen.name === "capture" ? menuItemActive : menuItemInactive}`}
                    onClick={() => {
                      setMenuOpen(false);
                      goCapture();
                    }}
                    role="menuitem"
                  >
                    Classify ECG
                  </button>
                  <button
                    type="button"
                    className={`${menuItem} ${screen.name === "history" ? menuItemActive : menuItemInactive}`}
                    onClick={() => {
                      setMenuOpen(false);
                      goHistory();
                    }}
                    role="menuitem"
                  >
                    History
                  </button>
                  <button
                    type="button"
                    className={`${menuItem} ${screen.name === "account" ? menuItemActive : menuItemInactive}`}
                    onClick={() => {
                      setMenuOpen(false);
                      goAccount();
                    }}
                    role="menuitem"
                  >
                    Settings
                  </button>
                </div>
              ) : null}
            </nav>
          ) : null}
        </div>

        {error ? (
          <div className="flex items-center gap-3 flex-wrap bg-error-wash border border-error-line text-error-ink rounded-card px-4 py-3 mb-4">
            <span>{error}</span>
            <button type="button" className="bg-emergency border-emergency text-white ml-auto" onClick={load}>
              Retry
            </button>
          </div>
        ) : null}

        <main className="flex-[1_0_auto] flex flex-col pb-7">{renderScreen()}</main>

        <footer className="pt-3 border-t border-line text-center print:hidden">
          <button type="button" className={btn.link} onClick={openPrivacy}>
            Data Privacy Notice
          </button>
        </footer>
        <PrivacyModal open={privacyOpen} onClose={closePrivacy} />
      </div>
    </AppContext.Provider>
  );
}
