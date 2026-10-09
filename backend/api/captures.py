"""Capture endpoints — the staged pipeline (plan §7.1):

    POST /api/captures                  ingest + detect + quality -> corner editor
    POST /api/captures/{id}/rectify     homography warp + preprocess -> preview
    POST /api/captures/{id}/predict     model forward -> scores
    GET  /api/captures[?page]           history list
    GET  /api/captures/{id}             full record + all prediction runs
    GET  /api/captures/{id}/files/{n}   whitelisted stage files
    PATCH /api/captures/{id}/annotation reference labels / notes
    DELETE /api/captures/{id}           record marked trashed; files -> captures/_trash/

Three calls instead of one monolith is what makes failure attribution and
model comparison achievable: predict operates on the persisted model_input.png,
so the same photograph can be re-scored by another .pt with a bit-identical
input.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from backend.api.auth import current_account, owned_capture
from backend.api.state import get_state
from backend.errors import ApiError, NotFound
from backend.schemas.capture import (AnnotationRequest, CaptureRecord,
                                     DetectionInfo, PredictRequest,
                                     RectifyRequest)
from backend.schemas.prediction import CaptureSummary, PredictionRecord, PredictionResponse
from backend.services import ingest as ing
from backend.services import preprocess as prep
from backend.services import quality as qual
from backend.services import rectify as rect
from backend.services import runner
from backend.services import storage
from backend.services.detect import detect_quad
from backend.settings import settings

router = APIRouter(prefix="/captures", tags=["captures"])
log = logging.getLogger("cardiosentry.captures")


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]


def _oriented_original(d: Path, record: dict) -> np.ndarray:
    """Re-decode the stored original in the oriented grid, per the record."""
    return ing.decode_record_original(d, record)


def _quad_norm_to_px(quad_norm, w: int, h: int) -> np.ndarray:
    pts = np.asarray([[p[0] * w, p[1] * h] for p in quad_norm], dtype=np.float64)
    return np.clip(pts, 0, [w - 1, h - 1])


def _write_preview_and_overlay(rgb: np.ndarray, d: Path, quad_px=None,
                               detection_ok: bool = True) -> None:
    h, w = rgb.shape[:2]
    scale = 1280 / max(h, w)
    if scale < 1.0:
        small = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        small = rgb
    cv2.imwrite(str(d / "preview.jpg"),
                cv2.cvtColor(small, cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, 85])
    overlay = small.copy()
    if quad_px is not None:
        pts = (np.asarray(quad_px, dtype=np.float64) * scale).astype(np.int32)
        colour = (46, 160, 67) if detection_ok else (240, 160, 32)
        cv2.polylines(overlay, [pts], True, colour, 3)
        for i, (x, y) in enumerate(pts):
            cv2.circle(overlay, (int(x), int(y)), 8, colour, -1)
            cv2.putText(overlay, f"{i + 1}", (int(x) + 12, int(y) - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)
    cv2.imwrite(str(d / "overlay.jpg"),
                cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, 85])


def _error(exc: Exception) -> None:
    """Raise ApiError through; map storage failures per §16 #14."""
    if isinstance(exc, ApiError):
        raise exc
    if isinstance(exc, OSError):
        import errno
        if exc.errno == errno.ENOSPC:
            raise ApiError(507, "STORAGE_FULL",
                           "Out of disk space — nothing was lost, free some "
                           "space and retry.") from exc
    raise exc


# --------------------------------------------------------------------- create
@router.post("", status_code=201)
async def create_capture(request: Request,
                         file: UploadFile = File(...),
                         sheet_id: str | None = Form(default=None),
                         notes: str | None = Form(default=None),
                         retake_of: str | None = Form(default=None),
                         blind_mode: bool = Form(default=False),
                         mode: str = Form(default="upload"),
                         privacy_notice: str | None = Form(default=None)):
    st = get_state(request)
    d, capture_id = storage.new_capture_dir()
    try:
        raw = await file.read(settings.max_upload_bytes + 1)
        res = ing.ingest_image(raw, file.filename or "", d / "original.jpg")
        rgb = ing.decode_oriented_rgb(res)
    except ApiError:
        raise
    except OSError as exc:
        _error(exc)

    det = detect_quad(rgb)
    q = qual.quality_original(rgb, det.quad_px, rgb.shape[1], rgb.shape[0])
    _write_preview_and_overlay(rgb, d, det.quad_px, det.success)

    record = CaptureRecord(
        capture_id=capture_id,
        created_utc=storage.utcnow(),
        owner=current_account(request).account_id,
        app={**storage.app_env_record(), "version": "0.1.0"},
        session={"sheet_id": sheet_id, "retake_of": retake_of,
                 "blind_mode": blind_mode, "notes": notes or "",
                 # Data Privacy Notice version acknowledged in the browser
                 # before this upload (RA 10173 proof of consent); None = an
                 # API/script caller that never saw the notice.
                 "privacy_notice_ack": privacy_notice},
        source={"mode": mode,
                "declared_filename": file.filename or "",
                "client_ua": request.headers.get("user-agent", "")},
        original={
            "sha256": res.sha256, "uploaded_sha256": res.uploaded_sha256,
            "bytes": res.bytes, "format": res.format,
            "width": res.width, "height": res.height,
            "oriented_width": res.oriented_width,
            "oriented_height": res.oriented_height,
            "exif": res.exif,
            "exif_orientation": res.exif_orientation,
            "exif_gps_present": res.exif_gps_present,
            "gps_stripped": res.gps_stripped,
            "orientation_applied": res.orientation_applied,
        },
        quality_original=q,
        detection=DetectionInfo(
            success=det.success, method=det.method,
            confidence=round(det.confidence, 4),
            quad_auto_px=[list(p) for p in det.quad_px],
            quad_norm=[list(p) for p in det.quad_norm],
            area_fraction=det.area_fraction, aspect_ratio=det.aspect_ratio,
            params=det.params, score_breakdown=det.score_breakdown),
        annotation={"notes": notes or ""},
    )
    try:
        st.records.create_capture(record)
    except Exception:
        log.error("Failed to store capture %s; its files remain on disk.", capture_id)
        raise

    base = f"/api/captures/{capture_id}"
    return {
        "capture_id": capture_id,
        "original": record.original,
        "detection": record.detection.model_dump(mode="json"),
        "quality": q.model_dump(mode="json"),
        "files": {"preview": f"{base}/files/preview.jpg",
                  "overlay": f"{base}/files/overlay.jpg"},
    }


# -------------------------------------------------------------------- rectify
@router.post("/{capture_id}/rectify")
def rectify_capture(capture_id: str, body: RectifyRequest, request: Request):
    st = get_state(request)
    d, record = owned_capture(request, capture_id)

    try:
        rgb = _oriented_original(d, record)
        h, w = rgb.shape[:2]
        quad_px = _quad_norm_to_px(body.quad_norm, w, h)
        auto_px = np.asarray(record["detection"]["quad_auto_px"], dtype=np.float64)
        if len({tuple(np.round(p, 2)) for p in auto_px}) == 4:
            shift = float(np.mean(np.linalg.norm(quad_px - auto_px, axis=1)))
        else:
            shift = None

        active_desc = st.active_model.descriptor
        pre_spec = active_desc.preprocess
        geometry_mode = body.geometry_mode
        r = rect.rectify(rgb, quad_px, geometry_mode=geometry_mode,
                         input_size=pre_spec.input_hw)
        cv2.imwrite(str(d / "corrected.png"),
                    cv2.cvtColor(r.corrected, cv2.COLOR_RGB2BGR))

        prep_result = prep.preprocess_corrected(
            r.corrected, input_size=pre_spec.input_hw,
            match_training_jpeg=pre_spec.match_training_jpeg,
            jpeg_quality=pre_spec.jpeg_quality,
            mean=pre_spec.normalize.mean, std=pre_spec.normalize.std,
            fit=pre_spec.fit, resample=pre_spec.resample,
            margin_px=r.margin_px)
        (d / "model_input.png").write_bytes(prep_result.model_input_png)

        gray_input = cv2.cvtColor(cv2.imread(str(d / "model_input.png")), cv2.COLOR_BGR2GRAY)
        q_after = qual.quality_model_input(r.corrected, gray_input)
    except ApiError:
        raise
    except OSError as exc:
        _error(exc)
    except Exception as exc:
        raise ApiError(500, "RECTIFY_FAILED",
                       f"Rectification failed: {exc}") from exc

    correction = {
        "quad_final_px": [list(map(float, p)) for p in quad_px],
        "quad_auto_px": record["detection"]["quad_auto_px"],
        "corners_manually_adjusted": body.source == "manual",
        "mean_corner_shift_px": round(shift, 2) if shift is not None else None,
        "source": body.source,
        "geometry_mode": geometry_mode,
        "homography": r.homography,
        "warp_interpolation": r.warp_interpolation,
        "canvas_px": list(r.canvas_px),
        "margin_px": r.margin_px,
        "paper_fill_rgb": r.paper_fill_rgb,
        "corrected_px": list(r.corrected_px),
        "est_px_per_mm_original": r.est_px_per_mm_original,
        "scale_factor_to_input": r.scale_factor_to_input,
    }
    preprocess = {
        "input_size": list(pre_spec.input_hw),          # [height, width]
        "resample": pre_spec.resample,
        "fit": pre_spec.fit,
        "margin_cropped_px": r.margin_px if pre_spec.fit == "height_pad" else 0,
        "match_training_jpeg": pre_spec.match_training_jpeg,
        "jpeg_quality": pre_spec.jpeg_quality,
        "normalize": {"mean": pre_spec.normalize.mean, "std": pre_spec.normalize.std},
        "tensor_shape": list(prep_result.tensor.shape),
        "tensor_dtype": str(prep_result.tensor.dtype),
        "tensor_sha256": prep_result.tensor_sha256,
        "preprocess_ms": round(prep_result.ms, 1),
    }

    def mutate(current: dict) -> None:
        current["correction"] = correction
        current["preprocess"] = preprocess
        current["quality_model_input"] = q_after.model_dump(mode="json")

    st.records.update_capture(capture_id, mutate)

    base = f"/api/captures/{capture_id}"
    return {
        "capture_id": capture_id,
        "corrected_px": list(r.corrected_px),
        "geometry_mode": geometry_mode,
        "mean_corner_shift_px": correction["mean_corner_shift_px"],
        "quality": q_after.model_dump(mode="json"),
        "preprocess": preprocess,
        "files": {
            "corrected": f"{base}/files/corrected.png",
            "model_input": f"{base}/files/model_input.png",
        },
    }


# ------------------------------------------------------------------- predict
@router.post("/{capture_id}/predict")
def predict_capture(capture_id: str, body: PredictRequest, request: Request):
    st = get_state(request)
    d, record = owned_capture(request, capture_id)

    thresholds_override = None
    if body.thresholds:
        lm_any = st.model(body.model_id)
        served_labels = lm_any.descriptor.served_labels
        missing = [l for l in served_labels if l not in body.thresholds]
        if missing:
            raise ApiError(422, "INCOMPLETE_THRESHOLDS",
                           "thresholds must cover every label of the model: "
                           + ", ".join(missing) + " missing")
        for label in body.thresholds:
            if label not in served_labels:
                raise ApiError(422, "UNKNOWN_LABEL",
                               f"unknown label {label!r}")
            if not 0.0 <= body.thresholds[label] <= 1.0:
                raise ApiError(422, "THRESHOLD_OUT_OF_RANGE",
                               "thresholds must be within [0, 1]")
        thresholds_override = body.thresholds

    lm = st.model(body.model_id)
    model_input = d / "model_input.png"
    # model_input.png was built for whichever model was active at rectify
    # time. Records from before `fit` existed were all stretched.
    stored_fit = (record.get("preprocess") or {}).get("fit", "stretch")
    if stored_fit != lm.descriptor.preprocess.fit:
        raise ApiError(409, "PREPROCESS_MISMATCH",
                       f"this capture's model input was built with fit="
                       f"{stored_fit!r}, but {lm.id} expects fit="
                       f"{lm.descriptor.preprocess.fit!r}. Re-run the corner "
                       "step with this model active, or use "
                       "scripts/reprocess.py --model " + lm.id + ".")
    try:
        pr = runner.predict(lm, model_input, thresholds_override=thresholds_override)
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(500, "INFERENCE_FAILED",
                       "Inference failed — the capture was saved; you can "
                       "retry.") from exc

    run_id = f"run_{_run_stamp()}_{lm.id}"
    created_utc = storage.utcnow()
    rec = PredictionRecord(
        run_id=run_id, capture_id=capture_id, model=lm.run_info(),
        descriptor_snapshot=lm.descriptor,
        scores=pr.scores, logits=pr.logits, thresholds=pr.thresholds,
        threshold_source=pr.threshold_source, positive=pr.positive,
        timing_ms=pr.timing_ms, created_utc=created_utc,
        model_input_sha256=pr.model_input_sha256,
        env=storage.app_env_record())
    st.records.add_prediction(capture_id, rec.model_dump(mode="json"))

    return PredictionResponse(
        run_id=run_id, capture_id=capture_id, model=rec.model,
        labels=lm.descriptor.served_labels,
        display_names=lm.descriptor.served_display_names,
        scores=pr.scores, logits=pr.logits, thresholds=pr.thresholds,
        threshold_source=pr.threshold_source, positive=pr.positive,
        timing_ms=pr.timing_ms, created_utc=created_utc,
        model_input_sha256=pr.model_input_sha256).model_dump(mode="json")


# ---------------------------------------------------------------------- reads
@router.get("")
def list_captures(request: Request, page: int = 1):
    if page < 1:
        raise ApiError(422, "BAD_PAGE", "page must be >= 1")
    st = get_state(request)
    account = current_account(request)
    size = settings.captures_page_size
    start = (page - 1) * size
    total, records_page = st.records.list_owned(account.account_id, size, start)
    out: list[CaptureSummary] = []
    for rec, runs in records_page:
        latest_pos, latest_model = [], None
        for run in runs:
            latest_pos = run.get("positive", [])
            latest_model = run.get("model", {}).get("id")
        cid = rec["capture_id"]
        try:
            has_preview = (storage.capture_dir(cid) / "preview.jpg").is_file()
        except KeyError:
            has_preview = False
        out.append(CaptureSummary(
            capture_id=rec["capture_id"],
            created_utc=rec["created_utc"],
            sheet_id=rec.get("session", {}).get("sheet_id"),
            thumbnail_url=(f"/api/captures/{cid}/files/preview.jpg"
                           if has_preview else None),
            has_correction=bool(rec.get("correction")),
            latest_model_id=latest_model,
            latest_positive=latest_pos,
            quality_level=(rec.get("quality_model_input") or {}).get("level", "ok"),
        ).model_dump(mode="json"))
    return {"captures": out, "page": page, "total": total,
            "has_more": start + size < total}


@router.get("/{capture_id}")
def get_capture(capture_id: str, request: Request):
    _, rec = owned_capture(request, capture_id)
    st = get_state(request)
    rec["prediction_runs"] = st.records.prediction_runs(
        capture_id, rec.get("predictions", []))
    return rec


@router.get("/{capture_id}/files/{name}")
def get_file(capture_id: str, name: str, request: Request):
    d, _ = owned_capture(request, capture_id)
    if name not in storage.FILE_WHITELIST:
        raise ApiError(404, "UNKNOWN_FILE",
                       f"whitelisted files only: {', '.join(storage.FILE_WHITELIST)}")
    p = (d / name).resolve()
    if not p.is_file() or d.resolve() not in p.parents:
        raise NotFound("UNKNOWN_FILE", "no such file")
    media = "image/jpeg" if name.endswith(".jpg") else "image/png"
    return FileResponse(p, media_type=media)


@router.patch("/{capture_id}/annotation")
def patch_annotation(capture_id: str, body: AnnotationRequest, request: Request):
    owned_capture(request, capture_id)
    st = get_state(request)

    def mutate(rec: dict) -> None:
        ann = rec.setdefault("annotation", {})
        if body.reference_labels is not None:
            if not ann.get("labels_entered_utc"):
                ann["labels_entered_utc"] = storage.utcnow()
            ann["reference_labels"] = body.reference_labels
        if body.labels_entered_before_prediction is not None:
            ann["labels_entered_before_prediction"] = body.labels_entered_before_prediction
        for k in ("truth_source", "notes", "sheet_id", "device_vendor", "paper_size"):
            v = getattr(body, k)
            if v is not None:
                target = "session" if k == "sheet_id" else "annotation"
                rec.setdefault(target, {})[k] = v

    rec = st.records.update_capture(capture_id, mutate)
    return rec


@router.delete("/{capture_id}")
def delete_capture(capture_id: str, request: Request):
    owned_capture(request, capture_id)
    st = get_state(request)
    try:
        trash = st.records.trash_capture(capture_id)
    except KeyError:
        raise NotFound("CAPTURE_NOT_FOUND", f"no capture {capture_id}")
    return {"capture_id": capture_id, "trashed": str(trash)}
