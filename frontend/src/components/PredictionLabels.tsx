import { useApp } from "../AppContext";
import ScoreBar from "./ScoreBar";

export interface PredictionLabelsProps {
  labels: string[];
  displayNames: Record<string, string>;
  scores: Record<string, number>;
  positive: string[];
  blind?: boolean;
  isAdmin?: boolean;
}

export default function PredictionLabels({
  labels,
  displayNames,
  scores,
  positive,
  blind = false,
  isAdmin: isAdminProp,
}: PredictionLabelsProps) {
  const { isAdmin: contextIsAdmin } = useApp();
  const isAdmin = isAdminProp ?? contextIsAdmin;
  if (blind) {
    return <div className="panel muted center">Results hidden until labels are entered.</div>;
  }

  const positiveSet = new Set(positive);
  const positiveLabels = labels.filter((label) => positiveSet.has(label));
  const negativeLabels = labels.filter((label) => !positiveSet.has(label));

  return (
    <div className="prediction-labels">
      <div className="label-section-head">
        <h2>Findings flagged</h2>
        <span className="count-badge">{positiveLabels.length}</span>
      </div>
      <p className="score-note">
        Percentages are model scores, not clinical confidence or disease probability.
      </p>

      {positiveLabels.length ? (
        positiveLabels.map((label) => (
          <ScoreBar
            key={label}
            label={label}
            displayName={displayNames[label] ?? label}
            score={scores[label]}
            positive
          />
        ))
      ) : (
        <div className="panel muted center">No findings flagged</div>
      )}

      {isAdmin && negativeLabels.length ? (
        <details className="negative-labels" data-print-open>
          <summary>Other model scores ({negativeLabels.length})</summary>
          <div className="negative-list">
            {negativeLabels.map((label) => (
              <ScoreBar
                key={label}
                label={label}
                displayName={displayNames[label] ?? label}
                score={scores[label]}
                positive={false}
              />
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}
