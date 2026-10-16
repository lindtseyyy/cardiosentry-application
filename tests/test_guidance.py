"""Four-tier clinical guidance: per-condition tiers, symptom and history
escalation, combinations, the model/suppression gate, and the route boundary."""
from __future__ import annotations

import secrets

import pytest
import yaml

from backend.schemas.guidance import GuidanceRequest
from backend.schemas.model_descriptor import ModelDescriptor
from backend.services import guidance
from backend.settings import APP_ROOT, settings

CLEAN12 = "convnext_v1_base_clean12"
CLEAN12_RFPN = "convnext_v1_base_rfpn_clean12"
CLEAN12_TINY_RFPN = "convnext_tiny_rfpn_clean12"
LEGACY = "convnextv2_tiny_v1img_v1"


def _assess(positive: list[str], model_id: str = CLEAN12, **kwargs):
    return guidance.assess(
        run_id="run_test",
        positive=positive,
        display_names={},
        request=GuidanceRequest(run_id="run_test", **kwargs),
        model_id=model_id,
    )


def _descriptor(model_id: str) -> ModelDescriptor:
    payload = yaml.safe_load(
        (APP_ROOT / "models" / f"{model_id}.yaml").read_text(encoding="utf-8")
    )
    return ModelDescriptor.model_validate(payload)


@pytest.mark.parametrize("model_id", [CLEAN12, CLEAN12_RFPN, CLEAN12_TINY_RFPN, LEGACY])
def test_rules_are_locked_to_reviewed_models_and_suppression_policy(model_id):
    descriptor = _descriptor(model_id)
    assert guidance.supports(descriptor)
    assert tuple(descriptor.served_labels) == guidance.RULE_SETS[model_id].served_labels

    changed = descriptor.model_copy(deep=True)
    changed.output.suppressed_labels = ["NORM"]
    assert not guidance.supports(changed)


def test_unreviewed_model_is_not_supported():
    assert not guidance.supports(_descriptor("resnet50_cbam_nat768"))
    cfg = guidance.config(_descriptor("resnet50_cbam_nat768"))
    assert cfg["enabled"] is False and cfg["model_id"] is None
    assert set(cfg["model_ids"]) == {CLEAN12, CLEAN12_RFPN, CLEAN12_TINY_RFPN, LEGACY}
    assert [t["id"] for t in cfg["urgency_levels"]] == ["green", "yellow", "orange", "red"]


@pytest.mark.parametrize(
    ("label", "tier"),
    [
        ("NORM", "green"),
        ("SB", "yellow"),
        ("STACH", "yellow"),
        ("1AVB", "yellow"),
        ("LBBB", "orange"),
        ("AF", "orange"),
        ("AFL", "orange"),
        ("LQT", "orange"),
        ("2AVB", "orange"),
        ("STE", "orange"),
        ("3AVB", "red"),
        ("STEMI", "red"),
    ],
)
def test_every_clean12_condition_has_a_baseline_tier(label: str, tier: str):
    result = _assess([label])
    assert result.urgency_level == tier
    assert result.finding_guidance[0].finding == label
    assert result.finding_guidance[0].tier == tier
    assert result.finding_guidance[0].source_ids
    assert result.reasons and all(result.reasons)


@pytest.mark.parametrize(
    ("label", "tier"),
    [("NORM", "green"), ("AF", "orange"), ("IAVB", "yellow"), ("LBBB", "orange"),
     ("RBBB", "yellow"), ("PAC", "yellow"), ("PVC", "yellow"), ("LAFB", "yellow"),
     ("LAE", "yellow")],
)
def test_legacy_model_keeps_guidance_on_the_same_tiers(label: str, tier: str):
    assert _assess([label], model_id=LEGACY).urgency_level == tier


def test_tier_steps_match_the_tier():
    assert "Call 911" in _assess(["STEMI"]).recommended_next_steps[0]
    assert "today" in _assess(["AF"]).recommended_next_steps[0]
    assert "routine appointment" in _assess(["SB"]).recommended_next_steps[0]
    assert _assess(["SB"]).urgency_action == "Book a routine clinician review"


def test_green_is_only_for_a_normal_read_with_nothing_raising_it():
    green = _assess(["NORM"])
    assert green.urgency_level == "green"
    assert green.urgency_action == "No extra action needed"
    assert "No extra appointment" in green.recommended_next_steps[0]
    assert "Normal" in green.reasons[0]
    # History that is not heart disease does not lift a Normal read.
    assert _assess(["NORM"], risk_factors=["hypertension"]).urgency_level == "green"

    # Nothing flagged is not a Normal read: a clinician should read it.
    none = _assess([])
    assert none.urgency_level == "yellow"
    assert none.finding_guidance[0].finding == "NONE"

    assert _assess(["NORM"], risk_factors=["heart_failure"]).urgency_level == "yellow"
    assert _assess(["NORM"], symptoms=["palpitations"]).urgency_level == "yellow"
    assert _assess([], symptoms=["palpitations"]).urgency_level == "orange"
    assert _assess(["NORM", "SB"]).urgency_level == "yellow"


def test_finding_actions_do_not_repeat_the_tier_action():
    result = _assess(list(guidance.RULE_SETS[CLEAN12].served_labels))
    tier_prefixes = ("Book a routine", "Get a medical assessment today", "Call 911")
    assert all(
        not step.startswith(tier_prefixes)
        for item in result.finding_guidance
        for step in item.next_steps
    )
    assert "Symptoms override" in result.safety_net
    # Most urgent conditions lead the rationale.
    assert [item.tier for item in result.finding_guidance][:2] == ["red", "red"]


@pytest.mark.parametrize(
    "symptom", ["chest_pain", "severe_shortness_of_breath", "stroke_signs"]
)
def test_emergency_symptoms_override_any_model_label(symptom: str):
    result = _assess(["NORM"], symptoms=[symptom], context_complete=True)
    assert result.urgency_level == "red"
    assert result.context.complete is True


def test_fainting_with_abnormal_finding_is_red_without_is_orange():
    assert _assess(["1AVB"], symptoms=["fainting"]).urgency_level == "red"
    assert _assess(["NORM"], symptoms=["fainting"]).urgency_level == "orange"


def test_condition_specific_symptom_escalation():
    assert _assess(["2AVB"], symptoms=["dizziness"]).urgency_level == "red"
    assert _assess(["LQT"], symptoms=["palpitations"]).urgency_level == "red"
    assert _assess(["STE"], symptoms=["dizziness"]).urgency_level == "red"
    # Palpitations with AF are expected; same-day, not an emergency on their own.
    assert _assess(["AF"], symptoms=["palpitations"]).urgency_level == "orange"
    assert _assess(["SB"], symptoms=["dizziness"]).urgency_level == "orange"


def test_history_and_multiple_findings_raise_yellow_to_orange():
    assert _assess(["1AVB"], risk_factors=["heart_failure"]).urgency_level == "orange"
    assert _assess(["STACH", "1AVB"]).urgency_level == "orange"
    # Hypertension alone does not change a Yellow conduction finding.
    assert _assess(["1AVB"], risk_factors=["hypertension"]).urgency_level == "yellow"


def test_clinically_relevant_combinations():
    infranodal = _assess(["LBBB", "2AVB"])
    assert infranodal.urgency_level == "red"
    assert any("below the AV node" in note for note in infranodal.combination_notes)

    assert _assess(["LQT", "2AVB"]).urgency_level == "red"
    assert any("torsades" in n for n in _assess(["LQT", "SB"]).combination_notes)
    assert any(
        "more than one part of the conduction system" in n
        for n in _assess(["LBBB", "1AVB"]).combination_notes
    )
    assert any(
        "usual criteria" in n and "Sgarbossa" in n
        for n in _assess(["LBBB", "STE"]).combination_notes
    )
    assert any("cannot both be" in n for n in _assess(["STACH", "AF"]).combination_notes)
    assert any("does not cancel" in n for n in _assess(["NORM", "AF"]).combination_notes)

    bifascicular = _assess(["RBBB", "LAFB"], model_id=LEGACY)
    assert bifascicular.urgency_level == "orange"
    assert any("bifascicular" in n for n in bifascicular.combination_notes)


def test_reasons_explain_only_the_final_tier():
    result = _assess(["AF", "STEMI"])
    assert result.urgency_level == "red"
    assert all("Atrial fibrillation" not in reason for reason in result.reasons)


@pytest.mark.parametrize("label", ["AF", "AFL"])
def test_atrial_arrhythmia_age_and_risk_add_stroke_risk_step(label: str):
    result = _assess(
        [label],
        age_group="75_plus",
        risk_factors=["hypertension", "prior_stroke_tia"],
        context_complete=True,
    )
    assert result.urgency_level == "orange"
    assert any("stroke-risk" in step for step in result.recommended_next_steps)
    assert result.context.age_group == "75_plus"


def test_suppressed_or_unknown_findings_cannot_receive_improvised_guidance():
    with pytest.raises(ValueError, match="unsupported or suppressed"):
        _assess(["TInv"], model_id=LEGACY)
    with pytest.raises(ValueError, match="unsupported or suppressed"):
        _assess(["RBBB"], model_id=CLEAN12)
    with pytest.raises(ValueError, match="no reviewed guidance rules"):
        _assess(["AF"], model_id="resnet50_cbam_nat768")


def test_every_source_id_resolves():
    for rule in guidance.FINDING_RULES.values():
        assert set(rule.sources) <= set(guidance._SOURCES)
    for combo in guidance.COMBINATIONS:
        assert set(combo.sources) <= set(guidance._SOURCES)


@pytest.mark.parametrize("model_id", [CLEAN12, LEGACY])
def test_lbbb_is_orange_because_newness_is_unknown(model_id):
    result = _assess(["LBBB"], model_id=model_id)
    assert result.urgency_level == "orange"
    assert any("new" in reason and "echocardiogram" in reason for reason in result.reasons)
    assert "prompt evaluation" in result.finding_guidance[0].next_steps[0]


@pytest.mark.parametrize("symptom", [None, "chest_pain", "fainting", "dizziness", "palpitations"])
def test_st_elevation_is_orange_and_escalates_to_red(symptom):
    result = _assess(["STE"], symptoms=[symptom] if symptom else [])
    assert result.urgency_level == ("red" if symptom else "orange")
    assert _assess(["STEMI"]).urgency_level == "red"


def test_second_degree_block_fainting_is_listed_red():
    rule = guidance.FINDING_RULES["2AVB"]
    assert rule.red_if == {"dizziness", "fainting"}
    result = _assess(["2AVB"], symptoms=["fainting"])
    assert result.urgency_level == "red"
    assert rule.red_reason in result.reasons


def test_second_degree_block_with_sinus_bradycardia_is_red():
    result = _assess(["2AVB", "SB"])
    assert result.urgency_level == "red"
    assert any("higher-grade" in note for note in result.combination_notes)


def test_second_degree_block_text_says_type_cannot_be_determined():
    item = _assess(["2AVB"]).finding_guidance[0]
    assert "one label for every type of second-degree block" in item.summary
    assert "(Mobitz I, Mobitz II, 2:1, high-grade)" in item.summary
    assert "cannot be determined from this result" in item.next_steps[0]
    assert "urgent pacemaker evaluation" in item.next_steps[0]


@pytest.mark.parametrize(
    ("positive", "model_id", "tier", "text"),
    [
        (["AF", "1AVB"], CLEAN12, "orange", "PR interval cannot be measured"),
        (["AF", "2AVB"], CLEAN12, "orange", "PR interval cannot be measured"),
        (["AFL", "2AVB"], CLEAN12, "orange", "flutter physiology"),
        (["AFL", "1AVB"], CLEAN12, "orange", "flutter physiology"),
        (["3AVB", "1AVB"], CLEAN12, "red", "mutually exclusive"),
        (["3AVB", "2AVB"], CLEAN12, "red", "mutually exclusive"),
        (["AF", "3AVB"], CLEAN12, "red", "Digoxin"),
        (["AF", "IAVB"], LEGACY, "orange", "PR interval cannot be measured"),
    ],
)
def test_label_conflict_notes(positive, model_id, tier, text):
    result = _assess(positive, model_id=model_id)
    assert result.urgency_level == tier
    assert any(text in note for note in result.combination_notes)


@pytest.mark.parametrize(
    ("other", "text"),
    [("LBBB", "overestimated"), ("STACH", "Bazett"), ("AF", "several beats"),
     ("AFL", "several beats")],
)
def test_long_qt_measurement_caveats(other, text):
    result = _assess(["LQT", other])
    assert result.urgency_level == "orange"
    assert any(text in note for note in result.combination_notes)
    assert any(
        source.id == "aha_ecg_qt_2009"
        and source.url == "https://www.jacc.org/doi/10.1016/j.jacc.2008.12.014"
        for source in result.sources
    )


@pytest.mark.parametrize("atrial", ["AF", "AFL"])
def test_sinus_bradycardia_with_atrial_arrhythmia_suggests_sinus_node_disease(atrial):
    result = _assess(["SB", atrial])
    assert result.urgency_level == "orange"
    assert any("sinus node disease" in note for note in result.combination_notes)
    assert not any("cannot both be" in note for note in result.combination_notes)


@pytest.mark.parametrize(
    ("positive", "labels"),
    [
        (["SB", "STACH"], "(SB, STACH)"),
        (["STACH", "AF"], "(AF, STACH)"),
        (["STACH", "AFL"], "(AFL, STACH)"),
        (["SB", "STACH", "AF"], "(AF, SB, STACH)"),
    ],
)
def test_impossible_rhythm_notes_list_only_conflicting_labels(positive, labels):
    result = _assess(positive)
    assert any(
        "cannot both be" in note and labels in note
        for note in result.combination_notes
    )
    if set(positive) >= {"SB", "AF"}:
        assert any("sinus node disease" in note for note in result.combination_notes)


@pytest.mark.parametrize(
    ("positive", "model_id", "text"),
    [
        (["LBBB", "1AVB"], CLEAN12, "echocardiogram"),
        (["AF", "LBBB"], CLEAN12, "fast, wide-complex"),
        (["AFL", "LBBB"], CLEAN12, "fast, wide-complex"),
        (["AF", "LBBB"], LEGACY, "fast, wide-complex"),
    ],
)
def test_combination_next_steps(positive, model_id, text):
    result = _assess(positive, model_id=model_id)
    assert result.urgency_level == "orange"
    assert any(text in step for step in result.recommended_next_steps)
    assert result.recommended_next_steps[:3] == guidance._tier_steps("orange", False)
    assert text in result.recommended_next_steps[-1]


def test_combination_steps_follow_tier_and_stroke_risk_steps_without_duplicates():
    result = _assess(["AF", "AFL", "LBBB", "SB", "1AVB", "AF"], age_group="75_plus")
    steps = result.recommended_next_steps
    tier_steps = guidance._tier_steps("orange", False)
    assert steps[0] == tier_steps[0]
    assert "stroke-risk assessment" in steps[1]
    assert steps[2:4] == tier_steps[1:]
    assert "echocardiogram" in steps[4]
    assert "AV-nodal-blocking medicines" in steps[5]
    assert "fast, wide-complex" in steps[6]
    assert len(steps) == len(set(steps)) == 7


@pytest.mark.parametrize("red_label", ["STEMI", "3AVB"])
@pytest.mark.parametrize("other", guidance.RULE_SETS[CLEAN12].served_labels)
def test_stemi_or_complete_block_with_anything_stays_red(red_label, other):
    assert _assess([red_label, other]).urgency_level == "red"


def test_lower_tier_notes_and_combination_steps_survive_red_escalation():
    result = _assess(["AF", "2AVB", "LBBB"], symptoms=["dizziness"])
    assert result.urgency_level == "red"
    assert any("PR interval cannot be measured" in note for note in result.combination_notes)
    assert not any("PR interval cannot be measured" in reason for reason in result.reasons)
    assert "fast, wide-complex" in result.recommended_next_steps[-1]

    long_qt = _assess(["LQT", "LBBB"], symptoms=["palpitations"])
    assert long_qt.urgency_level == "red"
    assert any("overestimated" in note for note in long_qt.combination_notes)


def test_abnormal_flag_orange_reason_excludes_fainting():
    result = _assess(["SB"], symptoms=["dizziness"])
    assert result.urgency_level == "orange"
    assert "An abnormal ECG flag plus palpitations or dizziness needs same-day assessment." in result.reasons
    assert not any("fainting" in reason for reason in result.reasons)
    assert _assess(["SB"], symptoms=["fainting"]).urgency_level == "red"
    assert _assess(["NORM"], symptoms=["fainting"]).urgency_level == "orange"


@pytest.mark.parametrize(
    ("positive", "symptoms", "tier"),
    [
        (["NORM"], [], "yellow"),
        ([], [], "yellow"),
        (["SB"], [], "yellow"),
        (["AF"], [], "orange"),
        (["NORM"], ["chest_pain"], "red"),
    ],
)
def test_under_18_adds_pediatric_caution(positive, symptoms, tier):
    result = _assess(positive, age_group="under_18", symptoms=symptoms)
    assert result.urgency_level == tier
    assert result.cautions == [guidance.PEDIATRIC_CAUTION]
    assert "not validated in children" in result.cautions[0]
    assert "pediatric clinician" in result.cautions[0] and "triage" in result.cautions[0]
    assert "60 and 100 beats/min" in result.cautions[0]
    assert result.model_dump(mode="json")["cautions"] == result.cautions
    if tier == "yellow":
        assert result.reasons == [
            "A pediatric ECG needs a clinician's interpretation; the adult rules used here do not apply to children."
        ]
        if positive == ["NORM"]:
            assert result.headline == "The model read this ECG as normal — book a routine review to have the ECG read."


def test_adult_normal_has_no_caution_and_keeps_green():
    result = _assess(["NORM"], age_group="18_64")
    assert result.cautions == []
    assert result.urgency_level == "green"
    assert _assess(["NORM"]).cautions == []


def test_under_18_does_not_add_adult_stroke_risk_step():
    result = _assess(["AF"], age_group="under_18", risk_factors=["hypertension"])
    assert result.urgency_level == "orange"
    assert result.cautions == [guidance.PEDIATRIC_CAUTION]
    assert not any("stroke-risk" in step for step in result.recommended_next_steps)


def test_normal_with_heart_history_has_normal_yellow_headline():
    result = _assess(["NORM"], risk_factors=["heart_failure"])
    assert result.urgency_level == "yellow"
    assert result.headline == "The model read this ECG as normal — book a routine review to have the ECG read."


def test_emergency_number_is_911_only():
    result = _assess(["STEMI"])
    texts = [
        *(text for info in guidance.TIER_INFO.values() for text in info.values()),
        *(step for tier in guidance.TIERS for step in guidance._tier_steps(tier, False)),
        result.safety_net,
        guidance.PEDIATRIC_CAUTION,
        guidance.PACED_CAUTION,
        guidance.SCOPE_NOTE,
        guidance.DISCLAIMER,
        guidance.RETAKE_STEP,
        *guidance.SYMPTOM_QUESTIONS.values(),
        *(
            text
            for rule in guidance.FINDING_RULES.values()
            for text in (
                rule.reason, rule.summary, rule.red_reason,
                rule.ask_first_reason, rule.known_reason, *rule.next_steps,
            )
        ),
        *(text for combo in guidance.COMBINATIONS for text in (combo.note, *combo.next_steps)),
    ]
    assert all("112" not in text and "999" not in text for text in texts)
    assert "Call 911 now" in guidance.TIER_INFO["red"]["description"]
    assert result.recommended_next_steps[0] == (
        "Call 911 now — the Philippine emergency hotline. Do not wait to see whether symptoms settle."
    )
    assert result.safety_net == guidance.SAFETY_NET
    assert "call 911." in result.safety_net
    assert result.rule_version == "four-tier-2026-10-10"


def test_combination_labels_are_served():
    served = {label for rs in guidance.RULE_SETS.values() for label in rs.served_labels}
    for combo in guidance.COMBINATIONS:
        assert (combo.all_of | combo.any_of) <= served
        assert combo.note.strip()


@pytest.mark.parametrize("risk", ["heart_failure", "known_heart_disease"])
@pytest.mark.parametrize("positive", [["NORM"], []])
def test_fainting_with_heart_history_is_red_without_abnormal_flag(positive, risk):
    result = _assess(positive, symptoms=["fainting"], risk_factors=[risk])
    assert result.urgency_level == "red"
    assert (
        "Fainting with known heart failure or structural heart disease needs "
        "emergency assessment, even with a normal ECG."
    ) in result.reasons
    assert any(source.id == "acc_syncope_2017" for source in result.sources)


@pytest.mark.parametrize("positive", [["NORM"], [], ["SB"]])
def test_fainting_with_palpitations_is_red(positive):
    result = _assess(positive, symptoms=["fainting", "palpitations"])
    assert result.urgency_level == "red"
    assert (
        "Fainting together with palpitations suggests a heart-rhythm cause "
        "and needs emergency assessment."
    ) in result.reasons


@pytest.mark.parametrize(
    "positive", [[], *([label] for label in guidance.RULE_SETS[CLEAN12].served_labels)]
)
def test_exertional_or_supine_fainting_is_red_for_any_result(positive):
    result = _assess(positive, symptoms=["fainting_exertion_or_supine"])
    assert result.urgency_level == "red"
    assert (
        "Fainting during exertion or while lying down is a high-risk feature "
        "that needs emergency assessment."
    ) in result.reasons
    assert any(source.id == "acc_syncope_2017" for source in result.sources)


@pytest.mark.parametrize("positive", [["NORM"], []])
def test_isolated_fainting_without_flag_or_history_stays_orange(positive):
    result = _assess(positive, symptoms=["fainting"])
    assert result.urgency_level == "orange"
    assert result.reasons == [
        "Fainting or near-fainting needs same-day assessment even without an abnormal flag."
    ]


@pytest.mark.parametrize("symptom", ["palpitations", "dizziness"])
def test_palpitations_or_dizziness_with_normal_read_is_yellow_within_days(symptom):
    result = _assess(["NORM"], symptoms=[symptom])
    assert result.urgency_level == "yellow"
    assert result.recommended_next_steps[0] == (
        "See the clinician who requested the ECG, or a primary-care clinician, "
        "within a few days because of the palpitations or dizziness, and ask "
        "whether heart-rhythm monitoring (for example a Holter monitor) is needed."
    )
    assert result.reasons == [
        "Palpitations or dizziness with a Normal ECG read need a clinician review "
        "within a few days, including whether heart-rhythm monitoring is needed."
    ]
    assert result.headline == (
        "The model read this ECG as normal — see a clinician within a few days about the symptoms."
    )
    no_reading = _assess([], symptoms=[symptom])
    assert no_reading.urgency_level == "orange"
    assert (
        "Palpitations or dizziness need same-day assessment because the model "
        "gave no reading of this ECG."
    ) in no_reading.reasons


def test_benign_sinus_brady_first_degree_pair_stays_yellow():
    result = _assess(["SB", "1AVB"])
    assert result.urgency_level == "yellow"
    assert (
        "Sinus bradycardia with first-degree AV block is a common, usually benign "
        "pairing (fitness, sleep, vagal tone, or medicines that slow the AV node), "
        "so on its own it stays Yellow; symptoms or heart history raise it."
    ) in result.combination_notes
    assert any("AV-nodal-blocking medicines" in step for step in result.recommended_next_steps)
    assert any("several conditions" in note for note in result.combination_notes)
    assert _assess(["NORM", "SB", "1AVB"]).urgency_level == "yellow"
    assert _assess(["SB", "1AVB"], symptoms=["dizziness"]).urgency_level == "orange"
    assert _assess(["SB", "1AVB"], risk_factors=["heart_failure"]).urgency_level == "orange"
    assert _assess(["SB", "1AVB", "STACH"]).urgency_level == "orange"


@pytest.mark.parametrize(
    ("label", "model_id"), [("AF", CLEAN12), ("AFL", CLEAN12), ("AF", LEGACY)]
)
def test_known_af_or_flutter_sets_yellow_baseline(label, model_id):
    result = _assess([label], model_id=model_id, risk_factors=["known_af_flutter"])
    assert result.urgency_level == "yellow"
    assert result.finding_guidance[0].tier == "yellow"
    assert (
        "Atrial fibrillation or flutter was reported as already known, so routine "
        "review is enough unless symptoms, history, or other findings raise the tier."
    ) in result.reasons
    assert _assess(
        [label], model_id=model_id, risk_factors=["known_af_flutter"], symptoms=["palpitations"]
    ).urgency_level == "orange"
    assert _assess(
        [label, "LBBB"], model_id=model_id, risk_factors=["known_af_flutter"]
    ).urgency_level == "orange"
    assert _assess(
        [label], model_id=model_id, risk_factors=["known_af_flutter", "heart_failure"]
    ).urgency_level == "orange"
    assert _assess(
        [label], model_id=model_id, risk_factors=["known_af_flutter"], symptoms=["chest_pain"]
    ).urgency_level == "red"
    assert _assess([label], model_id=model_id).urgency_level == "orange"
    if model_id == CLEAN12:
        assert _assess(["AF", "AFL"], risk_factors=["known_af_flutter"]).urgency_level == "orange"


@pytest.mark.parametrize("model_id", [CLEAN12, LEGACY])
def test_known_lbbb_sets_yellow_baseline(model_id):
    result = _assess(["LBBB"], model_id=model_id, risk_factors=["known_lbbb"])
    assert result.urgency_level == "yellow"
    assert result.finding_guidance[0].tier == "yellow"
    assert (
        "The LBBB was reported as already known from an earlier ECG, so routine "
        "review is enough unless symptoms, history, or other findings raise the tier."
    ) in result.reasons
    assert _assess(["LBBB"], model_id=model_id).urgency_level == "orange"
    assert _assess(
        ["LBBB"], model_id=model_id, risk_factors=["known_lbbb"], symptoms=["palpitations"]
    ).urgency_level == "orange"
    assert _assess(
        ["LBBB"], model_id=model_id, risk_factors=["known_lbbb", "heart_failure"]
    ).urgency_level == "orange"
    assert _assess(
        ["LBBB", "AF"], model_id=model_id, risk_factors=["known_lbbb", "known_af_flutter"]
    ).urgency_level == "orange"
    assert _assess(
        ["LBBB"], model_id=model_id, risk_factors=["known_lbbb"], symptoms=["chest_pain"]
    ).urgency_level == "red"


@pytest.mark.parametrize("model_id", [CLEAN12, LEGACY])
def test_pacemaker_adds_caution_and_prevents_green(model_id):
    result = _assess(["NORM"], model_id=model_id, risk_factors=["pacemaker_icd"])
    assert result.urgency_level == "yellow"
    assert result.cautions == [guidance.PACED_CAUTION]
    assert (
        "A pacemaker or ICD changes the ECG, so a clinician needs to read it; "
        "a Normal flag does not replace that."
    ) in result.reasons
    abnormal = _assess(["AF"], model_id=model_id, risk_factors=["pacemaker_icd"])
    assert abnormal.urgency_level == "orange"
    assert abnormal.cautions == [guidance.PACED_CAUTION]
    pediatric = _assess(
        ["NORM"], model_id=model_id, age_group="under_18", risk_factors=["pacemaker_icd"]
    )
    assert pediatric.urgency_level == "yellow"
    assert pediatric.cautions == [guidance.PEDIATRIC_CAUTION, guidance.PACED_CAUTION]


def test_st_elevation_asks_chest_pain_first_when_context_incomplete():
    for positive in (["STE"], ["LBBB", "STE"]):
        result = _assess(positive)
        assert result.urgency_level == "orange"
        question = result.priority_question
        assert question is not None
        assert question.symptom == "chest_pain"
        assert question.question == (
            "Does the patient have chest pain, pressure, or tightness now or recently?"
        )
        assert question.reason == (
            "The model flagged ST elevation. With chest pain this is an emergency "
            "(Red), so answer this before reading the result."
        )
        assert _assess(positive, context_complete=True).priority_question is None
        emergency = _assess(positive, symptoms=["chest_pain"])
        assert emergency.priority_question is None
        assert emergency.urgency_level == "red"
    for positive in (["STE", "STEMI"], ["STE", "3AVB"]):
        result = _assess(positive)
        assert result.urgency_level == "red"
        assert result.priority_question is None
    assert _assess(["NORM"]).priority_question is None
    assert _assess(["AF"], model_id=LEGACY).priority_question is None


@pytest.mark.parametrize(("present", "absent"), [("2AVB", "3AVB"), ("3AVB", "2AVB")])
def test_combination_two_lists_only_present_findings(present, absent):
    result = _assess(["LQT", present])
    assert result.urgency_level == "red"
    assert {item.finding for item in result.finding_guidance} == {"LQT", present}
    absent_item = _assess([absent]).finding_guidance[0]
    texts = [
        *result.recommended_next_steps,
        *(text for item in result.finding_guidance for text in (item.summary, *item.next_steps)),
    ]
    assert absent_item.summary not in texts
    assert not any(step in texts for step in absent_item.next_steps)


@pytest.mark.parametrize("atrial", ["AF", "AFL"])
def test_rhythm_conflict_note_applies_both_steps_and_higher_urgency(atrial):
    result = _assess(["STACH", atrial])
    assert result.urgency_level == "orange"
    note = next(note for note in result.combination_notes if "cannot both be" in note)
    assert "Guidance includes the steps for both findings and applies the higher urgency." in note
    assert "more urgent one" not in note
    assert {item.finding for item in result.finding_guidance} == {"STACH", atrial}
    for item in result.finding_guidance:
        assert item.next_steps == _assess([item.finding]).finding_guidance[0].next_steps
    if atrial == "AFL":
        assert "Atrial flutter with 2:1 conduction is often misread as sinus tachycardia." in note


def test_third_degree_block_recommends_echocardiogram():
    result = _assess(["3AVB"])
    assert result.urgency_level == "red"
    item = result.finding_guidance[0]
    assert "echocardiogram" in item.summary and "Class I" in item.summary
    assert any("echocardiogram" in step and "Class I" in step for step in item.next_steps)
    assert "hyperkalaemia" in item.next_steps[0]
    assert "acute inferior heart attack" in item.next_steps[0]
    assert "Lyme disease" in item.next_steps[0]
    assert (
        "Tell the emergency team whether the patient takes digoxin."
    ) in _assess(["AF", "3AVB"]).recommended_next_steps


@pytest.mark.parametrize(
    ("positive", "symptoms"),
    [(["STEMI"], []), (["3AVB"], []), (["NORM"], ["chest_pain"]), ([], ["chest_pain"])],
)
def test_red_steps_and_safety_net_include_cpr_aed(positive, symptoms):
    result = _assess(positive, symptoms=symptoms)
    assert result.urgency_level == "red"
    assert result.recommended_next_steps[2] == (
        "If the person collapses and is not breathing normally, start CPR "
        "and use an AED if one is available."
    )
    assert result.recommended_next_steps[3].startswith("Show the ECG to the emergency team")
    assert "start CPR and use an AED if one is available." in result.safety_net
    assert "palpitations followed by fainting, call 911." in result.safety_net


def test_orange_step_names_requesting_clinician_and_yellow_defines_routine():
    orange = _assess(["AF"])
    assert "clinician who requested the ECG" in orange.recommended_next_steps[0]
    assert "clinician who recorded" not in orange.recommended_next_steps[0]
    yellow = _assess(["SB"])
    assert "routine appointment within the next few weeks" in yellow.urgency_description
    assert yellow.recommended_next_steps[0] == (
        "Book a routine appointment within the next few weeks with the clinician "
        "who requested the ECG, or a primary-care clinician, to confirm and interpret the result."
    )


@pytest.mark.parametrize(
    ("context", "headline"),
    [
        ({}, "The model read this ECG as normal. No extra action needed from this result."),
        (
            {"risk_factors": ["heart_failure"]},
            "The model read this ECG as normal — book a routine review to have the ECG read.",
        ),
        (
            {"symptoms": ["dizziness"]},
            "The model read this ECG as normal — see a clinician within a few days about the symptoms.",
        ),
    ],
)
def test_normal_headline_does_not_say_flagged(context, headline):
    result = _assess(["NORM"], **context)
    assert result.headline == headline
    assert "flagged" not in result.headline


@pytest.mark.parametrize(
    ("symptoms", "tier"), [([], "yellow"), (["palpitations"], "orange"), (["chest_pain"], "red")]
)
def test_no_condition_flagged_adds_retake_step_unless_red(symptoms, tier):
    result = _assess([], symptoms=symptoms)
    assert result.urgency_level == tier
    retake = (
        "If the photo is blurred, cropped, or missing leads, retake it before relying on the result."
    )
    if tier == "red":
        assert retake not in result.recommended_next_steps
        assert any("do not delay to retake" in step for step in result.recommended_next_steps)
    else:
        assert result.recommended_next_steps[-1] == retake
    assert retake not in _assess(["NORM"]).recommended_next_steps


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("SB", "sleep apnoea"),
        ("STACH", "pulmonary embolism"),
        ("STACH", "2:1 conduction"),
        ("LQT", "calcium"),
        ("LQT", "CredibleMeds"),
        ("LQT", "does not measure"),
        ("AF", "obesity"),
        ("AF", "no longer recommended"),
        ("AFL", "Ask about heart-rate control"),
        ("STEMI", "120 minutes"),
        ("STE", "Brugada"),
        ("STE", "aneurysm"),
        ("3AVB", "Class I"),
    ],
)
def test_cardiology_review_text_refinements(label, text):
    item = _assess([label]).finding_guidance[0]
    assert any(text in value for value in (item.summary, *item.next_steps))
    if label == "STE":
        assert "60–80%" not in item.summary
        assert "most do not turn out to have a STEMI" in item.summary


@pytest.mark.parametrize("model_id", [CLEAN12, LEGACY])
@pytest.mark.parametrize("positive", [[], ["NORM"], ["AF"]])
def test_scope_note_and_disclaimer_state_model_limits(positive, model_id):
    for symptoms in ([], ["chest_pain"]):
        result = _assess(positive, model_id=model_id, symptoms=symptoms)
        assert result.scope_note == guidance.SCOPE_NOTE
        assert result.disclaimer == guidance.DISCLAIMER
        assert "model's flags and the context reported here" in result.disclaimer
        assert "heart rate, blood pressure, or the patient's current condition" in result.disclaimer


@pytest.mark.parametrize(
    ("label", "model_id"), [("AF", CLEAN12), ("AFL", CLEAN12), ("AF", LEGACY)]
)
def test_af_sources_include_esc_2024(label, model_id):
    result = _assess([label], model_id=model_id)
    assert "esc_af_2024" in result.finding_guidance[0].source_ids
    source = next(source for source in result.sources if source.id == "esc_af_2024")
    assert source.title == (
        "2024 ESC Guidelines for the management of atrial fibrillation developed "
        "in collaboration with the European Association for Cardio-Thoracic Surgery (EACTS)"
    )
    assert source.organization == "European Society of Cardiology (European Heart Journal)"
    assert source.url == "https://academic.oup.com/eurheartj/article/45/36/3314/7738779"


def test_route_uses_stored_positives_and_filters_suppressed_heads(client):
    descriptor = _descriptor(LEGACY)
    capture_id = f"2099-01-01_000000_{secrets.token_hex(3)}"
    run_id = f"run_20990101_000000_000_{LEGACY}"
    directory = settings.data_dir / "2099-01-01" / capture_id
    directory.mkdir(parents=True)
    try:
        client.app.state.csd.records.import_capture(
            {
                "capture_id": capture_id,
                "created_utc": "2099-01-01T00:00:00.000Z",
                "predictions": [run_id],
            },
            [{
                "run_id": run_id,
                "model": {"id": LEGACY},
                "descriptor_snapshot": descriptor.model_dump(mode="json"),
                # A hand-edited legacy record tries to reinsert a suppressed
                # head. The endpoint must never pass it to the rule engine.
                "positive": ["AF", "TInv"],
            }],
            [],
        )
        response = client.post(
            f"/api/captures/{capture_id}/guidance",
            json={"run_id": run_id, "context_complete": False},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["detected_findings"] == ["AF"]
        assert "TInv" not in result["detected_findings"]
        assert result["urgency_level"] == "orange"
        assert result["model_id"] == LEGACY
        assert result["priority_question"] is None
        assert result["scope_note"] == guidance.SCOPE_NOTE
    finally:
        client.delete(f"/api/captures/{capture_id}")
