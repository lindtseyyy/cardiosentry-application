import { useEffect, useRef } from "react";
import { useApp } from "../AppContext";
import PrivacyNotice from "./PrivacyNotice";

export interface PrivacyModalProps {
  open: boolean;
  onClose: () => void;
}

export default function PrivacyModal({ open, onClose }: PrivacyModalProps) {
  const { config } = useApp();
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      if (!dialog.open) {
        dialog.showModal();
      }
    } else {
      if (dialog.open) {
        dialog.close();
      }
    }
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      className="privacy-dialog"
      aria-labelledby="privacy-modal-title"
      onClose={onClose}
      onClick={(e) => {
        // A click on the backdrop lands on the <dialog> itself.
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="privacy-dialog-card">
        <header className="privacy-dialog-head">
          <h2 id="privacy-modal-title">Data Privacy Notice</h2>
          <button
            type="button"
            className="dialog-close-button"
            aria-label="Close"
            onClick={onClose}
          >
            ✕
          </button>
        </header>

        <div className="privacy-dialog-body">
          <PrivacyNotice privacy={config?.privacy ?? null} />
        </div>

      </div>
    </dialog>
  );
}
