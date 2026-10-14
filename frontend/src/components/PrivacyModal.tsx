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
      className="w-[min(860px,calc(100vw-32px))] max-h-[calc(100dvh-48px)] m-auto p-0 border border-line-strong rounded-card bg-panel text-ink shadow-modal overflow-hidden backdrop:bg-[rgba(15,23,42,0.6)] backdrop:[backdrop-filter:blur(2px)] md:w-[min(860px,calc(100vw-64px))] md:max-h-[calc(100dvh-80px)] max-compact:w-[calc(100vw-16px)] max-compact:max-h-[calc(100dvh-20px)]"
      aria-labelledby="privacy-modal-title"
      onClose={onClose}
      onClick={(e) => {
        // A click on the backdrop lands on the <dialog> itself.
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex flex-col max-h-[calc(100dvh-50px)] md:max-h-[calc(100dvh-82px)] max-compact:max-h-[calc(100dvh-22px)]">
        <header className="flex items-center justify-between px-6 py-4 border-b border-line shrink-0 bg-panel md:px-8 md:py-4.5 max-compact:px-4 max-compact:py-3">
          <h2 id="privacy-modal-title" className="m-0 text-[1.18rem] font-bold text-ink md:text-[1.25rem]">Data Privacy Notice</h2>
          <button
            type="button"
            className="inline-flex items-center justify-center size-8 min-h-8 p-0 border border-matte-blue rounded-control bg-matte-blue text-white text-[1rem] font-bold leading-[1] cursor-pointer [transition:background_0.15s_ease,border-color_0.15s_ease,transform_0.05s_ease] hover:bg-matte-blue-hover hover:border-matte-blue-hover"
            aria-label="Close"
            onClick={onClose}
          >
            ✕
          </button>
        </header>

        <div className="overflow-y-auto px-6 pt-5 pb-7 flex-auto md:px-8 md:py-6 max-compact:px-4 max-compact:py-3.5">
          <PrivacyNotice privacy={config?.privacy ?? null} />
        </div>

      </div>
    </dialog>
  );
}
