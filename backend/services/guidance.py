"""Versioned, model-specific four-tier urgency and next-step decision support.

This is deliberately NOT a generic ECG rules engine.  Each reviewed model is a
``RuleSet`` locked to its exact served-label order and suppression policy; a
future model or a policy change must be reviewed and added here before
``supports`` returns true.  The evidence-to-rule matrix lives in
``docs/clinical-guidance.md`` and must be updated together with this file.

Tiers, in increasing urgency:

* ``green``  — the model read the ECG as Normal and nothing reported raises
  the tier; no extra action is needed from this result alone.
* ``yellow`` — book a routine clinician review to confirm the reading.
* ``orange`` — get a medical assessment the same day.
* ``red``    — call emergency services now.

The final tier is the highest one produced by any flagged condition, any
reported symptom, the patient's history, or a listed condition combination.
Model scores are never used as a severity measure: crossing the threshold only
selects which conditions enter the rules.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from backend.schemas.guidance import (
    FindingGuidance,
    GuidanceContext,
    GuidanceRequest,
    GuidanceResponse,
    GuidanceSource,
    UrgencyLevel,
)
from backend.schemas.model_descriptor import ModelDescriptor

RULE_VERSION = "four-tier-2026-10-08"

TIERS: tuple[UrgencyLevel, ...] = ("green", "yellow", "orange", "red")
_RANK = {tier: rank for rank, tier in enumerate(TIERS)}

TIER_INFO: dict[str, dict[str, str]] = {
    "green": {
        "label": "Green — no action from this result",
        "action": "No extra action needed",
        "description": (
            "The model read this ECG as Normal and nothing reported raises the "
            "tier. Keep usual care; a normal ECG does not rule out heart disease."
        ),
    },
    "yellow": {
        "label": "Yellow — routine review",
        "action": "Book a routine clinician review",
        "description": (
            "Not an emergency on the information given. Have a clinician "
            "confirm and interpret the ECG at a routine appointment."
        ),
    },
    "orange": {
        "label": "Orange — same-day assessment",
        "action": "Get a medical assessment today",
        "description": (
            "Needs a clinician to confirm the ECG and assess the patient the "
            "same day. If the usual clinician cannot see them today, use an "
            "urgent-care centre or emergency department."
        ),
    },
    "red": {
        "label": "Red — emergency now",
        "action": "Call emergency services now",
        "description": (
            "Possible time-critical heart emergency. Call 911 now; do not wait "
            "for symptoms to settle."
        ),
    },
}

DISCLAIMER = (
    "Screening and decision support only. This experimental image-model output "
    "is not a diagnosis, does not measure clinical severity, and does not "
    "replace a clinician-interpreted ECG or professional medical evaluation."
)

PEDIATRIC_CAUTION = (
    "Normal heart-rate and ECG interval values are different in children, so "
    "this app's adult thresholds for sinus bradycardia, sinus tachycardia, and "
    "long QT do not apply. A pediatric ECG needs a clinician's interpretation; "
    "do not use this result for triage."
)

# Symptoms that make any result Red, whatever the model flagged.
RED_SYMPTOMS = frozenset({"chest_pain", "severe_shortness_of_breath", "stroke_signs"})
# Symptoms that need assessment even with no abnormal flag.
CARDIAC_SYMPTOMS = frozenset({"palpitations", "dizziness", "fainting"})
HEART_HISTORY = frozenset({"heart_failure", "known_heart_disease"})
AF_STROKE_RISKS = frozenset({
    "heart_failure", "hypertension", "diabetes", "prior_stroke_tia",
    "vascular_disease",
})

_SOURCES: dict[str, GuidanceSource] = {
    "aha_af_symptoms": GuidanceSource(
        id="aha_af_symptoms",
        title="What are the Symptoms of Atrial Fibrillation?",
        organization="American Heart Association",
        url=("https://www.heart.org/en/health-topics/atrial-fibrillation/"
             "what-are-the-symptoms-of-atrial-fibrillation"),
    ),
    "acc_af_2023": GuidanceSource(
        id="acc_af_2023",
        title="2023 Guideline for Diagnosis and Management of Atrial Fibrillation: Key Perspectives",
        organization="American College of Cardiology",
        url=("https://www.acc.org/latest-in-cardiology/ten-points-to-remember/"
             "2023/11/27/19/46/2023-acc-guideline-for-af-gl-af"),
    ),
    "merck_af": GuidanceSource(
        id="merck_af",
        title="Atrial Fibrillation",
        organization="Merck Manual Professional Edition",
        url=("https://www.merckmanuals.com/professional/cardiovascular-disorders/"
             "arrhythmias-and-conduction-disorders/atrial-fibrillation"),
    ),
    "merck_afl": GuidanceSource(
        id="merck_afl",
        title="Atrial Flutter",
        organization="Merck Manual Professional Edition",
        url=("https://www.merckmanuals.com/professional/cardiovascular-disorders/"
             "arrhythmias-and-conduction-disorders/atrial-flutter"),
    ),
    "acc_conduction_2018": GuidanceSource(
        id="acc_conduction_2018",
        title="2018 Guideline on Bradycardia and Cardiac Conduction Delay: Guidelines Made Simple",
        organization="American College of Cardiology / American Heart Association / Heart Rhythm Society",
        url=("https://www.acc.org/-/media/Non-Clinical/Files-PDFs-Excel-MS-Word-etc/"
             "Guidelines/2018/Guidelines_Made_Simple_2018_Bradycardia.pdf"),
    ),
    "merck_av_block": GuidanceSource(
        id="merck_av_block",
        title="Atrioventricular Block",
        organization="Merck Manual Professional Edition",
        url=("https://www.merckmanuals.com/professional/cardiovascular-disorders/"
             "arrhythmias-and-conduction-disorders/atrioventricular-block"),
    ),
    "merck_bundle_fascicular": GuidanceSource(
        id="merck_bundle_fascicular",
        title="Bundle Branch Block and Fascicular Block",
        organization="Merck Manual Professional Edition",
        url=("https://www.merckmanuals.com/professional/cardiovascular-disorders/"
             "arrhythmias-and-conduction-disorders/bundle-branch-block-and-fascicular-block"),
    ),
    "aha_bradycardia": GuidanceSource(
        id="aha_bradycardia",
        title="Bradycardia: Slow Heart Rate",
        organization="American Heart Association",
        url=("https://www.heart.org/en/health-topics/arrhythmia/about-arrhythmia/"
             "bradycardia--slow-heart-rate"),
    ),
    "cleveland_sinus_brady": GuidanceSource(
        id="cleveland_sinus_brady",
        title="Sinus Bradycardia: Causes, Symptoms & Treatment",
        organization="Cleveland Clinic",
        url="https://my.clevelandclinic.org/health/diseases/22473-sinus-bradycardia",
    ),
    "cleveland_sinus_tachy": GuidanceSource(
        id="cleveland_sinus_tachy",
        title="Sinus Tachycardia: Causes, Symptoms & Treatment",
        organization="Cleveland Clinic",
        url="https://my.clevelandclinic.org/health/diseases/23210-sinus-tachycardia",
    ),
    "merck_tdp_lqt": GuidanceSource(
        id="merck_tdp_lqt",
        title="Torsades de Pointes Ventricular Tachycardia (long QT)",
        organization="Merck Manual Professional Edition",
        url=("https://www.merckmanuals.com/professional/cardiovascular-disorders/"
             "arrhythmias-and-conduction-disorders/"
             "long-qt-syndrome-and-torsades-de-pointes-ventricular-tachycardia"),
    ),
    "aha_ecg_qt_2009": GuidanceSource(
        id="aha_ecg_qt_2009",
        title=(
            "AHA/ACCF/HRS Recommendations for the Standardization and Interpretation "
            "of the Electrocardiogram: Part IV: The ST Segment, T and U Waves, "
            "and the QT Interval"
        ),
        organization="American Heart Association / American College of Cardiology Foundation / Heart Rhythm Society",
        url="https://www.jacc.org/doi/10.1016/j.jacc.2008.12.014",
    ),
    "aha_conduction_lqts": GuidanceSource(
        id="aha_conduction_lqts",
        title="Heart Conduction Disorders (includes Long QT Syndrome)",
        organization="American Heart Association",
        url=("https://www.heart.org/en/health-topics/arrhythmia/about-arrhythmia/"
             "conduction-disorders"),
    ),
    "acc_acs_2025": GuidanceSource(
        id="acc_acs_2025",
        title="2025 ACC/AHA/ACEP/NAEMSP/SCAI Guideline for the Management of Patients With Acute Coronary Syndromes",
        organization="American College of Cardiology / American Heart Association (Circulation)",
        url="https://www.ahajournals.org/doi/10.1161/CIR.0000000000001309",
    ),
    "stemi_mimics_2024": GuidanceSource(
        id="stemi_mimics_2024",
        title="STEMI mimics: the differential diagnosis of non-ACS causes of ST-segment/T-wave abnormalities in the chest pain patient",
        organization="Turkish Journal of Emergency Medicine (2024), via PubMed Central",
        url="https://pmc.ncbi.nlm.nih.gov/articles/PMC11573177/",
    ),
    "aha_premature": GuidanceSource(
        id="aha_premature",
        title="Premature Contractions — PACs and PVCs",
        organization="American Heart Association",
        url=("https://www.heart.org/en/health-topics/arrhythmia/about-arrhythmia/"
             "premature-contractions-pacs-and-pvcs"),
    ),
    "cleveland_lae": GuidanceSource(
        id="cleveland_lae",
        title="Left Atrial Enlargement: Symptoms, Causes and Treatment",
        organization="Cleveland Clinic",
        url="https://my.clevelandclinic.org/health/diseases/23967-left-atrial-enlargement",
    ),
    "acc_syncope_2017": GuidanceSource(
        id="acc_syncope_2017",
        title="2017 Guideline for the Evaluation and Management of Patients With Syncope",
        organization="American College of Cardiology / American Heart Association / Heart Rhythm Society",
        url="https://www.acc.org/Guidelines/Guidelines/2017/03/09/08/27/Syncope",
    ),
    "aha_heart_attack": GuidanceSource(
        id="aha_heart_attack",
        title="Warning Signs of a Heart Attack",
        organization="American Heart Association",
        url=("https://www.heart.org/en/health-topics/heart-attack/"
             "warning-signs-of-a-heart-attack"),
    ),
    "uspstf_ecg_2018": GuidanceSource(
        id="uspstf_ecg_2018",
        title="Cardiovascular Disease Risk: Screening With Electrocardiography",
        organization="U.S. Preventive Services Task Force",
        url=("https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/"
             "cardiovascular-disease-risk-screening-with-electrocardiography"),
    ),
    "cdc_stroke": GuidanceSource(
        id="cdc_stroke",
        title="Signs and Symptoms of Stroke",
        organization="U.S. Centers for Disease Control and Prevention",
        url="https://www.cdc.gov/stroke/signs-symptoms/index.html",
    ),
}


@dataclass(frozen=True)
class FindingRule:
    """One condition's baseline tier, its symptom escalations, and its text."""

    tier: UrgencyLevel
    summary: str
    next_steps: tuple[str, ...]
    sources: tuple[str, ...]
    # Why the baseline tier is Orange/Red; required for those tiers.
    reason: str = ""
    # Reported symptoms that make THIS condition Red (beyond the global rules).
    red_if: frozenset[str] = frozenset()
    red_reason: str = ""


@dataclass(frozen=True)
class Combination:
    """A clinically meaningful co-occurrence of flagged conditions."""

    all_of: frozenset[str]
    tier: UrgencyLevel
    note: str
    sources: tuple[str, ...]
    any_of: frozenset[str] = field(default_factory=frozenset)
    next_steps: tuple[str, ...] = ()

    def matches(self, flagged: set[str]) -> bool:
        return self.all_of <= flagged and (not self.any_of or bool(self.any_of & flagged))


_FIRST_DEGREE_AVB = FindingRule(
    tier="yellow",
    summary=(
        "First-degree AV block (a lengthened PR interval) is rarely symptomatic "
        "and usually needs no treatment by itself; routine heart imaging is not "
        "indicated without signs of structural heart disease."
    ),
    next_steps=(
        "Ask the clinician to review medicines that slow conduction through the "
        "AV node (for example beta-blockers, some calcium-channel blockers, "
        "digoxin, amiodarone).",
    ),
    sources=("merck_av_block", "acc_conduction_2018"),
)

_ATRIAL_FIB = FindingRule(
    tier="orange",
    reason=(
        "Atrial fibrillation needs prompt confirmation, a heart-rate check, and a "
        "stroke-risk assessment."
    ),
    summary=(
        "Atrial fibrillation is an irregular atrial rhythm that raises stroke "
        "risk and can make the heart beat fast. It needs clinician confirmation "
        "and assessment of heart rate, symptoms, cause, and stroke risk."
    ),
    next_steps=(
        "Ask whether this AF is new. New AF needs a heart-rate check, a search "
        "for causes (for example thyroid disease, high blood pressure, sleep "
        "apnoea, alcohol), and a formal stroke-risk assessment.",
        "Do not start, stop, or change aspirin, a blood thinner, or heart-rhythm "
        "medicine based on this screening result.",
    ),
    sources=("aha_af_symptoms", "acc_af_2023", "merck_af"),
)

_LBBB = FindingRule(
    tier="orange",
    reason=(
        "The app usually cannot tell whether this LBBB is new, and a new LBBB "
        "needs prompt evaluation, including an echocardiogram."
    ),
    summary=(
        "Left bundle branch block markedly increases the likelihood of "
        "underlying structural heart disease, including a weak heart muscle. "
        "LBBB also hides the usual ECG signs of a heart attack, so any chest "
        "pain with LBBB needs emergency assessment."
    ),
    next_steps=(
        "Ask whether this LBBB is new by comparing with previous ECGs. A new "
        "LBBB needs prompt evaluation, including an echocardiogram (2018 "
        "conduction guideline, Class I).",
    ),
    sources=("acc_conduction_2018", "merck_bundle_fascicular"),
)

# Shared by every rule set; a rule set only selects the labels it serves.
FINDING_RULES: dict[str, FindingRule] = {
    "NONE": FindingRule(
        tier="yellow",
        summary=(
            "No condition, not even Normal, crossed its model threshold, so the "
            "model gives no reading. This does not rule out a heart problem or "
            "medically clear symptoms."
        ),
        next_steps=(
            "If this ECG was recorded because of a symptom or concern, still "
            "share the original tracing with the clinician who ordered it.",
        ),
        sources=("aha_heart_attack", "cdc_stroke"),
    ),
    "NORM": FindingRule(
        tier="green",
        reason=(
            "The model read this ECG as Normal, with no abnormal condition and no "
            "reported symptoms or history that raise the tier."
        ),
        summary=(
            "In a person without symptoms, a normal ECG needs no follow-up of its "
            "own. It is still not medical clearance: it cannot rule out coronary "
            "disease or a rhythm problem that comes and goes."
        ),
        next_steps=(
            "Do not use the Normal flag to dismiss new, severe, or worsening symptoms.",
        ),
        sources=("uspstf_ecg_2018", "aha_heart_attack", "cdc_stroke"),
    ),
    # ---------------------------------------------------- clean12 conditions
    "SB": FindingRule(
        tier="yellow",
        summary=(
            "Sinus bradycardia (a regular rhythm under 60 beats/min) is often "
            "normal in physically fit people and during sleep. It matters when "
            "it causes tiredness, dizziness, breathlessness, or fainting, or "
            "when it comes from medicines or conditions such as an underactive "
            "thyroid."
        ),
        next_steps=(
            "Tell the clinician about heart-rate-slowing medicines (for example "
            "beta-blockers, including eye drops, some calcium-channel blockers, "
            "antiarrhythmics, lithium) and about fitness level.",
            "Ask whether a thyroid or electrolyte blood test is appropriate if "
            "no obvious cause is found.",
        ),
        sources=("acc_conduction_2018", "aha_bradycardia", "cleveland_sinus_brady"),
    ),
    "STACH": FindingRule(
        tier="yellow",
        summary=(
            "Sinus tachycardia (a regular rhythm over 100 beats/min) is usually "
            "the heart responding to something else — exercise, anxiety, pain, "
            "fever, dehydration, anaemia, blood loss, an overactive thyroid, "
            "caffeine or other stimulants, or medicines. Treatment targets the "
            "cause."
        ),
        next_steps=(
            "Ask the clinician to look for the cause (for example fever, "
            "dehydration, anaemia, thyroid, stimulants, medicines), especially "
            "if the fast rate persists at rest.",
        ),
        sources=("cleveland_sinus_tachy",),
    ),
    "LBBB": _LBBB,
    "LQT": FindingRule(
        tier="orange",
        reason=(
            "Long QT raises the risk of a dangerous ventricular rhythm, so medicines "
            "and electrolytes need same-day review."
        ),
        summary=(
            "A long QT interval can be inherited or caused by medicines, low "
            "potassium or magnesium, or a slow heart rate. It raises the risk "
            "of torsades de pointes, a dangerous ventricular rhythm that causes "
            "fainting and can cause sudden death; the risk rises steeply when "
            "the corrected QT exceeds 500 ms."
        ),
        next_steps=(
            "Ask a clinician today to measure the corrected QT interval and to "
            "check potassium and magnesium.",
            "Bring a list of every medicine and supplement. Many antibiotics, "
            "antidepressants, antipsychotics, antiarrhythmics, and anti-nausea "
            "medicines prolong QT — ask the prescriber today rather than "
            "stopping a prescribed medicine on your own.",
            "Tell the clinician about any family history of sudden unexplained "
            "death or fainting, which can point to inherited long QT syndrome.",
        ),
        sources=("merck_tdp_lqt", "aha_conduction_lqts"),
        red_if=frozenset({"palpitations", "dizziness"}),
        red_reason=(
            "Long QT with palpitations or dizziness can mean torsades de pointes "
            "is occurring."
        ),
    ),
    "AF": _ATRIAL_FIB,
    "AFL": FindingRule(
        tier="orange",
        reason=(
            "Atrial flutter often runs near 150 beats/min and carries the same stroke-"
            "prevention considerations as atrial fibrillation."
        ),
        summary=(
            "Atrial flutter is a fast atrial rhythm, often with a regular heart "
            "rate near 150 beats/min. Stroke-prevention guidance is the same as "
            "for atrial fibrillation, and many people with flutter also have "
            "periods of AF."
        ),
        next_steps=(
            "Ask for heart-rate control and a formal stroke-risk assessment, and "
            "whether cardioversion or catheter ablation is appropriate.",
            "Do not start, stop, or change a blood thinner or heart-rhythm "
            "medicine based on this screening result.",
        ),
        sources=("merck_afl", "acc_af_2023"),
    ),
    "3AVB": FindingRule(
        tier="red",
        reason=(
            "Complete heart block can cause sudden fainting or cardiac arrest and "
            "usually needs a pacemaker."
        ),
        summary=(
            "Third-degree (complete) AV block means no atrial beats reach the "
            "ventricles; the heart depends on a slow back-up rhythm that can "
            "fail, causing fainting or sudden death. Without a reversible cause, "
            "a permanent pacemaker is recommended even without symptoms."
        ),
        next_steps=(
            "Tell the emergency team the ECG may show complete heart block, and "
            "give them the list of medicines, since some (for example "
            "beta-blockers, calcium-channel blockers, digoxin) can cause or "
            "worsen AV block.",
        ),
        sources=("merck_av_block", "acc_conduction_2018"),
    ),
    "2AVB": FindingRule(
        tier="orange",
        reason=(
            "Second-degree AV block may be a type that progresses suddenly to complete"
            " heart block; the type must be determined the same day."
        ),
        summary=(
            "In second-degree AV block some atrial beats do not reach the "
            "ventricles. Mobitz type I (Wenckebach) is often benign, especially "
            "in young or athletic people; Mobitz type II and high-grade block "
            "can progress suddenly to complete heart block, and a pacemaker is "
            "recommended regardless of symptoms. This model uses one label for "
            "every type of second-degree block (Mobitz I, Mobitz II, 2:1, "
            "high-grade), so it cannot tell them apart."
        ),
        next_steps=(
            "The type of block cannot be determined from this result, and some "
            "types need urgent pacemaker evaluation. Ask a clinician today to "
            "determine the type (Mobitz I, Mobitz II, 2:1, or high-grade) from "
            "the full tracing.",
            "Review medicines that slow AV conduction; for Mobitz type II or "
            "high-grade block, an echocardiogram is recommended (Class I).",
        ),
        sources=("merck_av_block", "acc_conduction_2018"),
        red_if=frozenset({"dizziness", "fainting"}),
        red_reason=(
            "Second-degree AV block with dizziness or fainting is a symptomatic "
            "slow rhythm and can progress to complete heart block."
        ),
    ),
    "1AVB": _FIRST_DEGREE_AVB,
    "STEMI": FindingRule(
        tier="red",
        reason=(
            "An ST-elevation heart-attack pattern is time-critical: treatment to "
            "reopen the artery must not be delayed."
        ),
        summary=(
            "This pattern suggests an ST-elevation heart attack — a coronary "
            "artery may be blocked. Reopening it is time-critical: the 2025 "
            "ACS guideline targets 90 minutes or less from first medical "
            "contact to treatment at a PCI-capable hospital."
        ),
        next_steps=(
            "This applies even with no pain right now: the ambulance team can "
            "record a new ECG and alert a heart-attack centre on the way.",
            "Stop any activity and rest while waiting. Take aspirin only if the "
            "dispatcher or a clinician tells you to.",
        ),
        sources=("acc_acs_2025", "aha_heart_attack"),
    ),
    "STE": FindingRule(
        tier="orange",
        reason=(
            "ST elevation must be treated as a possible heart attack until a clinician"
            " compares it with the patient's symptoms and earlier ECGs."
        ),
        summary=(
            "ST elevation can be an acute heart attack, but many other "
            "conditions cause it — normal early repolarization, pericarditis, "
            "left ventricular hypertrophy, LBBB, or an old infarct. Among "
            "chest-pain patients with ST elevation, most (about 60–80%) do not "
            "turn out to have a STEMI, so a clinician must read the tracing."
        ),
        next_steps=(
            "Have a clinician read this ECG today, ideally against a previous "
            "ECG, and ask specifically whether the ST elevation is new.",
            "If chest discomfort, breathlessness, cold sweat, nausea, or "
            "lightheadedness occurs, call emergency services — do not wait for "
            "the appointment.",
        ),
        sources=("stemi_mimics_2024", "acc_acs_2025", "aha_heart_attack"),
        red_if=frozenset({"palpitations", "dizziness"}),
        red_reason=(
            "ST elevation with lightheadedness or palpitations must be treated "
            "as a possible heart attack until a clinician excludes it."
        ),
    ),
    # --------------------------------------- convnextv2_tiny_v1img_v1 labels
    "IAVB": _FIRST_DEGREE_AVB,
    "RBBB": FindingRule(
        tier="yellow",
        summary=(
            "Isolated right bundle branch block may need no specific treatment, "
            "but clinicians assess for an underlying heart or lung condition."
        ),
        next_steps=(
            "Ask whether the RBBB is isolated and whether structural heart "
            "evaluation is appropriate.",
        ),
        sources=("acc_conduction_2018", "merck_bundle_fascicular"),
    ),
    "PAC": FindingRule(
        tier="yellow",
        summary=(
            "Occasional premature atrial contractions are common, but symptoms "
            "or frequent ectopy can justify monitoring and evaluation."
        ),
        next_steps=(
            "Discuss possible triggers, medicines, and whether heart-rhythm "
            "monitoring is needed.",
        ),
        sources=("aha_premature",),
    ),
    "PVC": FindingRule(
        tier="yellow",
        summary=(
            "Premature ventricular contractions can be benign, but symptoms or "
            "underlying heart disease can change their significance."
        ),
        next_steps=(
            "Ask whether heart-rhythm monitoring or an echocardiogram is appropriate.",
        ),
        sources=("aha_premature",),
    ),
    "LAFB": FindingRule(
        tier="yellow",
        summary=(
            "Left anterior fascicular block often causes no symptoms, but it "
            "should be interpreted with other conduction findings and heart history."
        ),
        next_steps=(
            "Ask the clinician to assess for associated structural or conduction disease.",
        ),
        sources=("acc_conduction_2018", "merck_bundle_fascicular"),
    ),
    "LAE": FindingRule(
        tier="yellow",
        summary=(
            "An ECG pattern suggesting left atrial enlargement can reflect high "
            "blood pressure, valve disease, or another heart condition and "
            "needs confirmation."
        ),
        next_steps=(
            "Ask about blood-pressure review, an echocardiogram, and possible "
            "underlying valve or heart disease.",
        ),
        sources=("cleveland_lae",),
    ),
}

COMBINATIONS: tuple[Combination, ...] = (
    Combination(
        all_of=frozenset({"LBBB", "2AVB"}),
        tier="red",
        note=(
            "Second-degree AV block together with LBBB suggests disease below "
            "the AV node, which can progress suddenly to complete heart block."
        ),
        sources=("merck_av_block", "acc_conduction_2018"),
    ),
    Combination(
        all_of=frozenset({"LQT"}),
        any_of=frozenset({"2AVB", "3AVB"}),
        tier="red",
        note=(
            "Long QT with AV block: pauses and slow ventricular rates are a "
            "recognised trigger for torsades de pointes."
        ),
        sources=("merck_tdp_lqt", "merck_av_block"),
    ),
    Combination(
        all_of=frozenset({"LQT", "SB"}),
        tier="orange",
        note=(
            "Long QT with a slow heart rate: bradycardia raises the risk of "
            "torsades de pointes, so medicines and electrolytes should be "
            "reviewed the same day."
        ),
        sources=("merck_tdp_lqt",),
    ),
    Combination(
        all_of=frozenset({"LBBB", "1AVB"}),
        tier="orange",
        note=(
            "First-degree AV block together with LBBB is what the 2018 "
            "conduction guideline calls extensive conduction disease."
        ),
        sources=("acc_conduction_2018",),
    ),
    Combination(
        all_of=frozenset({"LBBB", "STE"}),
        tier="orange",
        note=(
            "LBBB itself shifts the ST segment, so ST elevation with LBBB cannot "
            "be read with the usual criteria; a clinician must compare it with "
            "earlier ECGs. Any chest pain makes this an emergency."
        ),
        sources=("acc_acs_2025", "stemi_mimics_2024"),
    ),
    Combination(
        all_of=frozenset({"2AVB", "SB"}),
        tier="red",
        note=(
            "Second-degree AV block with sinus bradycardia: a slow ventricular "
            "rate suggests a higher-grade block, which can progress suddenly "
            "to complete heart block."
        ),
        sources=("merck_av_block", "acc_conduction_2018"),
    ),
    Combination(
        all_of=frozenset({"SB", "1AVB"}),
        tier="orange",
        note=(
            "A slow sinus rate together with a long PR interval can both come "
            "from medicines that slow the AV node."
        ),
        next_steps=(
            "Ask the clinician to review AV-nodal-blocking medicines — "
            "beta-blockers, calcium-channel blockers, and digoxin — which can "
            "cause both a slow heart rate and a long PR interval.",
        ),
        sources=("acc_conduction_2018", "merck_av_block"),
    ),
    Combination(
        all_of=frozenset({"LBBB"}),
        any_of=frozenset({"AF", "AFL"}),
        tier="orange",
        note=(
            "Atrial fibrillation or flutter with LBBB produces a wide-complex "
            "rhythm that, when fast, can be hard to tell apart from a "
            "ventricular rhythm."
        ),
        next_steps=(
            "A fast, wide-complex rhythm needs prompt clinician review: make "
            "sure a clinician reads this tracing today.",
        ),
        sources=("merck_af", "merck_afl", "merck_bundle_fascicular"),
    ),
    Combination(
        all_of=frozenset({"AF"}),
        any_of=frozenset({"1AVB", "2AVB", "IAVB"}),
        tier="orange",
        note=(
            "The PR interval cannot be measured in atrial fibrillation, so an "
            "AV-block flag cannot be read reliably together with AF. A clinician "
            "needs to read the tracing."
        ),
        sources=("merck_af", "merck_av_block"),
    ),
    Combination(
        all_of=frozenset({"AFL"}),
        any_of=frozenset({"1AVB", "2AVB"}),
        tier="orange",
        note=(
            "In atrial flutter, 2:1 or 4:1 conduction is normal flutter "
            "physiology, not true second-degree AV block, and the PR interval "
            "cannot be measured reliably. A clinician needs to read the tracing."
        ),
        sources=("merck_afl", "merck_av_block"),
    ),
    Combination(
        all_of=frozenset({"3AVB"}),
        any_of=frozenset({"1AVB", "2AVB"}),
        tier="red",
        note=(
            "Complete (third-degree) AV block and first- or second-degree AV "
            "block are mutually exclusive labels. Guidance uses the higher one, "
            "complete heart block (Red)."
        ),
        sources=("merck_av_block",),
    ),
    Combination(
        all_of=frozenset({"AF", "3AVB"}),
        tier="red",
        note=(
            "In atrial fibrillation, a slow, regular ventricular rhythm can "
            "mean complete heart block. Digoxin toxicity is one possible cause, "
            "so the full medication list is important."
        ),
        sources=("merck_af", "merck_av_block"),
    ),
    Combination(
        all_of=frozenset({"SB"}),
        any_of=frozenset({"AF", "AFL"}),
        tier="orange",
        note=(
            "Sinus bradycardia flagged together with atrial fibrillation or "
            "flutter can occur in sinus node disease (tachy-brady syndrome). "
            "A clinician needs to review the rhythm."
        ),
        sources=("acc_conduction_2018", "merck_af"),
    ),
    Combination(
        all_of=frozenset({"LQT", "LBBB"}),
        tier="orange",
        note=(
            "LBBB widens the QRS, which lengthens the QT, so the corrected QT "
            "is overestimated. A clinician should measure the QT manually."
        ),
        sources=("aha_ecg_qt_2009", "merck_tdp_lqt"),
    ),
    Combination(
        all_of=frozenset({"LQT", "STACH"}),
        tier="orange",
        note=(
            "At high heart rates the usual (Bazett) correction overcorrects the "
            "QT. A clinician should recheck the corrected QT."
        ),
        sources=("aha_ecg_qt_2009", "merck_tdp_lqt"),
    ),
    Combination(
        all_of=frozenset({"LQT", "AF"}),
        tier="orange",
        note=(
            "The QT interval is unreliable in an irregular rhythm such as AF. "
            "A clinician should average the QT over several beats."
        ),
        sources=("aha_ecg_qt_2009", "merck_tdp_lqt"),
    ),
    # Legacy (convnextv2_tiny_v1img_v1) combinations.
    Combination(
        all_of=frozenset({"RBBB", "LAFB"}),
        tier="orange",
        note=(
            "RBBB plus LAFB can represent a bifascicular conduction pattern. It "
            "needs same-day clinician review; fainting makes it an emergency."
        ),
        sources=("acc_conduction_2018", "merck_bundle_fascicular", "acc_syncope_2017"),
    ),
    Combination(
        all_of=frozenset({"IAVB"}),
        any_of=frozenset({"LBBB", "RBBB", "LAFB"}),
        tier="orange",
        note=(
            "First-degree AV block together with a bundle or fascicular block "
            "is more extensive conduction disease than either flag alone."
        ),
        sources=("acc_conduction_2018", "merck_bundle_fascicular"),
    ),
    Combination(
        all_of=frozenset({"AF", "LAE"}),
        tier="orange",
        note=(
            "AF and LAE should be assessed together because atrial size and the "
            "underlying structural condition can affect AF risk assessment."
        ),
        sources=("acc_af_2023", "cleveland_lae"),
    ),
)


@dataclass(frozen=True)
class RuleSet:
    model_id: str
    served_labels: tuple[str, ...]
    suppressed_labels: frozenset[str]
    normal_label: str = "NORM"

    @property
    def abnormal_labels(self) -> frozenset[str]:
        return frozenset(self.served_labels) - {self.normal_label}


RULE_SETS: dict[str, RuleSet] = {
    rs.model_id: rs
    for rs in (
        RuleSet(
            model_id="convnext_v1_base_clean12",
            served_labels=(
                "NORM", "SB", "STACH", "LBBB", "LQT", "AF", "AFL", "3AVB",
                "2AVB", "1AVB", "STEMI", "STE",
            ),
            suppressed_labels=frozenset(),
        ),
        RuleSet(
            model_id="convnextv2_tiny_v1img_v1",
            served_labels=(
                "NORM", "AF", "IAVB", "LBBB", "RBBB", "PAC", "PVC", "LAFB", "LAE",
            ),
            suppressed_labels=frozenset({"TInv", "LQT", "PRWP"}),
        ),
    )
}
SUPPORTED_MODEL_IDS = tuple(RULE_SETS)

# Every served label of every rule set must have a rule; fail at import, not
# in front of a patient.
_missing = {
    label
    for rs in RULE_SETS.values()
    for label in rs.served_labels
    if label not in FINDING_RULES
}
assert not _missing, f"guidance rules missing for {sorted(_missing)}"
assert all(r.reason for r in FINDING_RULES.values() if r.tier != "yellow")
# Green is reserved for a Normal read; an abnormal condition can never be Green.
assert all(
    FINDING_RULES[label].tier != "green"
    for rs in RULE_SETS.values()
    for label in rs.abnormal_labels
)
assert all(r.red_reason for r in FINDING_RULES.values() if r.red_if)
_served = frozenset(label for rs in RULE_SETS.values() for label in rs.served_labels)
assert all((combo.all_of | combo.any_of) <= _served for combo in COMBINATIONS)
assert all(combo.note.strip() for combo in COMBINATIONS)


def rule_set_for(descriptor: ModelDescriptor) -> RuleSet | None:
    """The reviewed rule set for this exact model and serving policy, if any."""
    rs = RULE_SETS.get(descriptor.id)
    if rs is None:
        return None
    if tuple(descriptor.served_labels) != rs.served_labels:
        return None
    if frozenset(descriptor.output.suppressed_labels) != rs.suppressed_labels:
        return None
    return rs


def supports(descriptor: ModelDescriptor) -> bool:
    return rule_set_for(descriptor) is not None


def config(descriptor: ModelDescriptor) -> dict:
    rs = rule_set_for(descriptor)
    return {
        "enabled": rs is not None,
        "model_id": descriptor.id if rs is not None else None,
        "model_ids": list(SUPPORTED_MODEL_IDS),
        "rule_version": RULE_VERSION,
        "supported_labels": list(rs.served_labels) if rs is not None else [],
        "urgency_levels": [
            {"id": tier, **TIER_INFO[tier]} for tier in TIERS
        ],
        "disclaimer": DISCLAIMER,
    }


def _max_tier(*tiers: UrgencyLevel) -> UrgencyLevel:
    return max(tiers, key=_RANK.__getitem__)


def _dedupe(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _rhythm_conflict(flagged: set[str]) -> str | None:
    sinus = flagged & {"SB", "STACH"}
    atrial = flagged & {"AF", "AFL"}
    if "STACH" in sinus and (len(sinus) == 2 or atrial):
        return (
            "The model flagged rhythms that cannot both be the underlying "
            "rhythm of one tracing (" + ", ".join(sorted(sinus | atrial)) + "). "
            "A clinician must read the rhythm; guidance uses the more urgent one."
        )
    return None


def _tier_steps(tier: UrgencyLevel, context_complete: bool) -> list[str]:
    if tier == "red":
        return [
            "Call 911 now — the Philippine emergency hotline. Do not wait to "
            "see whether symptoms settle.",
            "Do not drive yourself. Stay with someone if possible and follow the "
            "dispatcher's instructions.",
            "Show the ECG to the emergency team; do not delay to retake the photo "
            "or re-run the model.",
        ]
    if tier == "orange":
        return [
            "Get a medical assessment today: contact the clinician who recorded "
            "the ECG, or go to an urgent-care centre or emergency department if "
            "they cannot see the patient today.",
            "Bring the original ECG and a list of all medicines and supplements, "
            "and ask for the reading to be confirmed by a clinician.",
            "If chest pain, severe breathlessness, fainting, or stroke signs "
            "appear, this becomes Red — call emergency services.",
        ]
    if tier == "green":
        steps = [
            "No extra appointment is needed for this result alone. Keep any "
            "follow-up already planned and share the ECG with the clinician who "
            "requested it.",
        ]
    else:
        steps = [
            "Book a routine appointment with the clinician who requested the ECG, "
            "or a primary-care clinician, to confirm and interpret the result.",
        ]
    steps.append("Do not start, stop, or change medicine based on this screening output.")
    if not context_complete:
        steps.append(
            "Add the patient's symptoms and history under Patient context — "
            "they can raise the tier."
        )
    return steps


def assess(*, run_id: str, positive: list[str], display_names: dict[str, str],
           request: GuidanceRequest, model_id: str) -> GuidanceResponse:
    """Apply the reviewed rules to one stored prediction's served positives."""
    rs = RULE_SETS.get(model_id)
    if rs is None:
        raise ValueError(f"no reviewed guidance rules for model {model_id}")
    unsupported = [label for label in positive if label not in rs.served_labels]
    # A suppressed head reaching this function is a safety boundary violation,
    # not a cue to improvise clinical guidance.
    if unsupported:
        raise ValueError("unsupported or suppressed findings: " + ", ".join(unsupported))

    positive_set = set(positive)
    detected = [label for label in rs.served_labels if label in positive_set]
    abnormal = [label for label in detected if label in rs.abnormal_labels]
    flagged = set(abnormal)
    symptoms = set(request.symptoms)
    risks = set(request.risk_factors)

    def name(label: str) -> str:
        return display_names.get(label, label)

    # Green needs a positive Normal read. With nothing flagged at all the
    # model has not called the tracing normal, so a clinician should read it.
    normal_only = rs.normal_label in detected and not abnormal
    tier: UrgencyLevel = "green" if normal_only else "yellow"
    reasons: list[tuple[UrgencyLevel, str]] = []

    def raise_to(new: UrgencyLevel, reason: str) -> None:
        nonlocal tier
        tier = _max_tier(tier, new)
        reasons.append((new, reason))

    # 1) Each flagged condition's baseline tier.
    for label in abnormal:
        rule = FINDING_RULES[label]
        if rule.tier != "yellow":
            raise_to(rule.tier, rule.reason)

    cautions: list[str] = []
    if request.age_group == "under_18":
        cautions.append(PEDIATRIC_CAUTION)
        raise_to(
            "yellow",
            "A pediatric ECG needs a clinician's interpretation; the adult "
            "rules used here do not apply to children.",
        )

    # 2) Symptoms. Emergency symptoms override the model entirely.
    red_symptoms = symptoms & RED_SYMPTOMS
    if red_symptoms:
        raise_to("red", "Reported emergency warning symptoms override the ECG screening result.")
    if "fainting" in symptoms and abnormal:
        raise_to("red", "Fainting or near-fainting with an abnormal ECG flag needs emergency assessment.")
    for label in abnormal:
        rule = FINDING_RULES[label]
        if rule.red_if & symptoms:
            raise_to("red", rule.red_reason)
    if abnormal and symptoms & {"palpitations", "dizziness"}:
        raise_to("orange", "An abnormal ECG flag plus palpitations or dizziness needs same-day assessment.")
    if not abnormal and symptoms & CARDIAC_SYMPTOMS:
        raise_to("orange", "Palpitations, dizziness, or fainting need same-day assessment even without an abnormal flag.")

    # 3) History and multiplicity.
    if abnormal and risks & HEART_HISTORY:
        raise_to("orange", "Known heart failure or heart disease changes the significance of this ECG finding.")
    if not abnormal and risks & HEART_HISTORY:
        raise_to("yellow", "Known heart failure or heart disease needs its usual clinician follow-up; a Normal flag does not replace it.")
    if len(abnormal) > 1:
        raise_to("orange", "More than one abnormal condition crossed its model threshold.")

    # 4) Listed combinations.
    combination_notes: list[str] = []
    combination_sources: list[str] = []
    combination_steps: list[str] = []
    for combo in COMBINATIONS:
        if combo.matches(flagged):
            combination_notes.append(combo.note)
            combination_sources.extend(combo.sources)
            combination_steps.extend(combo.next_steps)
            if combo.tier != "yellow":
                raise_to(combo.tier, combo.note)
    conflict = _rhythm_conflict(flagged)
    if conflict:
        combination_notes.append(conflict)
    if len(abnormal) > 1:
        combination_notes.append(
            "Because several conditions were flagged, a clinician should review "
            "the complete tracing as a whole rather than treating each model "
            "output as an independent diagnosis."
        )
    if rs.normal_label in detected and abnormal:
        combination_notes.append(
            "This multi-label model flagged Normal and an abnormal condition at "
            "the same time. The abnormal condition and symptoms determine the "
            "guidance; Normal does not cancel them."
        )

    # Only the reasons that produced the final tier are shown; lower-tier
    # reasons would misstate why the result is, e.g., Red.
    final_reasons = [text for level, text in reasons if level == tier]
    if not final_reasons:
        if tier == "green":
            final_reasons = [FINDING_RULES[rs.normal_label].reason]
        elif abnormal:
            final_reasons = [
                "Only Yellow-tier conditions were flagged, with no reported "
                "symptoms or history that raise the tier."
            ]
        else:
            final_reasons = [
                "Neither Normal nor any abnormal condition crossed its model "
                "threshold, so a clinician should read the ECG."
            ]

    steps = _tier_steps(tier, request.context_complete)
    af_risk = (
        request.age_group != "under_18"
        and (request.age_group in {"65_74", "75_plus"} or bool(risks & AF_STROKE_RISKS))
    )
    if flagged & {"AF", "AFL"} and af_risk:
        steps.insert(
            1,
            "Age or reported stroke-risk factors make a formal clinician "
            "stroke-risk assessment especially important.",
        )
    steps.extend(combination_steps)

    if tier == "red":
        headline = "Emergency: call emergency services now."
    elif tier == "orange":
        headline = "Urgent: this result needs a medical assessment today."
    elif tier == "green":
        headline = "Normal ECG flagged — no extra action needed from this result."
    elif abnormal:
        headline = "Not an emergency on the information given — book a routine review."
    elif normal_only:
        headline = "Normal ECG flagged — book a routine review to have the ECG read."
    else:
        headline = "No condition flagged — book a routine review to have the ECG read."

    context_note = (
        "Guidance has been updated using the reported age group, symptoms, and risk factors."
        if request.context_complete
        else "This is provisional. Answer the context questions below because "
             "symptoms, age, and heart history can raise the tier."
    )

    finding_labels = detected or ["NONE"]
    finding_items = [
        FindingGuidance(
            finding=label,
            display_name=name(label) if label != "NONE" else "No condition flagged",
            tier=FINDING_RULES[label].tier,
            summary=FINDING_RULES[label].summary,
            next_steps=list(FINDING_RULES[label].next_steps),
            source_ids=list(FINDING_RULES[label].sources),
        )
        for label in finding_labels
    ]
    # Most urgent conditions first so their specific steps lead the list.
    finding_items.sort(key=lambda item: -_RANK[item.tier])

    source_ids = _dedupe([
        *(sid for item in finding_items for sid in item.source_ids),
        *combination_sources,
    ])
    if symptoms & {"chest_pain", "severe_shortness_of_breath"}:
        source_ids = _dedupe([*source_ids, "aha_heart_attack"])
    if "stroke_signs" in symptoms:
        source_ids = _dedupe([*source_ids, "cdc_stroke"])
    if "fainting" in symptoms:
        source_ids = _dedupe([*source_ids, "acc_syncope_2017"])

    return GuidanceResponse(
        rule_version=RULE_VERSION,
        model_id=rs.model_id,
        run_id=run_id,
        detected_findings=detected,
        abnormal_findings=abnormal,
        urgency_level=tier,
        urgency_label=TIER_INFO[tier]["label"],
        urgency_action=TIER_INFO[tier]["action"],
        urgency_description=TIER_INFO[tier]["description"],
        headline=headline,
        reasons=_dedupe(final_reasons),
        recommended_next_steps=_dedupe(steps),
        safety_net=(
            "Symptoms override this screening result. For chest pain or "
            "pressure, severe or worsening trouble breathing, stroke signs, or "
            "fainting, call 911."
        ),
        context=GuidanceContext(
            age_group=request.age_group,
            symptoms=request.symptoms,
            risk_factors=request.risk_factors,
            complete=request.context_complete,
        ),
        context_note=context_note,
        finding_guidance=finding_items,
        combination_notes=_dedupe(combination_notes),
        cautions=cautions,
        sources=[_SOURCES[source_id] for source_id in source_ids],
        disclaimer=DISCLAIMER,
    )
