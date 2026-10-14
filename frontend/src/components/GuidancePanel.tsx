import { useEffect, useRef, useState } from "react";
import { api, friendlyMessage, isApiError } from "../api/client";
import type {
  AgeGroup,
  GuidanceResponse,
  GuidanceRiskFactor,
  GuidanceSymptom,
  UrgencyLevel,
} from "../api/types";
import { btn, loadingBlock, msg } from "../ui";

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
  { value: "fainting_exertion_or_supine", label: "Fainting during exertion or while lying down" },
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
  "fainting_exertion_or_supine",
  "stroke_signs",
];

const RISK_FACTORS: Array<{ value: GuidanceRiskFactor; label: string }> = [
  { value: "heart_failure", label: "Diagnosed heart failure" },
  { value: "hypertension", label: "High blood pressure" },
  { value: "diabetes", label: "Diabetes" },
  { value: "prior_stroke_tia", label: "Prior stroke, TIA, or blood clot" },
  { value: "vascular_disease", label: "Known vascular disease or prior heart attack" },
  { value: "known_heart_disease", label: "Other known structural heart disease" },
  { value: "known_af_flutter", label: "Known atrial fibrillation or flutter (already diagnosed)" },
  { value: "known_lbbb", label: "Known left bundle branch block (seen on an earlier ECG)" },
  { value: "pacemaker_icd", label: "Pacemaker or ICD" },
];

const TIER_NAMES: Record<UrgencyLevel, string> = {
  green: "Green",
  yellow: "Yellow",
  orange: "Orange",
  red: "Red",
};

const TIER_STYLES: Record<UrgencyLevel, { panel: string; text: string; dot: string; chip: string }> = {
  green: {
    panel: "border-l-tier-green [background-image:linear-gradient(100deg,var(--color-tier-green-wash),transparent_55%)]",
    text: "text-tier-green-text",
    dot: "bg-tier-green ring-tier-green/18",
    chip: "bg-tier-green-wash text-tier-green-text inset-ring-tier-green/55",
  },
  yellow: {
    panel: "border-l-tier-yellow [background-image:linear-gradient(100deg,var(--color-tier-yellow-wash),transparent_55%)]",
    text: "text-tier-yellow-text",
    dot: "bg-tier-yellow ring-tier-yellow/18",
    chip: "bg-tier-yellow-wash text-tier-yellow-text inset-ring-tier-yellow/55",
  },
  orange: {
    panel: "border-l-tier-orange [background-image:linear-gradient(100deg,var(--color-tier-orange-wash),transparent_55%)]",
    text: "text-tier-orange-text",
    dot: "bg-tier-orange ring-tier-orange/18",
    chip: "bg-tier-orange-wash text-tier-orange-text inset-ring-tier-orange/55",
  },
  red: {
    panel: "border-l-tier-red [background-image:linear-gradient(100deg,var(--color-tier-red-wash),transparent_55%)]",
    text: "text-tier-red-text",
    dot: "bg-tier-red ring-tier-red/18",
    chip: "bg-tier-red-wash text-tier-red-text inset-ring-tier-red/55",
  },
};

const SECTION_LABEL = "m-0 mb-1.25 text-ink-muted text-[0.7rem] font-[750] tracking-[0.09em] uppercase";
const CONTEXT_CHIP = "inline-flex items-center gap-1.75 min-h-9.5 border rounded-full px-3 py-1.75 text-[0.8rem] text-left";
const CONTEXT_CHIP_STYLES = {
  unselected: "border-line bg-panel-2 text-ink-muted hover:border-line-strong hover:bg-panel-3 hover:text-ink",
  selected: "border-accent-strong bg-accent/9 text-ink",
  criticalSelected: "border-emergency bg-emergency/8 text-ink",
} as const;

function TierChip({ tier }: { tier: UrgencyLevel }) {
  return (
    <span className={`inline-block rounded-full px-1.75 py-0 text-[0.66rem] font-[750] tracking-[0.03em] uppercase align-[1px] inset-ring ${TIER_STYLES[tier].chip}`}>
      {TIER_NAMES[tier]}
    </span>
  );
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
  const [priorityAnswered, setPriorityAnswered] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setPriorityAnswered(false);
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
  async function handlePriorityYes() {
    if (!guidance || !guidance.priority_question) return;
    setLoading(true);
    setError(null);
    try {
      const newSymptoms = Array.from(new Set([...guidance.context.symptoms, guidance.priority_question.symptom]));
      setGuidance(
        await api.guidance(captureId, {
          run_id: runId,
          age_group: guidance.context.age_group,
          symptoms: newSymptoms,
          risk_factors: guidance.context.risk_factors,
          context_complete: guidance.context.complete,
        })
      );
    } catch (e) {
      setError(isApiError(e) ? friendlyMessage(e.code, e.message) : String(e));
    } finally {
      setLoading(false);
    }
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
    <section className="grid gap-3 my-5" aria-label="Urgency and recommendations">
      <div className="flex items-center gap-1.75 text-ink-muted text-[0.78rem] print:hidden">
        <span className="text-accent" aria-hidden="true">ⓘ</span>
        <span>Screening support only — not a diagnosis or a substitute for medical care.</span>
      </div>

      {loading && !guidance ? <div className={loadingBlock}>Assessing guidance…</div> : null}
      {error ? <div className={msg.warn}>{error}</div> : null}

      {guidance && context ? (
        <>
          {guidance.cautions && guidance.cautions.length > 0 ? (
            <section className="bg-tier-yellow-wash border border-tier-yellow text-tier-yellow-text rounded-card px-4.5 py-3 print:break-inside-avoid" aria-label="Important Cautions" role="alert">
              {guidance.cautions.map((caution) => (
                <p className="m-0 leading-[1.4] not-first:mt-2" key={caution}>
                  <strong>Caution:</strong> {caution}
                </p>
              ))}
            </section>
          ) : null}

          {guidance.priority_question && !priorityAnswered ? (
            <section
              className="bg-tier-red-wash border-2 border-emergency text-tier-red-text rounded-card px-4.5 py-4 print:break-inside-avoid"
              role="alert"
              aria-labelledby={`priority-question-${runId}`}
            >
              <h2 className="m-0 text-[1.16rem] font-bold text-emergency" id={`priority-question-${runId}`}>
                {guidance.priority_question.question}
              </h2>
              <p className="m-0 mt-2 text-ink text-[0.9rem] leading-[1.45]">
                {guidance.priority_question.reason}
              </p>
              <div className="flex gap-2.5 mt-4 print:hidden">
                <button
                  type="button"
                  className={`${btn.primary} bg-emergency border-emergency text-white hover:bg-emergency-text`}
                  onClick={handlePriorityYes}
                  disabled={loading}
                >
                  Yes
                </button>
                <button
                  type="button"
                  className={`${btn.ghost} border-emergency text-emergency hover:bg-tier-red-wash`}
                  onClick={() => setPriorityAnswered(true)}
                  disabled={loading}
                >
                  No
                </button>
              </div>
            </section>
          ) : null}

          <div className={guidance.priority_question && !priorityAnswered ? "hidden print:contents" : "contents"}>
            <section
              className={`bg-panel border border-line-strong border-l-[6px] rounded-card px-4.5 py-4.25 max-compact:p-3.75 print:break-inside-avoid ${TIER_STYLES[guidance.urgency_level].panel}`}
              aria-labelledby={`urgency-${runId}`}
              role="status"
            >
              <p className={`m-0 mb-1.5 text-[0.7rem] font-[750] tracking-[0.09em] uppercase ${TIER_STYLES[guidance.urgency_level].text}`}>
                Urgency · {TIER_NAMES[guidance.urgency_level]}
              </p>
              <div className="flex items-center gap-2.25">
                <span className={`size-2.5 flex-none rounded-full ring-4 ${TIER_STYLES[guidance.urgency_level].dot}`} aria-hidden="true" />
                <h2 className={`m-0 text-[1.16rem] font-bold ${TIER_STYLES[guidance.urgency_level].text}`} id={`urgency-${runId}`}>{guidance.urgency_action}</h2>
              </div>
              {guidance.reasons.map((reason) => (
                <p className="m-0 mt-2.25 text-ink-muted text-[0.8rem]" key={reason}>
                  {reason}
                </p>
              ))}
            </section>


          <section className="bg-panel border border-line-strong border-l-[6px] border-l-context rounded-card px-4 py-3 [background-image:linear-gradient(100deg,var(--color-context-wash),transparent_60%)] print:break-inside-avoid" aria-label="Patient context">
            <div className="flex items-center justify-between gap-3.5">
              <span className="grid gap-0.25">
                <strong className="text-context-text">Patient context</strong>
                <small className="text-ink-muted text-[0.78rem]">
                  {context.complete
                    ? appliedAnswers.length
                      ? "Applied to this guidance · not saved"
                      : "No symptoms or history reported"
                    : "Not answered — symptoms and history can raise the urgency"}
                </small>
              </span>
              <button
                type="button"
                className={`${btn.small} shrink-0 whitespace-nowrap ${context.complete ? "bg-transparent border-context-line-strong text-context-text" : "bg-context border-context text-white font-semibold hover:bg-context-text"}`}
                onClick={openContext}
              >
                {context.complete ? "Edit" : "Add details"}
              </button>
            </div>
            {appliedAnswers.length ? (
              <ul className="flex flex-wrap gap-1.5 m-0 mt-2.5 p-0 list-none">
                {appliedAnswers.map((answer) => (
                  <li key={answer.key} className={answer.critical ? "border border-critical-line rounded-full px-2.5 py-0.75 bg-tier-red-wash text-tier-red-text text-[0.76rem]" : "border border-context-line rounded-full px-2.5 py-0.75 bg-context-wash text-context-text text-[0.76rem]"}>
                    {answer.text}
                  </li>
                ))}
              </ul>
            ) : null}
          </section>

          <dialog
            ref={dialogRef}
            className="m-auto w-[min(560px,calc(100vw-32px))] max-h-[calc(100dvh-32px)] p-0 border border-line-strong rounded-card bg-panel text-ink shadow-dialog backdrop:bg-ink/45"
            aria-labelledby={`context-title-${runId}`}
            onClick={(e) => {
              // A click on the backdrop lands on the <dialog> itself.
              if (e.target === e.currentTarget) e.currentTarget.close();
            }}
          >
            <form
              method="dialog"
              className="flex flex-col max-h-[calc(100dvh-34px)]"
              onSubmit={(e) => {
                e.preventDefault();
                void reassess();
              }}
            >
              <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
                <h2 className="m-0 text-[1.05rem] font-bold" id={`context-title-${runId}`}>Refine for the patient</h2>
                <button
                  type="button"
                  className={`${btn.ghost} ${btn.small}`}
                  aria-label="Close"
                  onClick={() => dialogRef.current?.close()}
                >
                  ✕
                </button>
              </header>

              <div className="grid gap-4.25 overflow-y-auto p-4">
                <div className="min-w-0">
                  <label className="block mb-1.75 text-ink-muted text-[0.8rem] font-[650]" htmlFor={`guidance-age-${runId}`}>Age group</label>
                  <select
                    id={`guidance-age-${runId}`}
                    className="w-[min(100%,220px)] text-[0.85rem]"
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

                <fieldset className="min-w-0 m-0 p-0 border-0">
                  <legend className="block mb-1.75 px-0.5 text-ink-muted text-[0.8rem] font-[650]">Symptoms now or recently</legend>
                  <div className="flex flex-wrap gap-2">
                    {SYMPTOMS.map((item) => {
                      const selected = symptoms.includes(item.value);
                      const critical = CRITICAL_SYMPTOMS.includes(item.value);
                      return (
                        <button
                          type="button"
                          key={item.value}
                          className={`${CONTEXT_CHIP} ${selected ? (critical ? CONTEXT_CHIP_STYLES.criticalSelected : CONTEXT_CHIP_STYLES.selected) : CONTEXT_CHIP_STYLES.unselected}`}
                          aria-pressed={selected}
                          onClick={() =>
                            setSymptoms(updateSelection(symptoms, item.value, !selected))
                          }
                        >
                          <span className={`font-extrabold ${critical && selected ? "text-emergency" : "text-accent"}`} aria-hidden="true">{selected ? "✓" : "+"}</span>
                          {item.label}
                        </button>
                      );
                    })}
                  </div>
                </fieldset>

                <fieldset className="min-w-0 m-0 p-0 border-0">
                  <legend className="block mb-1.75 px-0.5 text-ink-muted text-[0.8rem] font-[650]">Relevant history</legend>
                  <div className="flex flex-wrap gap-2">
                    {RISK_FACTORS.map((item) => {
                      const selected = riskFactors.includes(item.value);
                      return (
                        <button
                          type="button"
                          key={item.value}
                          className={`${CONTEXT_CHIP} ${selected ? CONTEXT_CHIP_STYLES.selected : CONTEXT_CHIP_STYLES.unselected}`}
                          aria-pressed={selected}
                          onClick={() =>
                            setRiskFactors(
                              updateSelection(riskFactors, item.value, !selected)
                            )
                          }
                        >
                          <span className="text-accent font-extrabold" aria-hidden="true">{selected ? "✓" : "+"}</span>
                          {item.label}
                        </button>
                      );
                    })}
                  </div>
                </fieldset>
                {error ? <div className={msg.warn}>{error}</div> : null}
              </div>

              <footer className="flex items-center justify-between gap-3 border-t border-line px-4 py-3 max-compact:items-stretch max-compact:flex-col-reverse">
                <span className="text-ink-faint text-[0.75rem]">Used for this guidance only · not saved</span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className={`${btn.ghost} min-h-10 px-4 py-0 text-[0.85rem] max-compact:flex-1`}
                    onClick={() => dialogRef.current?.close()}
                  >
                    Cancel
                  </button>
                  <button type="submit" className={`${btn.primary} min-h-10 px-4 py-0 text-[0.85rem] max-compact:flex-1`} disabled={loading}>
                    {loading ? "Updating…" : "Update guidance"}
                  </button>
                </div>
              </footer>
            </form>
          </dialog>

          <section
            className="bg-panel border border-line-strong rounded-card p-4.5 max-compact:p-3.75"
            aria-labelledby={`recommendations-${runId}`}
          >
            <p className={SECTION_LABEL}>What to do</p>
            <h2 className="m-0 text-[1.16rem] font-bold print:break-after-avoid" id={`recommendations-${runId}`}>Recommended next steps</h2>
            <ol className="grid gap-0 m-0 mt-3.25 pl-7 list-decimal">
              {combinedActions.map((action) => (
                <li className="pt-1.75 pb-2.25 pl-1 text-[0.86rem] leading-[1.45] border-b border-line last:border-b-0 print:break-inside-avoid" key={action.text}>
                  <span>{action.text}</span>
                  {action.finding ? (
                    <small className="block mt-0.75 text-ink-faint text-[0.72rem]">
                      <TierChip tier={action.finding.tier} /> {action.finding.name}
                    </small>
                  ) : null}
                </li>
              ))}
            </ol>

            {guidance.combination_notes && guidance.combination_notes.length > 0 ? (
              <div className="mt-4.5 px-4.5 py-3.5 bg-panel-2 border border-line rounded-card print:break-inside-avoid">
                <p className={SECTION_LABEL}>Notes for the clinician reading this ECG</p>
                {guidance.combination_notes.map((note) => (
                  <p key={note} className="m-0 mb-2.5 last:mb-0 border-l-2 border-indigo pl-2.25 leading-[1.4] text-ink">
                    {note}
                  </p>
                ))}
              </div>
            ) : null}

            <details className="mt-2 border-t border-line pt-2.75" data-print-open>
              <summary className="cursor-pointer text-ink-muted text-[0.8rem] font-[650]">Why these steps</summary>
              <div className="pt-1.5">
                {guidance.finding_guidance.map((finding) => (
                  <p className="my-1.25 text-ink-muted text-[0.84rem] print:break-inside-avoid" key={finding.finding}>
                    <TierChip tier={finding.tier} />{" "}
                    <strong className="text-ink">{finding.display_name}:</strong> {finding.summary}
                  </p>
                ))}
              </div>
            </details>

              <div className="mt-4 print:break-inside-avoid">
                <p className={SECTION_LABEL}>What this model cannot detect</p>
                <p className="m-0 text-ink-muted text-[0.84rem]">
                  {guidance.scope_note}
                </p>
              </div>

            {guidance.urgency_level !== "red" ? (
              <div className="grid gap-0.5 mt-3.5 border-l-3 border-emergency py-2 pl-2.75 text-ink-muted text-[0.82rem] print:break-inside-avoid">
                <strong className="text-emergency">Get emergency help if symptoms worsen.</strong>
                <span>{guidance.safety_net}</span>
              </div>
            ) : null}
          </section>
          </div>
        </>
      ) : null}
    </section>
  );
}
