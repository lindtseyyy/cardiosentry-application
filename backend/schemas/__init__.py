"""Pydantic schemas for API requests/responses and persisted records."""
from __future__ import annotations

from .auth import AccountUpdateRequest, CredentialsRequest, UserResponse
from .capture import (Annotation, AnnotationRequest, CaptureRecord, CorrectionInfo,
                      DetectionInfo, PredictRequest, QualityMetrics, RectifyRequest)
from .guidance import (FindingGuidance, GuidanceContext, GuidanceRequest,
                       GuidanceResponse, GuidanceSource)
from .model_descriptor import (ArchitectureSpec, ModelDescriptor, NormalizeSpec,
                               PreprocessSpec, RuntimeSpec, ThresholdSpec)
from .prediction import (CaptureSummary, ModelRunInfo, PredictionRecord,
                         PredictionResponse)

__all__ = [
    "AccountUpdateRequest", "Annotation", "AnnotationRequest", "ArchitectureSpec", "CaptureRecord",
    "CaptureSummary", "CorrectionInfo", "CredentialsRequest", "DetectionInfo", "FindingGuidance",
    "GuidanceContext", "GuidanceRequest", "GuidanceResponse", "GuidanceSource",
    "ModelDescriptor", "ModelRunInfo", "NormalizeSpec", "PredictRequest",
    "PredictionRecord", "PredictionResponse", "PreprocessSpec", "QualityMetrics",
    "RectifyRequest", "RuntimeSpec", "ThresholdSpec", "UserResponse",
]
