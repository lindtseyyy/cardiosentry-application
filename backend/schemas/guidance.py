"""Clinical decision-support schemas for post-prediction guidance.

The guidance endpoint never accepts findings from the browser.  It resolves a
stored prediction run and applies these optional patient-context answers to the
run's already-suppressed positive labels.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

AgeGroup = Literal["under_18", "18_64", "65_74", "75_plus", "unknown"]
Symptom = Literal[
    "chest_pain",
    "severe_shortness_of_breath",
    "fainting",
    "palpitations",
    "dizziness",
    "stroke_signs",
]
RiskFactor = Literal[
    "heart_failure",
    "hypertension",
    "diabetes",
    "prior_stroke_tia",
    "vascular_disease",
    "known_heart_disease",
]
# Four tiers of increasing urgency: no extra action (Normal), routine review,
# same-day assessment, emergency now.  See backend/services/guidance.py.
UrgencyLevel = Literal["green", "yellow", "orange", "red"]


class GuidanceRequest(BaseModel):
    run_id: str
    age_group: AgeGroup = "unknown"
    symptoms: list[Symptom] = Field(default_factory=list)
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    # False distinguishes "not answered yet" from an intentional empty set.
    context_complete: bool = False

    @field_validator("symptoms", "risk_factors")
    @classmethod
    def _unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("answers must not contain duplicates")
        return values


class GuidanceSource(BaseModel):
    id: str
    title: str
    organization: str
    url: str


class FindingGuidance(BaseModel):
    finding: str
    display_name: str
    # The condition's own baseline tier, before symptoms and combinations.
    tier: UrgencyLevel
    summary: str
    next_steps: list[str]
    source_ids: list[str]


class GuidanceContext(BaseModel):
    age_group: AgeGroup
    symptoms: list[Symptom]
    risk_factors: list[RiskFactor]
    complete: bool


class GuidanceResponse(BaseModel):
    rule_version: str
    model_id: str
    run_id: str
    detected_findings: list[str]
    abnormal_findings: list[str]
    urgency_level: UrgencyLevel
    urgency_label: str
    urgency_action: str
    urgency_description: str
    headline: str
    reasons: list[str]
    recommended_next_steps: list[str]
    safety_net: str
    context: GuidanceContext
    context_note: str
    finding_guidance: list[FindingGuidance]
    combination_notes: list[str]
    cautions: list[str]
    sources: list[GuidanceSource]
    disclaimer: str
