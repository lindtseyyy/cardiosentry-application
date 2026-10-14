# Open questions: cardiologist feedback on the urgency layer

Recorded 2026-10-08; updated 2026-10-11. Both feedback passes are implemented in the app under `four-tier-2026-10-10`. The four first-review questions remain below; the second-review section records the adopted defaults and alternatives that still need confirmation. Revision 3 (`file-ouputs/CardioSentry_Urgency_and_Recommendation_Layer_Revised_v3.docx` and `.pdf`) presents the second pass to the adviser, with these questions in its Part B.

## Resolved

- **A separate paper or manuscript?** No. The paper is the revision 2 Word file `file-ouputs/CardioSentry_Urgency_and_Recommendation_Layer_Revised_v2.docx` and its PDF `…_Revised_v2.pdf`.

## Open

### 1. Under-18 handling

The cardiologist accepted either option: exclude pediatric use, or show a note that the result must not be used for triage.

- **Default in place: the note.** When the age group is "Under 18", the guidance response carries a `cautions` warning: the tool was not validated in children; adult heart-rate cut-offs of 60/100 beats/min and adult QT limits do not apply; a pediatric clinician must interpret the ECG; the result is not for triage. The result is also never Green; Yellow is the minimum. Red symptoms still give Red.
- **Alternative: full exclusion.** Under-18 gets no urgency tier at all. This changes the API contract because `urgency_level` can't be empty today. It means a new error code or a nullable tier, plus changes in `backend/services/guidance.py`, `backend/schemas/guidance.py`, `frontend/src/api/{types,client}.ts`, `GuidancePanel.tsx`, `docs/clinical-guidance.md`, `tests/test_guidance.py`, and regenerating the v2 docx/PDF.

### 2. Archive revision 2 in `../outputs/clinical-review/`?

- **Now:** the v2 docx and PDF exist only in `file-ouputs/`. Both copies of the originals are untouched.
- **If yes:** copy the two `_Revised_v2.*` files to `../outputs/clinical-review/`.

### 3. The older model (`convnextv2_tiny_v1img_v1`) is not described in the review document

- **Now:** the app applies the shared reviewed rules to the older model as well: unknown/new LBBB Orange, the AF + 1AVB note, the AF + LBBB step, 911 only, the under-18 warning, and fainting with an abnormal flag (including 2AVB) Red. The second pass also applies known-AF/LBBB Yellow baselines, the pacemaker caution/Yellow floor, the scope note and the global symptom refinements. The v2 document describes only the reviewed model, `convnext_v1_base_clean12`. The older model's own findings (RBBB, PAC, PVC, LAFB, LAE) and its 3 combination rules are not in the document.
- **Options:**
  - Leave it as is, if the older model is not going to the cardiologist.
  - Add an "older model" section to the document and have it reviewed.
  - Remove the older model from guidance (`SUPPORTED_MODEL_IDS`).

### 4. Follow-up message to the cardiologist about the LBBB and ST elevation mismatch

- **Background:** the cardiologist found that your earlier message and the PDF disagreed. The PDF (and the app) had LBBB = Yellow and ST elevation = Orange. Your message had LBBB = Orange and ST elevation = Red. Your message wasn't available here.
- **Now:** v2 states the final decisions in its "Changes in this revision" section. LBBB is Orange. ST elevation is Orange at baseline and goes to Red with symptoms.
- **To do (you):** decide whether to send him v2 with a short note confirming both points.

## Second review (2026-10-08)

Source: `file-ouputs/latest_to_implement/CardioSentry-Urgency-and-Recommendation-Layer-Revised-Cardiology-Review.docx`. The adviser reviewed the first Revised document, not v2, so some suggestions differ from the first pass. Defaults below are implemented choices, not a claim of reviewer approval; see `docs/clinical-guidance.md` for the disposition table.

### 1. Normal read with palpitations or dizziness (6.5)

- **Default in place: option (b).** With Normal alone, palpitations or dizziness gives Yellow with clinician review within a few days and consideration of heart-rhythm monitoring. Nothing flagged plus either symptom stays Orange. Heart-failure history alone does not make the Normal-plus-symptom result Orange; fainting still raises it according to the separate Orange/Red rules.
- **Alternative: option (a), keep Orange.** A Normal read with palpitations or dizziness would again require same-day assessment. The Yellow-within-days reason, step and headline would change together.

### 2. SB + first-degree AV block (5.1)

- **Default in place: benign-pair exception.** C7 is Yellow, and exactly SB+1AVB is exempt from the two-or-more-abnormal-flags Orange floor (a concurrent Normal flag does not cancel or change the pair). The medicine-review step and whole-tracing note remain. Symptoms, heart history, a third abnormal finding or another higher-tier rule still raise urgency.
- **Alternative: keep Orange and document over-triage.** Restore C7 Orange and apply the multiplicity floor to the pair, matching the v2 decision rather than this review's usually-benign-pair advice.

### 3. Exertional or supine fainting symptom (6.3, optional)

- **Default in place: add it.** "Fainting during exertion or while lying down" is a separate critical symptom chip (`fainting_exertion_or_supine`) and makes any result Red, even Normal or no reading.
- **Alternative: omit the extra question.** Remove the option from the backend/frontend enums and UI and remove its dedicated Red rule; retain the other fainting rules.

### 4. Optional combination refinements

- **Default in place: add both.** Q3 covers LQT with AF **or AFL** and asks for manual QT measurement averaged over several beats. K4 (AF+3AVB) adds "Tell the emergency team whether the patient takes digoxin."
- **Alternative: keep the narrower notes.** Limit Q3 to AF, omit K4's explicit digoxin step, or choose either refinement alone. The existing K4 note would still identify digoxin toxicity as a possible cause.

### 5. Known AF/flutter Yellow baseline and label

- **Default in place: add "Known atrial fibrillation or flutter (already diagnosed)".** `known_af_flutter` sets an AF or AFL flag's effective baseline to Yellow; symptoms, heart history, other flags and combinations can still raise it. The app cannot verify rate control or that stroke prevention is in place. Known AF+AFL together still gets the Orange multiplicity floor.
- **Alternative: keep the Orange baseline for all AF/flutter.** Remove the known-history option, or have the reviewer approve a more restrictive history question and its baseline criteria before changing them.

### 6. Known LBBB Yellow baseline

- **Default in place: add it.** "Known left bundle branch block (seen on an earlier ECG)" (`known_lbbb`) sets that finding's effective baseline to Yellow. The app does not verify the previous tracing; symptoms, history, other flags and combinations still raise urgency.
- **Alternative: keep all LBBB Orange.** Remove the known-history option, or restrict the Yellow path to a reviewer-approved history criterion.

### 7. Pacemaker or ICD

- **Default in place: caution plus Yellow floor only.** "Pacemaker or ICD" (`pacemaker_icd`) adds the paced-rhythm warning and prevents Green. It does not change finding tiers, count as structural-heart history or add an AF stroke-risk factor. Pediatric and paced cautions both remain when relevant.
- **Alternative: no new option, or a reviewer-defined exclusion.** Omitting the question removes the device-specific warning/floor; excluding paced ECGs from urgency guidance would instead require an explicit API/UI decision, not a silent tier change.

### 8. LBBB baseline: reviewer/v2 mismatch

- **Default in place: keep unknown/new LBBB Orange.** This preserves the first feedback round; the known-LBBB option provides a Yellow baseline path. Confirm this distinction with the adviser, who endorsed Yellow in the earlier document.
- **Alternative: all LBBB starts Yellow.** Change its default baseline and rationale, while retaining symptom/history/combination escalation and the newness/echocardiogram advice.

### 9. STE prevalence figure

- **Default in place: simplify app text.** It says "most do not turn out to have a STEMI", without the numerical range. The clinical basis retains "Moak et al. 2024 (60–80%, citing Brady 2001); app text simplified per 2026-10-08 review".
- **Alternative: retain the figure in app text.** Restore the range with an explicit Moak 2024 citation and the chest-pain/ST-elevation population qualifier.

### 10. AF aspirin sentence in patient-facing guidance

- **Default in place: keep it with the do-not-change instruction.** "Do not start, stop, or change aspirin, a blood thinner, or heart-rhythm medicine based on this screening result. Aspirin is no longer recommended for stroke prevention in AF; ask the clinician which option is right."
- **Alternative: clinician-facing text only.** Move the aspirin-prevention sentence to a clinician note or the clinical guide; retain the patient instruction not to change medicines from this result.

### 11. STE chest-pain gate on screen

- **Default in place: hide urgency until answered, still printable.** For incomplete context, no reported chest pain and a non-Red result, the backend supplies a priority chest-pain question. Yes re-requests with chest pain and yields Red; No reveals the existing result using local unsaved state. Cautions stay visible. Print includes the unanswered question, urgency, context and recommendations, but not answer buttons.
- **Alternative: show provisional Orange beneath the question.** Keep the question and responses but remove the screen-only hiding of the existing result. No answer or context response is persisted in either design.

### 12. Revision-3 docx/PDF and reviewer coverage

- **Done 2026-10-11.** `file-ouputs/CardioSentry_Urgency_and_Recommendation_Layer_Revised_v3.docx` and `…_v3.pdf` contain a response table for every review item, these questions (Part B, Questions 1–12, with a response sheet), a checklist of the Revision 2 rules the adviser has not seen (Question 13: 2AVB fainting step, C6, C7 medicine step, C8, label-conflict notes, sinus-node note, Long QT caveats) and a question on the older model (Question 14). Its texts and example urgencies are generated from `backend/services/guidance.py`; the generator was a scratch script (`/tmp/rev3/build_rev3.py`, two-pass via `/tmp/rev3/build.sh`). The v1/v2 files and the review are unchanged.
- **New points raised by the Revision 3 cross-check (defaults unchanged, asked in Part B):** AF and flutter both flagged with known AF/flutter stays Orange (2.2); Normal + palpitations/dizziness + heart failure stays Yellow (4.1); "Known vascular disease or prior heart attack" does not count as heart disease for fainting → Red (6.1) or abnormal finding → Orange (6.2); fainting and palpitations are recorded without timing (6.3); reported isolated fainting is Orange while the Orange step and safety net say fainting means call emergency services (6.4); the under-18 caution says "do not use this result for triage" while a tier is shown (7); a pacemaker/ICD does not count as heart disease for fainting (8.1) or abnormal-finding (8.2) rules; only ST elevation triggers the chest-pain question (9.1).
- **Text corrected while building Revision 3:** C7 and 3AVB medicine lists name non-dihydropyridine calcium-channel blockers; the flutter reason refers to the ventricular rate with 2:1 conduction; the flutter AV-block note covers first-degree block; the scope note lists Brugada pattern and pericarditis "as specific diagnoses"; the no-reading step says "requested"; the 2AVB echo step cites the 2018 guideline; C5 says "compare the tracing"; the STEMI step reads "Even with no pain right now…".

### 13. Per-label sensitivity/specificity

- **Default in place: thesis results chapter, outside app scope.** No per-label performance display or new application calculation is added.
- **Alternative: explicitly request an app performance display.** That would need the measured validation results and an agreed presentation; it is not an implication of this clinical-text review.
