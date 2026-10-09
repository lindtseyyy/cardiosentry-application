import { formatModelScore } from "../utils/modelScore";

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
    <div className={`score-row ${positive ? "positive" : "negative"}`}>
      <div className="score-result-main">
        <span className="score-name">{displayName || label}</span>
        <span className={`score-state ${positive ? "positive" : "negative"}`}>
          {positive ? "Flagged" : "Not flagged"}
        </span>
      </div>
      <div className="score-metric">
        <span>Model score</span>
        <strong className="score-value" aria-label={`${label} model score ${formattedScore}`}>
          {formattedScore}
        </strong>
      </div>
    </div>
  );
}
