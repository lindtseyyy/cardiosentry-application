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


@pytest.mark.parametrize("model_id", [CLEAN12, LEGACY])
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
    assert set(cfg["model_ids"]) == {CLEAN12, LEGACY}
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
    assert _assess(["NORM"], symptoms=["palpitations"]).urgency_level == "orange"
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
    assert _assess(["SB", "1AVB"]).urgency_level == "orange"
    # Hypertension alone does not change a Yellow conduction finding.
    assert _assess(["1AVB"], risk_factors=["hypertension"]).urgency_level == "yellow"


def test_clinically_relevant_combinations():
    infranodal = _assess(["LBBB", "2AVB"])
    assert infranodal.urgency_level == "red"
    assert any("below the AV node" in note for note in infranodal.combination_notes)

    assert _assess(["LQT", "2AVB"]).urgency_level == "red"
    assert any("torsades" in n for n in _assess(["LQT", "SB"]).combination_notes)
    assert any("extensive conduction" in n for n in _assess(["LBBB", "1AVB"]).combination_notes)
    assert any("usual criteria" in n for n in _assess(["LBBB", "STE"]).combination_notes)
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
    [("LBBB", "overestimated"), ("STACH", "Bazett"), ("AF", "several beats")],
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
        (["SB", "1AVB"], CLEAN12, "beta-blockers, calcium-channel blockers, and digoxin"),
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
    assert "AV-nodal-blocking medicines" in steps[4]
    assert "fast, wide-complex" in steps[5]
    assert len(steps) == len(set(steps)) == 6


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
    assert "children" in result.cautions[0] and "triage" in result.cautions[0]
    assert result.model_dump(mode="json")["cautions"] == result.cautions
    if tier == "yellow":
        assert result.reasons == [
            "A pediatric ECG needs a clinician's interpretation; the adult rules used here do not apply to children."
        ]
        if positive == ["NORM"]:
            assert result.headline == "Normal ECG flagged — book a routine review to have the ECG read."


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
    assert result.headline == "Normal ECG flagged — book a routine review to have the ECG read."


def test_emergency_number_is_911_only():
    result = _assess(["STEMI"])
    texts = [
        *(text for info in guidance.TIER_INFO.values() for text in info.values()),
        *(step for tier in guidance.TIERS for step in guidance._tier_steps(tier, False)),
        result.safety_net,
        guidance.PEDIATRIC_CAUTION,
        *(
            text
            for rule in guidance.FINDING_RULES.values()
            for text in (rule.reason, rule.summary, rule.red_reason, *rule.next_steps)
        ),
        *(text for combo in guidance.COMBINATIONS for text in (combo.note, *combo.next_steps)),
    ]
    assert all("112" not in text and "999" not in text for text in texts)
    assert "Call 911 now" in guidance.TIER_INFO["red"]["description"]
    assert result.recommended_next_steps[0] == (
        "Call 911 now — the Philippine emergency hotline. Do not wait to see whether symptoms settle."
    )
    assert result.safety_net.endswith("call 911.")
    assert result.rule_version == "four-tier-2026-10-08"


def test_combination_labels_are_served():
    served = {label for rs in guidance.RULE_SETS.values() for label in rs.served_labels}
    for combo in guidance.COMBINATIONS:
        assert (combo.all_of | combo.any_of) <= served
        assert combo.note.strip()


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
    finally:
        client.delete(f"/api/captures/{capture_id}")
