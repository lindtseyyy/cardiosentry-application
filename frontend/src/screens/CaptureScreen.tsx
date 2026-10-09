import { useRef, useState } from "react";
import { friendlyMessage, isApiError, uploadCapture } from "../api/client";
import type { CaptureUploadResponse } from "../api/types";
import { useApp } from "../AppContext";
import { PrivacySummary } from "../components/PrivacyNotice";

export interface CaptureScreenProps {
  onUploaded: (resp: CaptureUploadResponse) => void;
  onOpenPrivacy: () => void;
}

// Which Data Privacy Notice version this browser last accepted. A
// per-device convenience only: the record of consent that counts is the
// version sent with, and stored in, every capture.
const PRIVACY_ACK_KEY = "cardiosentry.privacyNoticeAck";

function readAck(): string | null {
  try {
    return localStorage.getItem(PRIVACY_ACK_KEY);
  } catch {
    return null;
  }
}

function writeAck(version: string) {
  try {
    localStorage.setItem(PRIVACY_ACK_KEY, version);
  } catch {
    // Private mode / blocked storage: the notice simply shows again next visit.
  }
}

// Monochrome line icons: they take the button's text colour (currentColor).
function CameraIcon() {
  return (
    <svg
      className="btn-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14.5 4h-5L8 6H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-3z" />
      <circle cx="12" cy="13" r="3.5" />
    </svg>
  );
}

function ImageIcon() {
  return (
    <svg
      className="btn-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <path d="m21 15-5-5L5 21" />
    </svg>
  );
}

export default function CaptureScreen({ onUploaded, onOpenPrivacy }: CaptureScreenProps) {
  const { config, health, loading } = useApp();
  const unreachable = !loading && (!config || !health);

  const noticeVersion = config?.privacy.notice_version ?? null;
  const [ackedVersion, setAckedVersion] = useState<string | null>(() => readAck());
  const [consentChecked, setConsentChecked] = useState(false);
  const acked = noticeVersion !== null && ackedVersion === noticeVersion;

  const cameraRef = useRef<HTMLInputElement>(null);
  const galleryRef = useRef<HTMLInputElement>(null);

  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  function acceptNotice() {
    if (!noticeVersion) return;
    writeAck(noticeVersion);
    setAckedVersion(noticeVersion);
  }

  function handleFile(file: File | null, mode: "upload" | "camera") {
    if (!file || uploading || !acked) return;
    setUploading(true);
    setError(null);
    setProgress(0);
    uploadCapture({
      file,
      mode,
      privacyNotice: noticeVersion ?? undefined,
      onProgress: (loaded, total) =>
        setProgress(total > 0 ? loaded / total : 0),
    })
      .then(onUploaded)
      .catch((e) => {
        setError(isApiError(e) ? friendlyMessage(e.code, e.message) : String(e));
      })
      .finally(() => {
        setUploading(false);
        if (cameraRef.current) cameraRef.current.value = "";
        if (galleryRef.current) galleryRef.current.value = "";
      });
  }

  return (
    <div className="capture-screen">

      {/* No status panel: only problems are worth the space. */}
      {unreachable ? <div className="msg error">Backend unreachable.</div> : null}
      {health && health.free_space_warn ? (
        <div className="msg warn">
          Low disk space ({health.free_space_gb} GB free)
        </div>
      ) : null}

      {config && !acked ? (
        <section className="panel privacy-gate" aria-labelledby="privacy-gate-title">
          <h2 id="privacy-gate-title">Data privacy</h2>
          <PrivacySummary />
          <button type="button" className="link-button" onClick={onOpenPrivacy}>
            Read the full Data Privacy Notice
          </button>
          <label className="privacy-consent">
            <input
              type="checkbox"
              checked={consentChecked}
              onChange={(e) => setConsentChecked(e.target.checked)}
            />
            <span>
              I have read the Data Privacy Notice, and I (or the patient, or their
              parent or guardian) consent to this ECG photograph being stored and
              processed as it describes.
            </span>
          </label>
          <button
            type="button"
            className="primary"
            disabled={!consentChecked}
            onClick={acceptNotice}
          >
            Continue
          </button>
        </section>
      ) : null}

      {acked ? (
        <div className="big-actions">
          <button
            type="button"
            className="primary"
            disabled={uploading}
            onClick={() => cameraRef.current?.click()}
          >
            <CameraIcon />
            Take photo
          </button>
          <button
            type="button"
            disabled={uploading}
            onClick={() => galleryRef.current?.click()}
          >
            <ImageIcon />
            Choose photo
          </button>
        </div>
      ) : null}

      {/* hidden native inputs (hand off to camera app — works over plain http LAN) */}
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => handleFile(e.target.files?.[0] ?? null, "camera")}
      />
      <input
        ref={galleryRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => handleFile(e.target.files?.[0] ?? null, "upload")}
      />

      {uploading ? (
        <div className="panel mt">
          <div className="hstack">
            <span className="spinner" />
            <span>Uploading… {Math.round(progress * 100)}%</span>
          </div>
          <div className="progress">
            <div style={{ width: `${progress * 100}%` }} />
          </div>
        </div>
      ) : null}

      {error ? <div className="msg error mt">{error}</div> : null}

    </div>
  );
}
