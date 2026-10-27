# Urgency and Recommended Next Steps — clinical rule basis

Rule version: `four-tier-2026-10-10`

This document is the evidence and safety specification for
`backend/services/guidance.py`. It is a screening and decision-support layer,
not a diagnostic or treatment protocol. The output must always state that the
image classifier is experimental, has not been clinically validated or
calibrated on real phone photographs, and cannot replace a clinician-read ECG
or professional medical evaluation.

The response and print footer carry this disclaimer:

> Screening and decision support only. This experimental image-model output is not a diagnosis, does not measure clinical severity, and does not replace a clinician-interpreted ECG or professional medical evaluation. The urgency reflects only the model's flags and the context reported here; it does not reflect heart rate, blood pressure, or the patient's current condition, which the model cannot see.

## The four tiers

| Tier | Action shown | Meaning |
|---|---|---|
| **Green — no action from this result** | No extra action needed | The model read this ECG as Normal and nothing reported raises the tier. Keep usual care; a normal ECG does not rule out heart disease. |
| **Yellow — routine review** | Book a routine clinician review | Not an emergency on the information given. Have a clinician confirm and interpret the ECG at a routine appointment within the next few weeks. |
| **Orange — same-day assessment** | Get a medical assessment today | Needs a clinician to confirm the ECG and assess the patient the same day. If the usual clinician cannot see them today, use an urgent-care centre or emergency department. |
| **Red — emergency now** | Call emergency services now | Possible time-critical heart emergency. Call 911 now; do not wait for symptoms to settle. |

The final tier is the **highest** tier produced by any of: a flagged
condition's effective baseline tier, a reported symptom, reported heart history,
a listed combination, or the under-18 or pacemaker/ICD Yellow floor.
Only a reported known AF/flutter or known LBBB sets that condition's baseline
to Yellow, and the SB+1AVB pair is exempt from the two-or-more rule; nothing
lowers a tier after it is raised.
Model scores are never used as a severity measure; crossing a threshold only
selects which conditions enter the rules.

Green is reserved for a positive Normal read: `NORM` flagged, no abnormal
condition flagged, and no reported context or caution that raises the tier. It
rests on the USPSTF finding that in asymptomatic low-risk adults an ECG is
very unlikely to change management, so a normal tracing needs no follow-up of
its own. Green is still not medical clearance: the step list keeps "do not use
the Normal flag to dismiss symptoms", and the symptom rules lift it like any
other tier. When **nothing** crosses its threshold (not even Normal) the model
has given no reading, so the result is Yellow and a clinician should read the
ECG. An import-time assertion stops any abnormal label from being given Green.

"Same day" for Orange is an operational choice, not a guideline time window.
It reflects that every Orange condition needs a clinician to read the tracing
before the patient's risk is known (for example, whether 2nd-degree block is
Mobitz I or II, whether ST elevation is new, or what the corrected QT is).

### Tier-level next steps

**Red** begins with these steps, before condition-specific recommendations:

1. Call 911 now — the Philippine emergency hotline. Do not wait to see whether symptoms settle.
2. Do not drive yourself. Stay with someone if possible and follow the dispatcher's instructions.
3. If the person collapses and is not breathing normally, start CPR and use an AED if one is available.
4. Show the ECG to the emergency team; do not delay to retake the photo or re-run the model.

**Orange** begins:

1. Get a medical assessment today: contact the clinician who requested the ECG, or go to an urgent-care centre or emergency department if they cannot see the patient today.
2. Bring the original ECG and a list of all medicines and supplements, and ask for the reading to be confirmed by a clinician.
3. If chest pain, severe breathlessness, fainting, or stroke signs appear, this becomes Red — call emergency services.

**Yellow** normally starts: "Book a routine appointment within the next few weeks
with the clinician who requested the ECG, or a primary-care clinician, to
confirm and interpret the result." For a Normal read with palpitations or
dizziness that remains Yellow, this is replaced by: "See the clinician who
requested the ECG, or a primary-care clinician, within a few days because of
the palpitations or dizziness, and ask whether heart-rhythm monitoring (for
example a Holter monitor) is needed." The "within a few days" step takes
precedence over the general Yellow description.

**Green** starts: "No extra appointment is needed for this result alone. Keep
any follow-up already planned and share the ECG with the clinician who
requested it." Green and Yellow also say: "Do not start, stop, or change
medicine based on this screening output." When context is incomplete, both
add: "Add the patient's symptoms and history under Patient context — they
can raise the tier."

## Scope and release gate

Rules are locked per model to the exact served-label order and suppression
policy (`RULE_SETS`). The endpoint reads positives from the stored prediction,
re-filters them through the stored descriptor snapshot, and refuses any other
model or any policy drift. A new model needs a new review and a rule-set entry.

| Model | Served labels | Suppressed |
|---|---|---|
| `convnext_tiny_rfpn_clean12_aug` (active) | `NORM, SB, STACH, LBBB, LQT, AF, AFL, 3AVB, 2AVB, 1AVB, STEMI, STE` | none |
| `convnext_tiny_rfpn_clean12` | `NORM, SB, STACH, LBBB, LQT, AF, AFL, 3AVB, 2AVB, 1AVB, STEMI, STE` | none |
| `convnext_v1_base_rfpn_clean12` | `NORM, SB, STACH, LBBB, LQT, AF, AFL, 3AVB, 2AVB, 1AVB, STEMI, STE` | none |
| `convnext_v1_base_clean12` | `NORM, SB, STACH, LBBB, LQT, AF, AFL, 3AVB, 2AVB, 1AVB, STEMI, STE` | none |
| `convnextv2_tiny_v1img_v1` (earlier runs) | `NORM, AF, IAVB, LBBB, RBBB, PAC, PVC, LAFB, LAE` | `TInv, LQT, PRWP` |

The review covered the clean12 rules as written for `convnext_v1_base_clean12`.
`convnext_v1_base_rfpn_clean12` (ConvNeXt-V1 Base + Residual FPN, same clean12
corpus, labels and order) reuses that rule set unchanged, by the developer's
decision of 2026-10-09; the rules are per condition, so its tiers match the
reviewed ones exactly. The checkpoint itself was not separately reviewed.
`convnext_tiny_rfpn_clean12` (ConvNeXt-V1 Tiny + Residual FPN, same clean12
corpus, labels and order) reuses the same rule set unchanged on the same
basis (2026-10-15); its checkpoint was not separately reviewed either.
`convnext_tiny_rfpn_clean12_aug` (the same Tiny + RFPN recipe trained on the
clean and the augmented sheet of every clean12 record; same labels and order)
reuses it on the same basis (2026-10-27); its checkpoint was not separately
reviewed either.

A label shared by both model families (`AF`, `LBBB`, `NORM`; `IAVB` = `1AVB`) uses
one rule, so the same condition always gets the same tier.

## What the model cannot detect

Every response includes the same `scope_note`, rendered after "Why these steps"
under **"What this model cannot detect"**, including for Red results and in print:

> This model reports only the specific conditions it was trained to recognise. It cannot detect any other heart-rhythm or ECG problem, so a condition that does not appear in this result has not been ruled out.

The note is deliberately general and names no example conditions, so it never
implies a complete list of what the model misses. Other guidance text that
mentions conditions outside the label set (as possible causes or mimics) is not
a claim that the model can label them.

## Priority question

When `STE` is flagged, the backend returns `priority_question` if all of these
hold: context is incomplete, `chest_pain` has not been reported, and the final
tier is not Red. It selects the first flagged rule with an `ask_first` question
in the model's served-label order. The question and reason are:

> Does the patient have chest pain, pressure, or tightness now or recently?

> The model flagged ST elevation. With chest pain this is an emergency (Red), so answer this before reading the result.

On screen, a prominent critical question card appears before the result.
Until answered, the urgency panel, Patient context card, and recommendations
are hidden; cautions remain visible. **Yes** requests guidance again with
`chest_pain` added to the currently applied symptoms, preserving the other
answers and `context_complete`; this produces Red and clears the question.
**No** reveals the existing result without changing the request or its tier.
The No answer is local UI state, not saved, and is lost on reload; that state
also resets when the capture or run changes.

The gate applies to `LBBB + STE` too. It is absent when context is complete,
chest pain is already reported, or another rule has made the result Red
(for example `STE + STEMI` or `STE + 3AVB`). The earlier model has no served
`STE` label and therefore no such question. The frontend uses only
`priority_question`, not hard-coded knowledge of STE.

In print, an unanswered question and its reason remain visible together with
the urgency panel, context and recommendations; only the buttons are hidden.
This is a screen gate, not a change to the backend tier or the printable result.

## Per-condition rules (clean12)

| Condition | Baseline | Symptom that makes it Red (besides the global rules) | Condition-specific next steps | Basis |
|---|---|---|---|---|
| `NORM` Normal (alone) | **Green** | — | No extra appointment for this result; keep planned follow-up. Not clearance; do not dismiss new or worsening symptoms. | USPSTF 2018 ECG screening (D for low-risk asymptomatic adults); AHA heart-attack warning signs; CDC stroke signs |
| nothing flagged | Yellow | — | The model gave no reading; have a clinician read the ECG. If it was taken for a symptom or concern, share the original tracing with the clinician who requested it. If the photo is blurred, cropped, or missing leads, retake it before relying on the result (not added when the final tier is Red). | AHA heart-attack warning signs; CDC stroke signs |
| `SB` Sinus bradycardia | Yellow | — | Review rate-slowing medicines (beta-blockers incl. eye drops, CCBs, antiarrhythmics, lithium) and fitness. Ask whether a thyroid or electrolyte blood test, or an assessment for sleep apnoea, is appropriate if no obvious cause is found. | 2018 ACC/AHA/HRS bradycardia guideline (no pacing for asymptomatic physiological SB; no routine imaging; Table 4 drugs); AHA bradycardia; Cleveland Clinic |
| `STACH` Sinus tachycardia | Yellow | — | Look for the cause (fever, infection, dehydration, anaemia, thyroid, stimulants, medicines, a blood clot in the lungs, or heart failure), especially if persistent at rest. For the clinician: a rate near 150 beats/min read as sinus tachycardia should be checked for atrial flutter with 2:1 conduction. | Cleveland Clinic sinus tachycardia; Merck atrial flutter |
| `1AVB` First-degree AV block | Yellow | — | Review AV-nodal-slowing medicines. | Merck AV block ("rarely symptomatic, usually no treatment"); 2018 guideline (no routine imaging) |
| `LBBB` Left bundle branch block | **Orange**; Yellow if reported as already known | — | Ask whether this LBBB is new by comparing with previous ECGs. A new LBBB needs prompt evaluation, including an echocardiogram (2018 conduction guideline, Class I). | 2018 guideline (Top-10 #3, imaging rec. 1); Merck bundle branch block |
| `AF` Atrial fibrillation | **Orange**; Yellow if AF/flutter reported as already diagnosed | — | Ask whether new; check heart rate, causes (thyroid disease, high blood pressure, sleep apnoea, obesity, alcohol), and formal stroke risk. Do not start, stop, or change aspirin, a blood thinner, or heart-rhythm medicine based on this screening result. Aspirin is no longer recommended for stroke prevention in AF; ask the clinician which option is right. | 2023 ACC/AHA/ACCP/HRS AF guideline; 2024 ESC AF guideline; AHA AF symptoms; Merck AF |
| `AFL` Atrial flutter | **Orange**; Yellow if AF/flutter reported as already diagnosed | — | Ask about heart-rate control and a formal stroke-risk assessment, and whether cardioversion or catheter ablation is appropriate. Do not start, stop, or change a blood thinner or heart-rhythm medicine based on this screening result. | Merck atrial flutter (2:1 → ~150/min; anticoagulation same as AF; AF coexists); 2023 AF guideline; 2024 ESC AF guideline |
| `LQT` Long QT | **Orange** | palpitations, dizziness | Ask a clinician today to measure the corrected QT interval by hand — the model does not measure it, and the measurement is unreliable in atrial fibrillation, atrial flutter, or bundle branch block — and to check potassium, magnesium, and calcium. Bring a full medicine/supplement list (QT-prolonging drugs); ask the prescriber today rather than self-stopping. Clinicians can check each medicine against the CredibleMeds QTdrugs list. Report family history of sudden death or fainting. | Merck torsades/long QT (drugs, ↓K, ↓Mg, ↓Ca, bradycardia; risk rises with QTc > 500 ms; syncope and palpitations); AHA conduction disorders/LQTS |
| `2AVB` Second-degree AV block | **Orange** | dizziness, fainting; also Red with `LBBB` (C1), `LQT` (C2), `SB` (C6), or `3AVB` (K3) | The type of block cannot be determined from this result, and some types need urgent pacemaker evaluation. Ask a clinician today to determine the type (Mobitz I, Mobitz II, 2:1, or high-grade) from the full tracing. Review medicines that slow AV conduction; for Mobitz type II or high-grade block, an echocardiogram is recommended (2018 conduction guideline, Class I). | Merck AV block (Mobitz I often benign; Mobitz II progresses suddenly → pacemaker); 2018 guideline (Top-10 #5) |
| `STE` ST elevation | **Orange** | palpitations, dizziness; chest pain is Red globally; `STEMI` is a separate Red class | Have a clinician read this ECG today, ideally against a previous ECG, and ask specifically whether the ST elevation is new. If chest discomfort, breathlessness, cold sweat, nausea, or lightheadedness occurs, call emergency services — do not wait for the appointment. Chest pain is asked first when context is incomplete (see Priority question). | Moak et al. 2024 (60–80%, citing Brady 2001); app text simplified per 2026-10-08 review; 2025 ACS guideline; AHA warning signs |
| `3AVB` Complete heart block | **Red** | — | Tell the emergency team the ECG may show complete heart block and give the medicine list (beta-blockers, non-dihydropyridine calcium-channel blockers, digoxin). The team will also check reversible causes: high potassium (hyperkalaemia), an acute inferior heart attack, or Lyme disease where it occurs. An echocardiogram is recommended for complete heart block (2018 conduction guideline, Class I). | Merck AV block (escape rhythm unreliable; syncope, sudden death); 2018 guideline (pacing regardless of symptoms; Class I echocardiogram) |
| `STEMI` ST-elevation MI | **Red** | — | Call even without pain: the ambulance team can record a new ECG and alert a heart-attack centre; rest; aspirin only if the dispatcher/clinician says so. | 2025 ACC/AHA/ACEP/NAEMSP/SCAI ACS guideline (FMC-to-device ≤ 90 min); 2023 ESC ACS guideline (transfer target ≤ 120 min); AHA warning signs |

STE stays Orange at baseline. Its rule summary is: "ST elevation can be an acute heart attack, but many other conditions cause it — normal early repolarization, pericarditis, left ventricular hypertrophy, LBBB, an old infarct or left ventricular aneurysm, or Brugada pattern. Among chest-pain patients with ST elevation, most do not turn out to have a STEMI, so a clinician must read the tracing." Dizziness or palpitations trigger the condition-specific Red rule: "ST elevation with lightheadedness or palpitations must be treated as a possible heart attack until a clinician excludes it." Chest pain, severe breathlessness, stroke signs, and fainting with an abnormal flag are Red through the global rules. `STEMI` is its own Red class, not the baseline tier of `STE`.

LBBB's Orange rationale is: "The app usually cannot tell whether this LBBB is new, and a new LBBB needs prompt evaluation, including an echocardiogram."

Reporting known LBBB changes only its effective baseline to Yellow: "The LBBB
was reported as already known from an earlier ECG, so routine review is enough
unless symptoms, history, or other findings raise the tier." Known AF/flutter
does the same for AF and AFL: "Atrial fibrillation or flutter was reported as
already known, so routine review is enough unless symptoms, history, or other
findings raise the tier." The app cannot verify rate control or stroke
prevention. `AF + AFL` still gets the Orange multiplicity floor even when both
are known; this is deliberate over-triage.

SB's summary includes an underactive thyroid or sleep apnoea as possible
causes. STACH's summary adds: "At rest, important causes to rule out include a
blood clot in the lungs (pulmonary embolism), infection or sepsis, and heart
failure. Treatment targets the cause."

LQT's summary includes "low potassium, magnesium, or calcium, or a slow heart
rate" and states: "This model flags a long-QT pattern; it does not measure the
QT interval." Its medication step ends: "Clinicians can check each medicine
against the CredibleMeds QTdrugs list."

The complete-heart-block summary includes: "An echocardiogram is recommended
(2018 conduction guideline, Class I)." The STEMI summary states: "This pattern
suggests an ST-elevation heart attack — a coronary artery may be blocked.
Reopening it is time-critical: guidelines target 90 minutes or less from first
medical contact to treatment at a PCI-capable hospital, or 120 minutes or less
when transfer to one is needed."

The second-degree block summary states the one-label limitation: "In second-degree AV block some atrial beats do not reach the ventricles. Mobitz type I (Wenckebach) is often benign, especially in young or athletic people; Mobitz type II and high-grade block can progress suddenly to complete heart block, and a pacemaker is recommended regardless of symptoms. This model uses one label for every type of second-degree block (Mobitz I, Mobitz II, 2:1, high-grade), so it cannot tell them apart." Its symptom-specific Red reason is: "Second-degree AV block with dizziness or fainting is a symptomatic slow rhythm and can progress to complete heart block."

## Global symptom and history rules (all models)

| Rule | Tier |
|---|---|
| Chest pain/pressure, new severe or worsening breathlessness, or sudden stroke signs — whatever the model flagged | **Red** |
| Fainting or near-fainting with any abnormal flag | **Red** |
| Fainting with known heart failure or structural heart disease, even with Normal or nothing flagged | **Red** — Fainting with known heart failure or structural heart disease needs emergency assessment, even with a normal ECG. |
| Fainting together with palpitations, whatever the model flagged | **Red** — Fainting together with palpitations suggests a heart-rhythm cause and needs emergency assessment. |
| Fainting during exertion or while lying down, whatever the model flagged | **Red** — Fainting during exertion or while lying down is a high-risk feature that needs emergency assessment. |
| Palpitations or dizziness with any abnormal flag | at least **Orange** — An abnormal ECG flag plus palpitations or dizziness needs same-day assessment. Condition-specific Red rules still apply. |
| Fainting or near-fainting with no abnormal flag and no Red trigger above | **Orange** — Fainting or near-fainting needs same-day assessment even without an abnormal flag. |
| Normal alone with palpitations or dizziness, and no higher-tier rule | **Yellow**, review **within a few days** — Palpitations or dizziness with a Normal ECG read need a clinician review within a few days, including whether heart-rhythm monitoring is needed. |
| Nothing flagged with palpitations or dizziness | at least **Orange** — Palpitations or dizziness need same-day assessment because the model gave no reading of this ECG. |
| Heart failure or known heart disease with any abnormal flag | at least **Orange** |
| Heart failure or known heart disease with a Normal read | at least **Yellow** (usual follow-up continues) |
| Two or more abnormal flags, except exactly `SB + 1AVB` | at least **Orange** |
| Exactly `SB + 1AVB` (a concurrent `NORM` flag does not change the pair) | **Yellow** on its own; symptoms, heart history, another abnormal finding, or a higher-tier rule can raise it |
| Known AF/flutter (`known_af_flutter`) with an AF or AFL flag | sets that condition's **baseline to Yellow** only; symptoms, history, multiplicity and combinations still raise it |
| Known LBBB (`known_lbbb`) with an LBBB flag | sets that condition's **baseline to Yellow** only; symptoms, history, multiplicity and combinations still raise it |
| Pacemaker or ICD (`pacemaker_icd`) | at least **Yellow**, plus a paced-rhythm caution; does not change condition-specific tiers or count as heart history or an AF stroke-risk factor |
| AF or AFL with age ≥ 65 or a CHA₂DS₂-VA (2024 ESC) risk factor (HF, hypertension, diabetes, prior stroke/TIA, vascular disease), unless under 18 | adds an explicit formal stroke-risk-assessment step (no tier change); the 2023 ACC/AHA guideline uses CHA₂DS₂-VASc |
| Age group Under 18 | at least **Yellow**, plus a caution — A pediatric ECG needs a clinician's interpretation; the adult rules used here do not apply to children. |

Sources: AHA heart-attack warning signs; CDC stroke signs; 2017
ACC/AHA/HRS syncope guideline (ECG abnormalities, heart failure/structural
heart disease, and arrhythmic syncope are high-risk features); AHA bradycardia
("call 911 for chest pain, breathing difficulty, or fainting"); 2024 ESC and
2023 ACC/AHA AF guidelines for stroke-risk factors. The app never computes a
risk score or recommends anticoagulation. Under option 6.5(b), a Normal read
with palpitations/dizziness remains Yellow even with heart-failure history;
fainting with heart-failure or structural-disease history gives Red.

## Combinations

| Rule | Flagged together | Tier | Note and any additional next step |
|---|---|---|---|
| C1 | `LBBB + 2AVB` | **Red** | Second-degree AV block together with LBBB suggests disease below the AV node, which can progress suddenly to complete heart block. |
| C2 | `LQT + 2AVB` or `LQT + 3AVB` | **Red** | Long QT with AV block: pauses and slow ventricular rates are a recognised trigger for torsades de pointes. Condition-specific steps are listed only for the findings actually flagged. |
| C3 | `LQT + SB` | Orange | Long QT with a slow heart rate: bradycardia raises the risk of torsades de pointes, so medicines and electrolytes should be reviewed the same day. |
| C4 | `LBBB + 1AVB` | Orange | First-degree AV block together with LBBB suggests disease in more than one part of the conduction system. **Additional step:** If an echocardiogram has not been done, ask for one: it is recommended for newly identified LBBB (2018 conduction guideline, Class I). |
| C5 | `LBBB + STE` | Orange | LBBB itself shifts the ST segment, so ST elevation with LBBB cannot be read with the usual criteria; a clinician should apply the Sgarbossa or modified Sgarbossa (Smith) criteria and compare the tracing with earlier ECGs. Any chest pain makes this an emergency. |
| C6 | `2AVB + SB` | **Red** | Second-degree AV block with sinus bradycardia: a slow ventricular rate suggests a higher-grade block, which can progress suddenly to complete heart block. |
| C7 | `SB + 1AVB` | **Yellow** | Sinus bradycardia with first-degree AV block is a common, usually benign pairing (fitness, sleep, vagal tone, or medicines that slow the AV node), so on its own it stays Yellow; symptoms or heart history raise it. **Additional step:** Ask the clinician to review AV-nodal-blocking medicines — beta-blockers, non-dihydropyridine calcium-channel blockers (verapamil, diltiazem), and digoxin — which can cause both a slow heart rate and a long PR interval. |
| C8 | `LBBB + AF` or `LBBB + AFL` | Orange | Atrial fibrillation or flutter with LBBB produces a wide-complex rhythm that, when fast, can be hard to tell apart from a ventricular rhythm. **Additional step:** A fast, wide-complex rhythm needs prompt clinician review: make sure a clinician reads this tracing today. |
| Rhythm conflict | `SB + STACH` | Orange (two-or-more rule); note | The model flagged rhythms that cannot both be the underlying rhythm of one tracing (SB, STACH). A clinician must read the rhythm. Guidance includes the steps for both findings and applies the higher urgency. |
| Rhythm conflict | `STACH + AF` | Orange (two-or-more rule); note | The model flagged rhythms that cannot both be the underlying rhythm of one tracing (AF, STACH). A clinician must read the rhythm. Guidance includes the steps for both findings and applies the higher urgency. |
| Rhythm conflict | `STACH + AFL` | Orange (two-or-more rule); note | The model flagged rhythms that cannot both be the underlying rhythm of one tracing (AFL, STACH). A clinician must read the rhythm. Guidance includes the steps for both findings and applies the higher urgency. Atrial flutter with 2:1 conduction is often misread as sinus tachycardia. |
| K5 — sinus-node note | `SB + AF` or `SB + AFL` | Orange | Sinus bradycardia flagged together with atrial fibrillation or flutter can occur in sinus node disease (tachy-brady syndrome). A clinician needs to review the rhythm. |
| Normal/abnormal conflict | `NORM` + any abnormal | note only | This multi-label model flagged Normal and an abnormal condition at the same time. The abnormal condition and symptoms determine the guidance; Normal does not cancel them. |
| Legacy | `RBBB + LAFB` | Orange | RBBB plus LAFB can represent a bifascicular conduction pattern. It needs same-day clinician review; fainting makes it an emergency. |
| Legacy | `IAVB` + `LBBB`/`RBBB`/`LAFB` | Orange | First-degree AV block together with a bundle or fascicular block is more extensive conduction disease than either flag alone. |
| Legacy | `AF + LAE` | Orange | AF and LAE should be assessed together because atrial size and the underlying structural condition can affect AF risk assessment. |

The engine does not claim that model labels prove a combined diagnosis; notes
use "suggests" / "can represent" and always defer to a clinician-read ECG.

The rhythm-conflict notes do not independently raise urgency; the existing
two-or-more-abnormal-flags rule supplies an Orange floor. `SB + AF`/`AFL`
gets the sinus-node note (K5), not the "cannot both be" rhythm-conflict note.
`AF + AFL` is not treated as a rhythm conflict. C4, C7, C8 and K4 add their
steps to `recommended_next_steps` after the tier steps and any AF/AFL
stroke-risk step. Notes and steps are deduplicated. The whole-tracing
"several conditions" note also remains for the benign SB+1AVB pair.

### Labels that cannot be read reliably together

| Rule | Flagged together | Tier | Note |
|---|---|---|---|
| K1 | `AF` + `1AVB`, `2AVB`, or legacy `IAVB` | Orange | The PR interval cannot be measured in atrial fibrillation, so an AV-block flag cannot be read reliably together with AF. A clinician needs to read the tracing. |
| K2 | `AFL` + `1AVB` or `2AVB` | Orange | In atrial flutter the PR interval cannot be measured reliably, so an AV-block flag cannot be read reliably together with flutter; 2:1 or 4:1 conduction is normal flutter physiology, not true second-degree AV block. A clinician needs to read the tracing. |
| K3 | `3AVB` + `1AVB` or `2AVB` | **Red** | Complete (third-degree) AV block and first- or second-degree AV block are mutually exclusive labels. Guidance uses the higher one, complete heart block (Red). |
| K4 | `AF + 3AVB` | **Red** | In atrial fibrillation, a slow, regular ventricular rhythm can mean complete heart block. Digoxin toxicity is one possible cause, so the full medication list is important. **Additional step:** Tell the emergency team whether the patient takes digoxin. |

Basis: Merck AV block, AF, and atrial flutter; K5 also uses the 2018
ACC/AHA/HRS conduction guideline. Labels are not suppressed by these notes.

### Long QT measurement caveats

| Rule | Flagged together | Tier | Note |
|---|---|---|---|
| Q1 | `LQT + LBBB` | Orange | LBBB widens the QRS, which lengthens the QT, so the corrected QT is overestimated. A clinician should measure the QT manually. |
| Q2 | `LQT + STACH` | Orange | At high heart rates the usual (Bazett) correction overcorrects the QT. A clinician should recheck the corrected QT. |
| Q3 | `LQT + AF` or `LQT + AFL` | Orange | The QT interval is unreliable in atrial fibrillation or flutter. A clinician should measure the QT manually, averaging it over several beats. |

Basis: the AHA/ACCF/HRS 2009 ECG standardization Part IV statement and Merck
torsades/long QT. These are Orange caveats, not reasons to lower urgency.
`STEMI` or `3AVB` with any other finding stays **Red**; no combination,
label-conflict note, or QT caveat lowers a tier.

## Per-condition rules (earlier model `convnextv2_tiny_v1img_v1`)

`RBBB`, `PAC`, `PVC`, `LAFB`, `LAE` are Yellow; their text and sources are
unchanged (Merck bundle/fascicular block, 2018 conduction guideline, AHA
premature contractions, Cleveland Clinic LAE). `AF`, `LBBB`, `IAVB`, `NORM`
share the clean12 rules above, including **LBBB at Orange** unless reported as
already known, and the known-AF Yellow baseline. The pacemaker caution, Yellow
floor and scope note also apply. `AF + IAVB` gets the Orange PR-interval
conflict note (K1), and `AF + LBBB` gets the Orange wide-complex note and
prompt-review step (C8). Suppressed `LQT` never enters the earlier model's
rules, so Q1–Q3 do not apply to it.

## Context questions

The UI asks, and does not persist:

- **Age group:** under 18, 18–64, 65–74, 75 or older, unknown.
- **Symptoms:** chest pain/pressure/tightness; new severe or worsening
  breathlessness; fainting/near-fainting; **"Fainting during exertion or while
  lying down"** (`fainting_exertion_or_supine`); palpitations; dizziness; sudden
  stroke signs. The exertional/supine option is styled critical.
- **History:** heart failure, hypertension, diabetes, prior stroke/TIA or
  clot, vascular disease/prior MI, other known structural heart disease;
  **"Known atrial fibrillation or flutter (already diagnosed)"**
  (`known_af_flutter`); **"Known left bundle branch block (seen on an earlier
  ECG)"** (`known_lbbb`); **"Pacemaker or ICD"** (`pacemaker_icd`).

Until answered, the result is marked provisional: "This is provisional.
Answer the context questions below because symptoms, age, and heart history
can raise the tier." Answered context says: "Guidance has been updated using
the reported age group, symptoms, and risk factors."

Selecting Under 18 adds this caution verbatim and prevents a Green result:

> This tool was not validated in children. Normal heart-rate and ECG values are different in children: the adult cut-offs of 60 and 100 beats/min for sinus bradycardia and tachycardia and adult QT limits do not apply, and normal pediatric ECG features can be mislabelled by an adult-trained model. Have a pediatric clinician read the ECG; do not use this result for triage.

Selecting Pacemaker or ICD also prevents a Green result and adds:

> A pacemaker or ICD changes the ECG: a paced rhythm often looks like left bundle branch block, and this model was not trained to recognise paced rhythms. Have a clinician read the ECG; do not rely on this result's condition labels.

Its Yellow-floor reason is: "A pacemaker or ICD changes the ECG, so a clinician
needs to read it; a Normal flag does not replace that." If both cautions
apply, the pediatric caution comes first. Neither floor overrides higher
urgency: Red symptoms still produce Red, and both cautions remain. With an
unknown age there is no pediatric caution until the age group is entered.

All context answers are used for this guidance only and are not saved. They
travel in `GuidanceRequest` and are echoed in response `context`, but the
endpoint persists nothing. The priority-question No answer is local UI state.
Neither the new options nor the gate require a privacy-notice version change.

## Response and visible clinician notes

`GuidanceResponse.cautions: list[str]` carries whole-result warnings and is
`[]` when there are none. Pediatric and pacemaker cautions are shown prominently
before the urgency panel or priority question, outside collapsed details,
and are printable.

`combination_notes: list[str]` includes combinations, label-conflict notes,
QT caveats, rhythm-conflict notes, and the sinus-node note. All notes are
visible after Recommended next steps under **"Notes for the clinician reading
this ECG"**; "Why these steps" retains the finding summaries only.
`finding_guidance[].tier` is each condition's effective baseline (including
the known-AF/flutter or known-LBBB Yellow path), not the final urgency.
Condition-specific steps are included only for detected labels, or `NONE`
when nothing was detected.

`priority_question` is either `null` or an object with `symptom`, `question`
and `reason`; the screen and print behaviour is described above.
`scope_note: str` carries the same model-limit statement for every rule set
and every tier, including Red; it remains printable.

`reasons` contains only reasons at the final tier. Lower-tier notes remain in
`combination_notes` and stay visible even when a Red rule removes them from
`reasons`. The API's Normal-read headlines are:

| Result | `headline` |
|---|---|
| Green | The model read this ECG as normal. No extra action needed from this result. |
| Yellow with palpitations/dizziness requiring prompt review | The model read this ECG as normal — see a clinician within a few days about the symptoms. |
| Other Yellow Normal read, including pediatric, pacemaker or heart-history floor | The model read this ECG as normal — book a routine review to have the ECG read. |

The other headlines remain "Emergency: call emergency services now.",
"Urgent: this result needs a medical assessment today.", "Not an emergency
on the information given — book a routine review." (Yellow with abnormal
findings), and "No condition flagged — book a routine review to have the ECG
read." The panel does not render `headline`; it renders `urgency_action`
and `reasons`.

The response's safety net, shown for non-Red results, is:

> Symptoms override this screening result. For chest pain or pressure, severe or worsening trouble breathing, stroke signs, fainting, or palpitations followed by fainting, call 911. If someone collapses and is not breathing normally, start CPR and use an AED if one is available.

## Second cardiology review (2026-10-08) disposition

The review source is
`file-ouputs/latest_to_implement/CardioSentry-Urgency-and-Recommendation-Layer-Revised-Cardiology-Review.docx`.
The adviser read the first Revised document, before the v2 decisions. This
table records the application/doc disposition, not approval of the defaults
that remain listed in `OPEN_QUESTIONS_cardiologist_feedback.md`.

| Review item | Disposition in `four-tier-2026-10-10` |
|---|---|
| Must-fix 1: syncope with HF/structural disease | Red even when Normal or nothing is flagged; fainting with palpitations and exertional/supine fainting are also Red. Isolated fainting without a Red trigger stays Orange. |
| Must-fix 2: complete-block echo | 3AVB now includes Class I echocardiography and reversible causes (hyperkalaemia, acute inferior MI, Lyme disease where relevant). |
| Must-fix 3: C2 finding steps | Existing engine behaviour retained and documented: only the actually flagged AV-block finding contributes its condition-specific steps. |
| Must-fix 4: rhythm conflict | Both findings' steps are retained and the higher urgency applies; STACH+AFL also explains 2:1-conduction misreading. AF+AFL is not a rhythm conflict. |
| Must-fix 5: pediatric handling | Existing Yellow floor retained; warning now explicitly says not validated in children, names 60/100 beats/min adult cut-offs, and directs a pediatric clinician review rather than triage. |
| Sections 1–2: tier and action wording | Highest-tier rule retained with explicit baseline/exemption wording; Yellow routine = next few weeks; requested-clinician wording, CPR/AED, context prompt and model/context-only disclaimer included. |
| Section 3: finding refinements | Sleep apnoea, serious resting-tachycardia causes, flutter 2:1 check, calcium/manual QT/CredibleMeds, obesity/AF aspirin caution, AFL wording, STEMI transfer target, STE mimics and simplified prevalence wording, and non-Red no-reading retake step included. |
| Sections 4–5: combinations | C4 conduction wording and echo step; C5 Sgarbossa/modified Smith criteria; C7 Yellow benign-pair exception; Q3 extended to AF or AFL; K4 digoxin step. Existing C1–C3/C6/C8 and K/Q caveats retained. |
| Section 6: context defaults | 6.5(b): Normal+palpitations/dizziness Yellow within days, no reading Orange. Known AF/flutter and known LBBB set only that baseline to Yellow; pacemaker/ICD adds caution and a Yellow floor. ESC 2024 CHA₂DS₂-VA and ACC/AHA CHA₂DS₂-VASc distinction documented. |
| Section 7: presentation and limits | Normal-read headlines rewritten; safety net includes CPR/AED and palpitations followed by fainting; priority chest-pain question gates screen urgency but not print; scope note is visible for every tier. Context answers remain unsaved. |
| Review/v2 mismatch and deliverables | Unknown/new LBBB remains Orange; known LBBB offers the Yellow path. STE remains Orange before symptom escalation. The optional defaults need reviewer confirmation; they are asked in Part B of `file-ouputs/CardioSentry_Urgency_and_Recommendation_Layer_Revised_v3.docx`/`.pdf` (Revision 3, 2026-10-11), which also corrected the clinical wording of the C7/3AVB calcium-channel-blocker lists, the AFL rate reason, the K2 flutter note and the scope note. Per-label sensitivity/specificity belongs in the thesis results chapter, not the app. |

## Source register (checked 2026-10-08)

- [2025 ACC/AHA/ACEP/NAEMSP/SCAI Guideline for the Management of Patients With Acute Coronary Syndromes (Circulation)](https://www.ahajournals.org/doi/10.1161/CIR.0000000000001309)
- [2018 ACC/AHA/HRS Bradycardia and Cardiac Conduction Delay — Guidelines Made Simple](https://www.acc.org/-/media/Non-Clinical/Files-PDFs-Excel-MS-Word-etc/Guidelines/2018/Guidelines_Made_Simple_2018_Bradycardia.pdf)
- [2023 ACC/AHA/ACCP/HRS AF guideline — key perspectives](https://www.acc.org/latest-in-cardiology/ten-points-to-remember/2023/11/27/19/46/2023-acc-guideline-for-af-gl-af)
- `esc_af_2024`: [2024 ESC Guidelines for the management of atrial fibrillation developed in collaboration with the European Association for Cardio-Thoracic Surgery (EACTS)](https://academic.oup.com/eurheartj/article/45/36/3314/7738779) — European Society of Cardiology (European Heart Journal).
- `esc_acs_2023`: [2023 ESC Guidelines for the management of acute coronary syndromes](https://academic.oup.com/eurheartj/article/44/38/3720/7243210) — European Society of Cardiology (European Heart Journal).
- [2017 ACC/AHA/HRS Syncope guideline](https://www.acc.org/Guidelines/Guidelines/2017/03/09/08/27/Syncope)
- [Merck Manual Professional: Atrioventricular Block](https://www.merckmanuals.com/professional/cardiovascular-disorders/arrhythmias-and-conduction-disorders/atrioventricular-block)
- [Merck Manual Professional: Atrial Flutter](https://www.merckmanuals.com/professional/cardiovascular-disorders/arrhythmias-and-conduction-disorders/atrial-flutter)
- [Merck Manual Professional: Atrial Fibrillation](https://www.merckmanuals.com/professional/cardiovascular-disorders/arrhythmias-and-conduction-disorders/atrial-fibrillation)
- [Merck Manual Professional: Torsades de Pointes Ventricular Tachycardia (long QT)](https://www.merckmanuals.com/professional/cardiovascular-disorders/arrhythmias-and-conduction-disorders/long-qt-syndrome-and-torsades-de-pointes-ventricular-tachycardia)
- [AHA/ACCF/HRS Recommendations for the Standardization and Interpretation of the Electrocardiogram: Part IV: The ST Segment, T and U Waves, and the QT Interval (2009)](https://www.jacc.org/doi/10.1016/j.jacc.2008.12.014)
- [Merck Manual Professional: Bundle Branch Block and Fascicular Block](https://www.merckmanuals.com/professional/cardiovascular-disorders/arrhythmias-and-conduction-disorders/bundle-branch-block-and-fascicular-block)
- [Moak, Muck, Brady. STEMI mimics. Turk J Emerg Med 2024 (PMC11573177)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11573177/)
- [AHA: Warning Signs of a Heart Attack](https://www.heart.org/en/health-topics/heart-attack/warning-signs-of-a-heart-attack)
- [AHA: Bradycardia — Slow Heart Rate](https://www.heart.org/en/health-topics/arrhythmia/about-arrhythmia/bradycardia--slow-heart-rate)
- [AHA: Heart Conduction Disorders (Long QT Syndrome)](https://www.heart.org/en/health-topics/arrhythmia/about-arrhythmia/conduction-disorders)
- [AHA: What are the Symptoms of Atrial Fibrillation?](https://www.heart.org/en/health-topics/atrial-fibrillation/what-are-the-symptoms-of-atrial-fibrillation)
- [AHA: Premature Contractions — PACs and PVCs](https://www.heart.org/en/health-topics/arrhythmia/about-arrhythmia/premature-contractions-pacs-and-pvcs)
- [Cleveland Clinic: Sinus Bradycardia](https://my.clevelandclinic.org/health/diseases/22473-sinus-bradycardia)
- [Cleveland Clinic: Sinus Tachycardia](https://my.clevelandclinic.org/health/diseases/23210-sinus-tachycardia)
- [Cleveland Clinic: Left Atrial Enlargement](https://my.clevelandclinic.org/health/diseases/23967-left-atrial-enlargement)
- [USPSTF 2018: Cardiovascular Disease Risk — Screening With Electrocardiography](https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/cardiovascular-disease-risk-screening-with-electrocardiography)
- [CDC: Signs and Symptoms of Stroke](https://www.cdc.gov/stroke/signs-symptoms/index.html)
- [Philippine Executive Order No. 56, s. 2018 — institutionalizing the Emergency 911 Hotline as the nationwide emergency answering point](https://ldr.senate.gov.ph/executive-issuance/executive-order-no-56-s-2018)

heart.org, ahajournals.org, and cdc.gov return 403 to scripted fetches; those
pages were confirmed through search results rather than a direct fetch. The
JACC QT statement and Senate EO 56 pages also returned 403 on 2026-10-08;
their publication/order details were confirmed through search results.

The ESC 2024 AF and ESC 2023 ACS sources were added for the second-review
implementation on 2026-10-10. Direct Oxford Academic fetches returned 403;
the guideline identities were confirmed through the ESC
[AF guideline page](https://www.escardio.org/guidelines/clinical-practice-guidelines/all-esc-practice-guidelines/atrial-fibrillation/)
and [ACS guideline page](https://www.escardio.org/guidelines/clinical-practice-guidelines/all-esc-practice-guidelines/acute-coronary-syndromes-acs-guidelines)
search results.
