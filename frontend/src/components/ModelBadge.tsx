import type { ModelInputSize } from "../api/types";

/** "768\u00d71024", or "768px" when the model input is square. */
export function formatInputSize(size?: ModelInputSize | null): string | null {
  if (!Array.isArray(size) || size.length !== 2) return null;
  const [h, w] = size;
  return h === w ? `${h}px` : `${h}\u00d7${w}`;
}

export interface ModelBadgeProps {
  id?: string;
  displayName: string;
  version?: string;
  checkpointShort?: string;
  inputSize?: ModelInputSize | null;
  device?: string;
}

export default function ModelBadge({
  id,
  displayName,
  version,
  checkpointShort,
  inputSize,
  device,
}: ModelBadgeProps) {
  return (
    <div className="flex flex-wrap gap-x-3.5 gap-y-2 items-center bg-panel-2 border border-line rounded-card px-4 py-3">
      <span className="font-bold">{displayName}</span>
      {version ? <span className="text-ink-muted text-[0.85rem]">v{version}</span> : null}
      {id ? <span className="tabular-nums text-[0.82rem] text-accent">{id}</span> : null}
      {checkpointShort ? (
        <span className="tabular-nums text-[0.82rem] text-accent">sha&nbsp;{checkpointShort}</span>
      ) : null}
      {formatInputSize(inputSize) ? (
        <span className="text-ink-muted text-[0.85rem]">input&nbsp;{formatInputSize(inputSize)}</span>
      ) : null}
      {device ? <span className="text-ink-muted text-[0.85rem]">{device}</span> : null}
    </div>
  );
}
