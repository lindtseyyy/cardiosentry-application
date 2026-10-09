# Urgency and Recommended Next Steps — clinical rule basis

Rule version: `four-tier-2026-10-08`

This document is the evidence and safety specification for
`backend/services/guidance.py`. It is a screening and decision-support layer,
not a diagnostic or treatment protocol. The output must always state that the
image classifier is experimental, has not been clinically validated or
calibrated on real phone photographs, and cannot replace a clinician-read ECG
or professional medical evaluation.

## The four tiers

| Tier | Action shown | Meaning |
|---|---|---|
| **Green — no action from this result** | No extra action needed | The model read this ECG as Normal and nothing reported raises the tier. Keep usual care; a normal ECG does not rule out heart disease. |
| **Yellow — routine review** | Book a routine clinician review | Not an emergency on the information given. Have a clinician confirm and interpret the ECG at a routine appointment. |
| **Orange — same-day assessment** | Get a medical assessment today | Needs a clinician to confirm the ECG and assess the patient the same day. If the usual clinician cannot see them today, use an urgent-care centre or emergency department. |
| **Red — emergency now** | Call 911 now — the Philippine emergency hotline. Do not wait to see whether symptoms settle. | Possible time-critical heart emergency. Call 911 now; do not wait for symptoms to settle. |

The final tier is the **highest** tier produced by any of: a flagged
condition's baseline tier, a reported symptom, reported heart history, a
listed combination, or the under-18 Yellow floor. Nothing lowers a tier.
Model scores are never used as a severity measure; crossing a threshold only
selects which conditions enter the rules.

Green is reserved for a positive Normal read: `NORM` flagged, no abnormal
condition flagged, and no symptom or heart history that raises the tier. It
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

## Scope and release gate

Rules are locked per model to the exact served-label order and suppression
policy (`RULE_SETS`). The endpoint reads positives from the stored prediction,
re-filters them through the stored descriptor snapshot, and refuses any other
model or any policy drift. A new model needs a new review and a rule-set entry.

| Model | Served labels | Suppressed |
|---|---|---|
| `convnext_v1_base_clean12` (active) | `NORM, SB, STACH, LBBB, LQT, AF, AFL, 3AVB, 2AVB, 1AVB, STEMI, STE` | none |
| `convnextv2_tiny_v1img_v1` (earlier runs) | `NORM, AF, IAVB, LBBB, RBBB, PAC, PVC, LAFB, LAE` | `TInv, LQT, PRWP` |

A label shared by both models (`AF`, `LBBB`, `NORM`; `IAVB` = `1AVB`) uses
one rule, so the same condition always gets the same tier.

## Per-condition rules (clean12)

| Condition | Baseline | Symptom that makes it Red (besides the global rules) | Condition-specific next steps | Basis |
|---|---|---|---|---|
| `NORM` Normal (alone) | **Green** | — | No extra appointment for this result; keep planned follow-up. Not clearance; do not dismiss new or worsening symptoms. | USPSTF 2018 ECG screening (D for low-risk asymptomatic adults); AHA heart-attack warning signs; CDC stroke signs |
| nothing flagged | Yellow | — | The model gave no reading; have a clinician read the ECG. | AHA heart-attack warning signs; CDC stroke signs |
| `SB` Sinus bradycardia | Yellow | — | Review rate-slowing medicines (beta-blockers incl. eye drops, CCBs, antiarrhythmics, lithium) and fitness; consider thyroid/electrolyte tests. | 2018 ACC/AHA/HRS bradycardia guideline (no pacing for asymptomatic physiological SB; no routine imaging; Table 4 drugs); AHA bradycardia; Cleveland Clinic |
| `STACH` Sinus tachycardia | Yellow | — | Look for the cause (fever, dehydration, anaemia, thyroid, stimulants, medicines), especially if persistent at rest. | Cleveland Clinic sinus tachycardia |
| `1AVB` First-degree AV block | Yellow | — | Review AV-nodal-slowing medicines. | Merck AV block ("rarely symptomatic, usually no treatment"); 2018 guideline (no routine imaging) |
| `LBBB` Left bundle branch block | **Orange** | — | Ask whether this LBBB is new by comparing with previous ECGs. A new LBBB needs prompt evaluation, including an echocardiogram (2018 conduction guideline, Class I). | 2018 guideline (Top-10 #3, imaging rec. 1); Merck bundle branch block |
| `AF` Atrial fibrillation | **Orange** | — | Ask whether new; heart rate, causes, formal stroke-risk assessment; no medicine changes from this output. | 2023 ACC/AHA/ACCP/HRS AF guideline; AHA AF symptoms; Merck AF |
| `AFL` Atrial flutter | **Orange** | — | Rate control, stroke-risk assessment (same as AF), ask about cardioversion/ablation. | Merck atrial flutter (2:1 → ~150/min; anticoagulation same as AF; AF coexists); 2023 AF guideline |
| `LQT` Long QT | **Orange** | palpitations, dizziness | Measured QTc; potassium and magnesium; full medicine list (QT-prolonging drugs) — ask prescriber, do not self-stop; family history of sudden death. | Merck torsades/long QT (drugs, ↓K, ↓Mg, bradycardia; risk rises with QTc > 500 ms; syncope and palpitations); AHA conduction disorders/LQTS |
| `2AVB` Second-degree AV block | **Orange** | dizziness, fainting; also Red with `SB` (C6) or `LBBB` (C1) | The type of block cannot be determined from this result, and some types need urgent pacemaker evaluation. Ask a clinician today to determine the type (Mobitz I, Mobitz II, 2:1, or high-grade) from the full tracing. Review medicines that slow AV conduction; for Mobitz type II or high-grade block, an echocardiogram is recommended (Class I). | Merck AV block (Mobitz I often benign; Mobitz II progresses suddenly → pacemaker); 2018 guideline (Top-10 #5) |
| `STE` ST elevation | **Orange** | palpitations, dizziness; chest pain is Red globally; `STEMI` is a separate Red class | Have a clinician read this ECG today, ideally against a previous ECG, and ask specifically whether the ST elevation is new. If chest discomfort, breathlessness, cold sweat, nausea, or lightheadedness occurs, call emergency services — do not wait for the appointment. | Moak et al. 2024 STEMI mimics (60–80% of chest-pain STE is not STEMI; early repol., pericarditis, LVH, LBBB, aneurysm); 2025 ACS guideline; AHA warning signs |
| `3AVB` Complete heart block | **Red** | — | Tell the team it may be complete heart block; give the medicine list. | Merck AV block (escape rhythm unreliable; syncope, sudden death); 2018 guideline (pacing regardless of symptoms) |
| `STEMI` ST-elevation MI | **Red** | — | Call even without pain; rest; aspirin only if the dispatcher/clinician says so. | 2025 ACC/AHA/ACEP/NAEMSP/SCAI ACS guideline (FMC-to-device ≤ 90 min); AHA warning signs |

STE stays Orange at baseline. Its rule summary is: "ST elevation can be an acute heart attack, but many other conditions cause it — normal early repolarization, pericarditis, left ventricular hypertrophy, LBBB, or an old infarct. Among chest-pain patients with ST elevation, most (about 60–80%) do not turn out to have a STEMI, so a clinician must read the tracing." Dizziness or palpitations trigger the condition-specific Red rule: "ST elevation with lightheadedness or palpitations must be treated as a possible heart attack until a clinician excludes it." Chest pain, severe breathlessness, stroke signs, and fainting with an abnormal flag are Red through the global rules. `STEMI` is its own Red class, not the baseline tier of `STE`.

LBBB's Orange rationale is: "The app usually cannot tell whether this LBBB is new, and a new LBBB needs prompt evaluation, including an echocardiogram."

The second-degree block summary states the one-label limitation: "In second-degree AV block some atrial beats do not reach the ventricles. Mobitz type I (Wenckebach) is often benign, especially in young or athletic people; Mobitz type II and high-grade block can progress suddenly to complete heart block, and a pacemaker is recommended regardless of symptoms. This model uses one label for every type of second-degree block (Mobitz I, Mobitz II, 2:1, high-grade), so it cannot tell them apart." Its symptom-specific Red reason is: "Second-degree AV block with dizziness or fainting is a symptomatic slow rhythm and can progress to complete heart block."

## Global symptom and history rules (all models)

| Rule | Tier |
|---|---|
| Chest pain/pressure, new severe or worsening breathlessness, or sudden stroke signs — whatever the model flagged | **Red** |
| Fainting or near-fainting with any abnormal flag | **Red** |
| Palpitations or dizziness with any abnormal flag | at least **Orange** — An abnormal ECG flag plus palpitations or dizziness needs same-day assessment. |
| Palpitations, dizziness, or fainting with no abnormal flag | **Orange** |
| Heart failure or known heart disease with any abnormal flag | at least **Orange** |
| Heart failure or known heart disease with a Normal read | at least **Yellow** (usual follow-up continues) |
| Two or more abnormal flags | at least **Orange** |
| AF or AFL with age ≥ 65 or a CHA₂DS₂-VASc risk factor (HF, hypertension, diabetes, prior stroke/TIA, vascular disease), unless under 18 | adds an explicit formal stroke-risk-assessment step (no tier change) |
| Age group Under 18 | at least **Yellow**, plus a caution — A pediatric ECG needs a clinician's interpretation; the adult rules used here do not apply to children. |

Sources: AHA heart-attack warning signs; CDC stroke signs; 2017
ACC/AHA/HRS syncope guideline (ECG abnormalities and arrhythmic syncope are
high-risk features); AHA bradycardia ("call 911 for chest pain, breathing
difficulty, or fainting"); 2023 AF guideline for stroke-risk factors. The app
never computes a risk score or recommends anticoagulation.

## Combinations

| Rule | Flagged together | Tier | Note and any additional next step |
|---|---|---|---|
| C1 | `LBBB + 2AVB` | **Red** | Second-degree AV block together with LBBB suggests disease below the AV node, which can progress suddenly to complete heart block. |
| C2 | `LQT + 2AVB` or `LQT + 3AVB` | **Red** | Long QT with AV block: pauses and slow ventricular rates are a recognised trigger for torsades de pointes. |
| C3 | `LQT + SB` | Orange | Long QT with a slow heart rate: bradycardia raises the risk of torsades de pointes, so medicines and electrolytes should be reviewed the same day. |
| C4 | `LBBB + 1AVB` | Orange | First-degree AV block together with LBBB is what the 2018 conduction guideline calls extensive conduction disease. |
| C5 | `LBBB + STE` | Orange | LBBB itself shifts the ST segment, so ST elevation with LBBB cannot be read with the usual criteria; a clinician must compare it with earlier ECGs. Any chest pain makes this an emergency. |
| C6 | `2AVB + SB` | **Red** | Second-degree AV block with sinus bradycardia: a slow ventricular rate suggests a higher-grade block, which can progress suddenly to complete heart block. |
| C7 | `SB + 1AVB` | Orange | A slow sinus rate together with a long PR interval can both come from medicines that slow the AV node. **Additional step:** Ask the clinician to review AV-nodal-blocking medicines — beta-blockers, calcium-channel blockers, and digoxin — which can cause both a slow heart rate and a long PR interval. |
| C8 | `LBBB + AF` or `LBBB + AFL` | Orange | Atrial fibrillation or flutter with LBBB produces a wide-complex rhythm that, when fast, can be hard to tell apart from a ventricular rhythm. **Additional step:** A fast, wide-complex rhythm needs prompt clinician review: make sure a clinician reads this tracing today. |
| Rhythm conflict | `SB + STACH` | note only | The model flagged rhythms that cannot both be the underlying rhythm of one tracing (SB, STACH). A clinician must read the rhythm; guidance uses the more urgent one. |
| Rhythm conflict | `STACH + AF` | note only | The model flagged rhythms that cannot both be the underlying rhythm of one tracing (AF, STACH). A clinician must read the rhythm; guidance uses the more urgent one. |
| Rhythm conflict | `STACH + AFL` | note only | The model flagged rhythms that cannot both be the underlying rhythm of one tracing (AFL, STACH). A clinician must read the rhythm; guidance uses the more urgent one. |
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
C7 and C8 add their steps to `recommended_next_steps` after the tier steps
and any AF/AFL stroke-risk step. Notes and steps are deduplicated.

### Labels that cannot be read reliably together

| Rule | Flagged together | Tier | Note |
|---|---|---|---|
| K1 | `AF` + `1AVB`, `2AVB`, or legacy `IAVB` | Orange | The PR interval cannot be measured in atrial fibrillation, so an AV-block flag cannot be read reliably together with AF. A clinician needs to read the tracing. |
| K2 | `AFL` + `1AVB` or `2AVB` | Orange | In atrial flutter, 2:1 or 4:1 conduction is normal flutter physiology, not true second-degree AV block, and the PR interval cannot be measured reliably. A clinician needs to read the tracing. |
| K3 | `3AVB` + `1AVB` or `2AVB` | **Red** | Complete (third-degree) AV block and first- or second-degree AV block are mutually exclusive labels. Guidance uses the higher one, complete heart block (Red). |
| K4 | `AF + 3AVB` | **Red** | In atrial fibrillation, a slow, regular ventricular rhythm can mean complete heart block. Digoxin toxicity is one possible cause, so the full medication list is important. |

Basis: Merck AV block, AF, and atrial flutter; K5 also uses the 2018
ACC/AHA/HRS conduction guideline. Labels are not suppressed by these notes.

### Long QT measurement caveats

| Rule | Flagged together | Tier | Note |
|---|---|---|---|
| Q1 | `LQT + LBBB` | Orange | LBBB widens the QRS, which lengthens the QT, so the corrected QT is overestimated. A clinician should measure the QT manually. |
| Q2 | `LQT + STACH` | Orange | At high heart rates the usual (Bazett) correction overcorrects the QT. A clinician should recheck the corrected QT. |
| Q3 | `LQT + AF` | Orange | The QT interval is unreliable in an irregular rhythm such as AF. A clinician should average the QT over several beats. |

Basis: the AHA/ACCF/HRS 2009 ECG standardization Part IV statement and Merck
torsades/long QT. These are Orange caveats, not reasons to lower urgency.
`STEMI` or `3AVB` with any other finding stays **Red**; no combination,
label-conflict note, or QT caveat lowers a tier.

## Per-condition rules (earlier model `convnextv2_tiny_v1img_v1`)

`RBBB`, `PAC`, `PVC`, `LAFB`, `LAE` are Yellow; their text and sources are
unchanged (Merck bundle/fascicular block, 2018 conduction guideline, AHA
premature contractions, Cleveland Clinic LAE). `AF`, `LBBB`, `IAVB`, `NORM`
share the clean12 rules above, including **LBBB at Orange** with its
newness/echocardiogram rationale. `AF + IAVB` gets the Orange PR-interval
conflict note (K1), and `AF + LBBB` gets the Orange wide-complex note and
prompt-review step (C8). Suppressed `LQT` never enters the earlier model's
rules, so Q1–Q3 do not apply to it.

## Context questions

The UI asks, and does not persist: age group (under 18, 18–64, 65–74, 75+,
unknown); symptoms (chest pain/pressure, new severe or worsening
breathlessness, fainting/near-fainting, palpitations, dizziness, sudden stroke
signs); history (heart failure, hypertension, diabetes, prior stroke/TIA or
clot, vascular disease/prior MI, other known structural heart disease). Until
answered, the result is marked provisional.

Selecting Under 18 adds this caution verbatim and prevents a Green result:

> Normal heart-rate and ECG interval values are different in children, so this app's adult thresholds for sinus bradycardia, sinus tachycardia, and long QT do not apply. A pediatric ECG needs a clinician's interpretation; do not use this result for triage.

The Yellow floor does not override higher urgency: Red symptoms still produce
Red, and the caution remains. With an unknown age there is no pediatric
caution until the age group is entered. The age group and all other context
answers remain ephemeral; no privacy-notice change is required.

## Response and visible clinician notes

`GuidanceResponse.cautions: list[str]` carries whole-result warnings and is
`[]` when there are none. The under-18 caution is shown prominently below the
urgency panel, outside collapsed details, and is printable.
`combination_notes: list[str]` includes combinations, label-conflict notes,
QT caveats, rhythm-conflict notes, and the sinus-node note. All notes are
visible after Recommended next steps under **"Notes for the clinician reading
this ECG"**; "Why these steps" retains the finding summaries only.

`reasons` contains only reasons at the final tier. Lower-tier notes remain in
`combination_notes` and stay visible even when a Red rule removes them from
`reasons`. The Yellow headline for a Normal read with no abnormal flag,
including the under-18 or heart-history floor, is:
"Normal ECG flagged — book a routine review to have the ECG read."

The response's safety net, shown for non-Red results, is:

> Symptoms override this screening result. For chest pain or pressure, severe or worsening trouble breathing, stroke signs, or fainting, call 911.

## Source register (checked 2026-10-08)

- [2025 ACC/AHA/ACEP/NAEMSP/SCAI Guideline for the Management of Patients With Acute Coronary Syndromes (Circulation)](https://www.ahajournals.org/doi/10.1161/CIR.0000000000001309)
- [2018 ACC/AHA/HRS Bradycardia and Cardiac Conduction Delay — Guidelines Made Simple](https://www.acc.org/-/media/Non-Clinical/Files-PDFs-Excel-MS-Word-etc/Guidelines/2018/Guidelines_Made_Simple_2018_Bradycardia.pdf)
- [2023 ACC/AHA/ACCP/HRS AF guideline — key perspectives](https://www.acc.org/latest-in-cardiology/ten-points-to-remember/2023/11/27/19/46/2023-acc-guideline-for-af-gl-af)
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
