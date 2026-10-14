import { useEffect, useState } from "react";

export interface Stage {
  key: string;
  label: string;
  url: string | null;
}

export interface StageStripProps {
  stages: Stage[];
  active?: string;
}

export default function StageStrip({ stages, active }: StageStripProps) {
  const [open, setOpen] = useState<Stage | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const present = stages.filter((s) => s.url);

  return (
    <>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(96px,1fr))] gap-2.5">
        {present.map((s) => (
          <div
            key={s.key}
            className={`relative border-2 rounded-control overflow-hidden bg-black cursor-pointer aspect-square ${active === s.key ? "border-accent ring-2 ring-accent/25" : "border-line"}`}
            role="button"
            tabIndex={0}
            onClick={() => setOpen(s)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setOpen(s);
              }
            }}
          >
            <img className="size-full object-cover block" src={s.url!} alt={s.label} loading="lazy" />
            <span className="absolute inset-x-0 bottom-0 text-[0.68rem] px-1.5 py-0.75 bg-[rgba(5,10,22,0.78)] text-white text-center">{s.label}</span>
          </div>
        ))}
      </div>

      {open && (
        <div className="fixed inset-0 bg-[rgba(3,7,18,0.92)] flex items-center justify-center z-1000 p-5" onClick={() => setOpen(null)}>
          <button
            className="absolute top-4 right-4 min-h-11 min-w-11 rounded-[50%] bg-panel-3 text-[1.3rem] leading-[1]"
            aria-label="Close"
            onClick={(e) => {
              e.stopPropagation();
              setOpen(null);
            }}
          >
            ×
          </button>
          <img
            className="max-w-full max-h-[92vh] object-contain rounded-control"
            src={open.url!}
            alt={open.label}
            onClick={(e) => e.stopPropagation()}
          />
          <span className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-[rgba(5,10,22,0.85)] text-white px-3.5 py-1.5 rounded-full text-[0.85rem]">{open.label}</span>
        </div>
      )}
    </>
  );
}
