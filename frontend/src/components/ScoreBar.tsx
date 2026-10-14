import { formatModelScore } from "../utils/modelScore";
import { scoreValue } from "../ui";

export interface ScoreBarProps {
  label: string;
  displayName: string;
  score: number;
  positive: boolean;
}

export default function ScoreBar({
  label,
  displayName,
  score,
  positive,
}: ScoreBarProps) {
  const formattedScore = formatModelScore(score);

  return (
    <div className={`flex items-center justify-between gap-4 border rounded-card px-3.5 py-3 mb-2.25 print:px-2.5 print:py-1.5 print:mb-1.25 print:break-inside-avoid max-phone:items-start ${positive ? "bg-panel-2 border-indigo shadow-[inset_3px_0_0_var(--color-indigo)]" : "bg-panel border-line last:mb-0 print:last:mb-1.25"}`}>
      <div className="flex items-center gap-2.25 min-w-0 max-phone:flex-col max-phone:items-start max-phone:gap-1">
        <span className={`font-bold text-[1rem] ${positive ? "" : "print:text-[9pt]"}`}>{displayName || label}</span>
        <span className={`flex-none rounded-full py-0.5 px-1.75 text-[0.68rem] font-bold ${positive ? "text-positive-ink bg-positive-wash" : "text-negative-ink bg-negative-wash print:hidden"}`}>
          {positive ? "Flagged" : "Not flagged"}
        </span>
      </div>
      <div className="flex items-baseline gap-2 flex-none max-phone:flex-col max-phone:items-start max-phone:gap-1">
        <span className={`text-ink-muted text-[0.72rem] ${positive ? "" : "print:hidden"}`}>Model score</span>
        <strong className={`${scoreValue} text-[1.25rem] ${positive ? "" : "print:text-[10pt]"}`} aria-label={`${label} model score ${formattedScore}`}>
          {formattedScore}
        </strong>
      </div>
    </div>
  );
}
