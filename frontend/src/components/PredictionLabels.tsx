import { useApp } from "../AppContext";
import ScoreBar from "./ScoreBar";
import { disclosure, disclosureSummary, panel } from "../ui";

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
    return <div className={`${panel} mb-4.5 text-ink-muted text-center`}>Results hidden until labels are entered.</div>;
  }

  const positiveSet = new Set(positive);
  const positiveLabels = labels.filter((label) => positiveSet.has(label));
  const negativeLabels = labels.filter((label) => !positiveSet.has(label));

  return (
    <div className="my-4.5">
      <div className="flex items-center gap-2 mb-2.5 print:break-after-avoid">
        <h2 className="m-0 text-[1.05rem] font-bold">Findings flagged</h2>
        <span className="inline-flex items-center justify-center min-w-6 h-6 px-1.75 rounded-full bg-positive-wash text-positive-ink text-[0.78rem] font-bold">{positiveLabels.length}</span>
      </div>
      <p className="-mt-0.75 mx-0 mb-3 text-ink-muted text-[0.78rem]">
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
        <div className={`${panel} mb-4.5 text-ink-muted text-center`}>No findings flagged</div>
      )}

      {isAdmin && negativeLabels.length ? (
        <details className={`${disclosure} print:mt-2 print:pt-2`} data-print-open>
          <summary className={disclosureSummary}>Other model scores ({negativeLabels.length})</summary>
          <div className="mt-3 print:grid print:grid-cols-2 print:gap-x-2 print:mt-1.5">
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
