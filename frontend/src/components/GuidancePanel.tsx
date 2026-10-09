import { useEffect, useRef, useState } from "react";
import { api, friendlyMessage, isApiError } from "../api/client";
import type {
  AgeGroup,
  GuidanceResponse,
  GuidanceRiskFactor,
  GuidanceSymptom,
  UrgencyLevel,
} from "../api/types";

export interface GuidancePanelProps {
  captureId: string;
  runId: string;
}

const AGE_GROUPS: Array<{ value: AgeGroup; label: string }> = [
  { value: "unknown", label: "Unknown / prefer not to say" },
  { value: "under_18", label: "Under 18" },
  { value: "18_64", label: "18–64" },
  { value: "65_74", label: "65–74" },
  { value: "75_plus", label: "75 or older" },
];

const SYMPTOMS: Array<{ value: GuidanceSymptom; label: string }> = [
  { value: "chest_pain", label: "Chest pain, pressure, or tightness" },
  {
    value: "severe_shortness_of_breath",
    label: "New, severe, or worsening shortness of breath",
  },
  { value: "fainting", label: "Fainting or nearly fainting" },
  { value: "palpitations", label: "Palpitations or a racing/irregular heartbeat" },
  { value: "dizziness", label: "Dizziness or lightheadedness" },
  {
    value: "stroke_signs",
    label: "Sudden face droop, arm weakness/numbness, or speech trouble",
  },
];

const CRITICAL_SYMPTOMS: GuidanceSymptom[] = [
  "chest_pain",
  "severe_shortness_of_breath",
  "fainting",
  "stroke_signs",
];

const RISK_FACTORS: Array<{ value: GuidanceRiskFactor; label: string }> = [
  { value: "heart_failure", label: "Diagnosed heart failure" },
  { value: "hypertension", label: "High blood pressure" },
  { value: "diabetes", label: "Diabetes" },
  { value: "prior_stroke_tia", label: "Prior stroke, TIA, or blood clot" },
  { value: "vascular_disease", label: "Known vascular disease or prior heart attack" },
  { value: "known_heart_disease", label: "Other known structural heart disease" },
];

const TIER_NAMES: Record<UrgencyLevel, string> = {
  green: "Green",
  yellow: "Yellow",
  orange: "Orange",
  red: "Red",
};

function TierChip({ tier }: { tier: UrgencyLevel }) {
  return <span className={`tier-chip ${tier}`}>{TIER_NAMES[tier]}</span>;
}

function labelOf<T extends string>(items: Array<{ value: T; label: string }>, value: T) {
  return items.find((item) => item.value === value)?.label ?? value;
}

function updateSelection<T extends string>(
  current: T[],
  value: T,
  checked: boolean
): T[] {
  return checked ? Array.from(new Set([...current, value])) : current.filter((x) => x !== value);
}

export default function GuidancePanel({ captureId, runId }: GuidancePanelProps) {
  const [guidance, setGuidance] = useState<GuidanceResponse | null>(null);
  // Draft answers inside the modal; the applied answers live in guidance.context.
  const [ageGroup, setAgeGroup] = useState<AgeGroup>("unknown");
  const [symptoms, setSymptoms] = useState<GuidanceSymptom[]>([]);
  const [riskFactors, setRiskFactors] = useState<GuidanceRiskFactor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .guidance(captureId, { run_id: runId, context_complete: false })
      .then((result) => {
        if (!cancelled) setGuidance(result);
      })
      .catch((e) => {
        if (!cancelled)
          setError(isApiError(e) ? friendlyMessage(e.code, e.message) : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [captureId, runId]);

  function openContext() {
    // Start every edit from what is currently applied, so Cancel discards.
    if (guidance) {
      setAgeGroup(guidance.context.age_group);
      setSymptoms(guidance.context.symptoms);
      setRiskFactors(guidance.context.risk_factors);
    }
    dialogRef.current?.showModal();
  }

  async function reassess() {
    setLoading(true);
    setError(null);
    try {
      setGuidance(
        await api.guidance(captureId, {
          run_id: runId,
          age_group: ageGroup,
          symptoms,
          risk_factors: riskFactors,
          context_complete: true,
        })
      );
      dialogRef.current?.close();
    } catch (e) {
      setError(isApiError(e) ? friendlyMessage(e.code, e.message) : String(e));
    } finally {
      setLoading(false);
    }
  }

  const combinedActions = guidance
    ? [
        ...guidance.recommended_next_steps.map((text) => ({ text, finding: null })),
        ...guidance.finding_guidance.flatMap((finding) =>
          finding.next_steps.map((text) => ({
            text,
            finding: { name: finding.display_name, tier: finding.tier },
          }))
        ),
      ].filter(
        (action, index, all) =>
          all.findIndex((candidate) => candidate.text === action.text) === index
      )
    : [];

  const context = guidance?.context;
  const appliedAnswers = context
    ? [
        ...(context.age_group !== "unknown"
          ? [{ key: "age", text: `Age ${labelOf(AGE_GROUPS, context.age_group)}`, critical: false }]
          : []),
        ...context.symptoms.map((s) => ({
          key: s,
          text: labelOf(SYMPTOMS, s),
          critical: CRITICAL_SYMPTOMS.includes(s),
        })),
        ...context.risk_factors.map((r) => ({
          key: r,
          text: labelOf(RISK_FACTORS, r),
          critical: false,
        })),
      ]
    : [];

  return (
    <section className="guidance-shell" aria-label="Urgency and recommendations">
      <div className="guidance-mini-notice">
        <span aria-hidden="true">ⓘ</span>
        <span>Screening support only — not a diagnosis or a substitute for medical care.</span>
      </div>

      {loading && !guidance ? <div className="loading-block">Assessing guidance…</div> : null}
      {error ? <div className="msg warn">{error}</div> : null}

      {guidance && context ? (
        <>
          <section
            className={`urgency-panel ${guidance.urgency_level}`}
            aria-labelledby={`urgency-${runId}`}
            role="status"
          >
            <p className="urgency-eyebrow">
              Urgency · {TIER_NAMES[guidance.urgency_level]}
            </p>
            <div className="urgency-title-row">
              <span className="urgency-dot" aria-hidden="true" />
              <h2 id={`urgency-${runId}`}>{guidance.urgency_action}</h2>
            </div>
            {guidance.reasons.map((reason) => (
              <p className="urgency-reason" key={reason}>
                {reason}
              </p>
            ))}
          </section>

          {guidance.cautions && guidance.cautions.length > 0 ? (
            <section className="guidance-cautions" aria-label="Important Cautions" role="alert">
              {guidance.cautions.map((caution) => (
                <p key={caution}>
                  <strong>Caution:</strong> {caution}
                </p>
              ))}
            </section>
          ) : null}

          <section className="context-summary" aria-label="Patient context">
            <div className="context-summary-head">
              <span>
                <strong>Patient context</strong>
                <small>
                  {context.complete
                    ? appliedAnswers.length
                      ? "Applied to this guidance · not saved"
                      : "No symptoms or history reported"
                    : "Not answered — symptoms and history can raise the urgency"}
                </small>
              </span>
              <button
                type="button"
                className={context.complete ? "ghost small" : "primary small"}
                onClick={openContext}
              >
                {context.complete ? "Edit" : "Add details"}
              </button>
            </div>
            {appliedAnswers.length ? (
              <ul className="context-applied">
                {appliedAnswers.map((answer) => (
                  <li key={answer.key} className={answer.critical ? "critical" : ""}>
                    {answer.text}
                  </li>
                ))}
              </ul>
            ) : null}
          </section>

          <dialog
            ref={dialogRef}
            className="context-dialog"
            aria-labelledby={`context-title-${runId}`}
            onClick={(e) => {
              // A click on the backdrop lands on the <dialog> itself.
              if (e.target === e.currentTarget) e.currentTarget.close();
            }}
          >
            <form
              method="dialog"
              onSubmit={(e) => {
                e.preventDefault();
                void reassess();
              }}
            >
              <header className="context-dialog-head">
                <h2 id={`context-title-${runId}`}>Refine for the patient</h2>
                <button
                  type="button"
                  className="ghost small"
                  aria-label="Close"
                  onClick={() => dialogRef.current?.close()}
                >
                  ✕
                </button>
              </header>

              <div className="context-dialog-body">
                <div className="refiner-field">
                  <label htmlFor={`guidance-age-${runId}`}>Age group</label>
                  <select
                    id={`guidance-age-${runId}`}
                    value={ageGroup}
                    onChange={(e) => setAgeGroup(e.target.value as AgeGroup)}
                  >
                    {AGE_GROUPS.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </div>

                <fieldset className="refiner-field">
                  <legend>Symptoms now or recently</legend>
                  <div className="context-chips">
                    {SYMPTOMS.map((item) => {
                      const selected = symptoms.includes(item.value);
                      const critical = CRITICAL_SYMPTOMS.includes(item.value);
                      return (
                        <button
                          type="button"
                          key={item.value}
                          className={`context-chip ${selected ? "selected" : ""} ${
                            critical ? "critical" : ""
                          }`}
                          aria-pressed={selected}
                          onClick={() =>
                            setSymptoms(updateSelection(symptoms, item.value, !selected))
                          }
                        >
                          <span aria-hidden="true">{selected ? "✓" : "+"}</span>
                          {item.label}
                        </button>
                      );
                    })}
                  </div>
                </fieldset>

                <fieldset className="refiner-field">
                  <legend>Relevant history</legend>
                  <div className="context-chips">
                    {RISK_FACTORS.map((item) => {
                      const selected = riskFactors.includes(item.value);
                      return (
                        <button
                          type="button"
                          key={item.value}
                          className={`context-chip ${selected ? "selected" : ""}`}
                          aria-pressed={selected}
                          onClick={() =>
                            setRiskFactors(
                              updateSelection(riskFactors, item.value, !selected)
                            )
                          }
                        >
                          <span aria-hidden="true">{selected ? "✓" : "+"}</span>
                          {item.label}
                        </button>
                      );
                    })}
                  </div>
                </fieldset>
                {error ? <div className="msg warn">{error}</div> : null}
              </div>

              <footer className="context-dialog-foot">
                <span>Used for this guidance only · not saved</span>
                <div>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => dialogRef.current?.close()}
                  >
                    Cancel
                  </button>
                  <button type="submit" className="primary" disabled={loading}>
                    {loading ? "Updating…" : "Update guidance"}
                  </button>
                </div>
              </footer>
            </form>
          </dialog>

          <section
            className="recommendation-panel"
            aria-labelledby={`recommendations-${runId}`}
          >
            <p className="guidance-section-label">What to do</p>
            <h2 id={`recommendations-${runId}`}>Recommended next steps</h2>
            <ol className="recommendation-list">
              {combinedActions.map((action) => (
                <li key={action.text}>
                  <span>{action.text}</span>
                  {action.finding ? (
                    <small>
                      <TierChip tier={action.finding.tier} /> {action.finding.name}
                    </small>
                  ) : null}
                </li>
              ))}
            </ol>

            {guidance.combination_notes && guidance.combination_notes.length > 0 ? (
              <div className="clinician-notes-block">
                <p className="guidance-section-label">Notes for the clinician reading this ECG</p>
                {guidance.combination_notes.map((note) => (
                  <p key={note} className="combination-note">
                    {note}
                  </p>
                ))}
              </div>
            ) : null}

            <details className="recommendation-rationale" data-print-open>
              <summary>Why these steps</summary>
              <div>
                {guidance.finding_guidance.map((finding) => (
                  <p key={finding.finding}>
                    <TierChip tier={finding.tier} />{" "}
                    <strong>{finding.display_name}:</strong> {finding.summary}
                  </p>
                ))}
              </div>
            </details>

            {guidance.urgency_level !== "red" ? (
              <div className="guidance-safety-net">
                <strong>Get emergency help if symptoms worsen.</strong>
                <span>{guidance.safety_net}</span>
              </div>
            ) : null}
          </section>
        </>
      ) : null}
    </section>
  );
}
