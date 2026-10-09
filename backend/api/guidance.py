"""Post-prediction urgency and recommended-next-steps endpoint.

The browser supplies only patient context plus a stored run id. Findings are
read from the persisted prediction so a caller cannot inject a diagnosis, and
the run's descriptor snapshot enforces the reviewed model/suppression policy.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from backend.api.auth import owned_capture
from backend.api.state import get_state
from backend.errors import ApiError, NotFound
from backend.schemas.guidance import GuidanceRequest, GuidanceResponse
from backend.schemas.model_descriptor import ModelDescriptor
from backend.services import guidance
from backend.services import storage
from backend.services.records import RecordStore

router = APIRouter(prefix="/captures", tags=["guidance"])


def _capture(capture_id: str, request: Request) -> tuple[Path, dict]:
    return owned_capture(request, capture_id)


def _prediction(records: RecordStore, capture_id: str, record: dict,
                run_id: str) -> dict:
    # Only server-made run ids attached to this capture can be used.
    if (not storage.PREDICTION_ID_RE.fullmatch(run_id)
            or run_id not in record.get("predictions", [])):
        raise NotFound("RUN_NOT_FOUND", f"no prediction run {run_id} on this capture")
    run = records.prediction_run(capture_id, run_id)
    if run is None:
        raise NotFound("RUN_NOT_FOUND", f"no prediction run {run_id} on this capture")
    return run


@router.post("/{capture_id}/guidance", response_model=GuidanceResponse)
def clinical_guidance(capture_id: str, body: GuidanceRequest, request: Request):
    _, record = _capture(capture_id, request)
    st = get_state(request)
    prediction = _prediction(st.records, capture_id, record, body.run_id)
    try:
        descriptor = ModelDescriptor.model_validate(prediction["descriptor_snapshot"])
    except (KeyError, ValueError) as exc:
        raise ApiError(
            409,
            "GUIDANCE_RUN_INCOMPATIBLE",
            "This older prediction does not contain the model snapshot needed for safe guidance.",
        ) from exc
    if not guidance.supports(descriptor):
        raise ApiError(
            422,
            "GUIDANCE_UNSUPPORTED_MODEL",
            "Urgency guidance has reviewed rules only for "
            + ", ".join(guidance.SUPPORTED_MODEL_IDS)
            + " with their exact served labels.",
        )
    if prediction.get("model", {}).get("id") != descriptor.id:
        raise ApiError(
            409,
            "GUIDANCE_RUN_INCOMPATIBLE",
            "The prediction's model provenance does not match its descriptor snapshot.",
        )

    # Prediction positives already exclude suppressed heads. Re-filtering by
    # the descriptor snapshot is defense in depth for hand-edited/legacy data.
    positive_set = set(prediction.get("positive", []))
    positive = [label for label in descriptor.served_labels if label in positive_set]
    try:
        return guidance.assess(
            run_id=body.run_id,
            positive=positive,
            display_names=descriptor.served_display_names,
            request=body,
            model_id=descriptor.id,
        )
    except ValueError as exc:
        raise ApiError(409, "GUIDANCE_RUN_INCOMPATIBLE", str(exc)) from exc
