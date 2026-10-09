# CardioSentry system flowcharts

This folder contains the paper-ready flowchart set for the CardioSentry web
application. Open `cardiosentry-system-flowcharts.html` in a browser for the
editable source view, or use the generated PDF/PNG files for insertion into a
paper.

## Scope and implementation status

The diagrams distinguish what the application does today from the remaining
model integration work:

- **Solid border — implemented:** photo ingest, OpenCV paper detection,
  quality warnings, manual corner review, homography rectification, canonical
  preprocessing, multi-label inference, persisted records, and user-requested
  Grad-CAM.
- **Purple dashed border — integration pending:** the trained ConvNeXt-V2 Tiny
  + final-stage CBAM checkpoint exists in
  `prototype-results/NEW_convnextv2_tiny_cbam_v1img_clean_seed42/`, but the
  application currently points `models/active.yaml` to the bare
  `convnextv2_tiny_v1img_v1` model and has no serving descriptor/wrapper for
  the CBAM checkpoint.
- **Solid border — implemented:** the post-prediction urgency and recommendation
  layer is implemented for the current model's nine served labels. It reads a
  stored prediction, asks optional age/symptom/risk questions, applies emergency
  symptom overrides and combination modifiers, and returns sourced guidance.

The model page shows the requested ConvNeXt-V2 + CBAM target path because that
is the architecture described in the paper text and represented by the trained
checkpoint. It also states the current serving gap so the diagram does not
misrepresent the running application.

## Key facts represented

- The model input is an RGB tensor of shape `[1, 3, 768, 1024]` after PIL
  bicubic resizing and ImageNet normalization.
- The CBAM checkpoint has 12 independent sigmoid heads. The application policy
  currently serves 9 (`NORM`, `AF`, `IAVB`, `LBBB`, `RBBB`, `PAC`, `PVC`,
  `LAFB`, `LAE`) and suppresses `TInv`, `LQT`, and `PRWP` at the serving
  boundary.
- Grad-CAM is post-hoc and user-requested. It explains a selected positive
  abnormal label; it does not change the prediction.
- Image quality warnings never block inference.
- A model score is a research output, not a diagnosis or a calibrated
  probability on real phone photographs.

## Safety basis for the urgency layer

Urgency is driven first by reported symptoms, not by a model label or the size
of its score. Severe chest pain/pressure, severe or worsening trouble breathing,
or stroke signs route directly to local emergency services; fainting with an
abnormal served finding does too. This follows current
[American Heart Association arrhythmia guidance](https://www.heart.org/en/health-topics/arrhythmia/symptoms-diagnosis--monitoring-of-arrhythmia)
and [CDC stroke guidance](https://www.cdc.gov/stroke/signs-symptoms/index.html).
Each abnormal model flag is then looked up in the model-specific versioned rule
table documented in [`../clinical-guidance.md`](../clinical-guidance.md). The
highest priority among the flagged conditions is used. The endpoint refuses a
different model or suppression policy rather than improvising. An abnormal flag
can recommend review and confirmation with a clinician-interpreted ECG, but it
must not independently diagnose a condition, assign treatment, or interpret a
larger model score as greater clinical severity.
