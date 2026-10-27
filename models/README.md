# Models directory

A model = **one `.pt` + one YAML descriptor** — the model is data, not code.
Swapping models is adding two files and pointing `active.yaml` (or
`CARDIOSENTRY_ACTIVE_MODEL`) at the new descriptor. Zero application-code
changes.

## Layout

```
models/
├── active.yaml -> convnext_tiny_rfpn_clean12_aug.yaml  # which model the app serves
├── convnext_tiny_rfpn_clean12_aug.yaml    # HEEDB clean12 + augmented ConvNeXt-V1 Tiny + RFPN, 12 heads
├── convnext_tiny_rfpn_clean12.yaml        # HEEDB clean12 ConvNeXt-V1 Tiny + RFPN, 12 heads
├── convnext_v1_base_rfpn_clean12.yaml     # HEEDB clean12 ConvNeXt-V1 Base + RFPN, 12 heads
├── convnext_v1_base_clean12.yaml          # HEEDB clean12 ConvNeXt-V1 Base, 12 heads
├── convnextv2_tiny_v1img_v1.yaml          # V1 clean-image model, 12 heads / 9 served
├── efficientnetv2_s_nat768.yaml           # round-3 PLAIN baseline, 768x1024
├── efficientnetv2_s_cbam_nat768.yaml      # round-3, same geometry + CBAM
├── resnet50_cbam_nat768.yaml              # round-3, same geometry, other backbone
├── resnet50_hires.yaml                    # round-2 control, 768px square
├── resnet50_dual.yaml                     # round-2 dual-stream 384+768
├── resnet50_v1.yaml                       # round-1, 384px, tensor call style
├── gates/                                 # ECG / not-ECG gates (§ECG gate), not diagnostic models
│   ├── convnext_tiny_rfpn_ecg_gate_v1.yaml  # default: learned gate head
│   └── ocr_lead_labels_v1.yaml            # OCR of the printed lead labels (alternative)
└── weights/
    ├── convnext_tiny_rfpn_clean12_aug_inference.pt  # 120 MB inference export
    ├── convnext_tiny_rfpn_clean12_inference.pt  # 120 MB inference export
    ├── convnext_v1_base_rfpn_clean12_inference.pt  # 360 MB inference export
    ├── convnext_tiny_rfpn_ecg_gate_v1.pt  # 121 MB: Tiny RFPN export + gate head
    ├── convnext_v1_base_clean12_best.pt   # 1.4 GB full training checkpoint
    ├── convnextv2_tiny_v1img_v1.pt
    ├── efficientnetv2_s_nat768.pt
    ├── resnet50_cbam_nat768.pt
    ├── efficientnetv2_s_cbam_nat768.pt
    ├── resnet50_hires.pt
    ├── resnet50_dual.pt
    └── resnet50_v1.pt
```

## Where the `.pt` files come from

The checkpoints are the training outputs in the research tree; copy them here:

```bash
# clean12 + augmented ConvNeXt-V1 Tiny + RFPN: inference.pt of MyDrive/CardioSentry/new_runs/
#   convnext_tiny_v1_rfpn_clean12_aug_colab_a100_seed42
cp ../prototype-results/new_runs/convnext_tiny_v1_rfpn_clean12_aug_colab_a100_seed42/convnext_tiny_rfpn/inference.pt \
   weights/convnext_tiny_rfpn_clean12_aug_inference.pt
# clean12 ConvNeXt-V1 Tiny + RFPN: inference.pt of MyDrive/CardioSentry/new_runs/
#   convnext_tiny_v1_rfpn_clean12_colab_a100_seed42
cp ../prototype-results/new_runs/convnext_tiny_v1_rfpn_clean12_colab_a100_seed42/convnext_tiny_rfpn/inference.pt \
   weights/convnext_tiny_rfpn_clean12_inference.pt
# clean12 ConvNeXt-V1 Base + RFPN: inference.pt of MyDrive/CardioSentry/new_runs/
#   convnext_v1_base_rfpn_clean12_colab_a100_seed42
cp ../prototype-results/convnext_v1_base_rfpn_clean12_colab_a100_seed42/inference.pt \
   weights/convnext_v1_base_rfpn_clean12_inference.pt
# clean12 ConvNeXt-V1 Base: best.pt of MyDrive/CardioSentry/new_runs/
#   convnextv1_base_clean12_a100_seed42 (= s3://cardiosentry/runs/
#   convnext_v1_base_clean12_g6e2xlarge_seed42/best.pt)
cp <that best.pt> weights/convnext_v1_base_clean12_best.pt
cp ../prototype-results/NEW_convnext_v2_tiny_V1/best.pt \
   weights/convnextv2_tiny_v1img_v1.pt
cp "../prototype-results/efficientnetv2_s@nat768/weights/best.pt" \
   weights/efficientnetv2_s_nat768.pt
cp "../prototype-results/resnet50_cbam@nat768/weights/best.pt" \
   weights/resnet50_cbam_nat768.pt
cp "../prototype-results/efficientnetv2_s_cbam@nat768/weights/best.pt" \
   weights/efficientnetv2_s_cbam_nat768.pt
cp ../prototype-results/hybrid_v1/resnet50_hires/weights/best.pt weights/resnet50_hires.pt
cp ../prototype-results/hybrid_v1/resnet50_dual/weights/best.pt  weights/resnet50_dual.pt
cp ../prototype-results/v1/resnet50/weights/best.pt              weights/resnet50_v1.pt
```

`weights/` is gitignored (the files are 100–500 MB training artifacts). The
descriptors pin each checkpoint with `expected_sha256` and
`expected_protocol_fingerprint`, so a swapped or corrupted `.pt` **refuses to
start** instead of silently invalidating every recorded prediction (§16 #18).

Full training checkpoints are fine as-is: the runner memory-maps every `.pt`,
so a clean12 `best.pt` (raw + EMA weights, optimizer, RNG state) costs only the
weights it serves, and when the blob records `selected_weight_source` the
runner serves that state_dict (`ema` for the clean12 run), not `model`. A
clean12 `inference.pt` export (no `optimizer`, no `model_ema`) already holds the
selected weights under `model`; its `selected_weight_source` is provenance.

## The descriptor format

See `backend/schemas/model_descriptor.py` (the pydantic schema that validates
each YAML at startup) and `resnet50_cbam_nat768.yaml` for the annotated
example. Key fields:

- `architecture.module` — vendored arch package (`arch.hybrids_v2` /
  `arch.hybrids_v1` / `arch.runs_v1`, under `backend/arch/`); `registry_key` —
  key in its REGISTRY.
- `architecture.call_style` — `view_dict` (round-2: `model({768: t})`) or
  `tensor` (round-1 and round-3: `model(t)`).
- `architecture.views` — per-view input geometry. An int is a square view
  (`[384, 768]` = two square views); a pair is `[height, width]`
  (`[[768, 1024]]`). `view_dict` keys its input dict by a single integer, so
  that call style accepts square views only — the schema refuses the
  combination rather than silently transposing something.
- `labels` — MUST match the checkpoint's head order (the active V1 run uses
  `[NORM, AF, IAVB, LBBB, RBBB, PAC, PVC, LAFB, LAE, TInv, LQT, PRWP]`);
  `display_names` are the UI strings.
- `output.suppressed_labels` — reversible serving-only suppression. These
  labels remain in `labels`, the model still loads its complete head with
  `strict=True`, and removing them from this list returns them in future API/UI
  results. Suppressed labels do not appear in scores, thresholds, positives,
  reference-label controls, or new explanations.
- `thresholds.source` — `checkpoint` reads the frozen per-class thresholds
  from the `.pt` (default; startup refuses if absent); `explicit` takes the
  values from the descriptor.
- `preprocess.fit` — `stretch` (default) resizes the whole rectified sheet,
  margin included; `height_pad` (clean12) crops the rectify margin, fits the
  sheet to the input height keeping its aspect and pads the sides with the
  paper colour, exactly like the clean12 render (`resample: pil_lanczos`).
  Each capture records its `fit`, and predicting with a model of the other fit
  is refused (409) rather than scoring pixels it was not trained on.
- `preprocess` — the training input chain parameters; keep them at the
  training values unless you are deliberately running the experiment those
  flags exist for. `input_size` is the one that decides the geometry: `768`
  (square) or `[768, 1024]` (**height, width** — torch order, the same order the
  research code's `config.IMG_SIZE` uses and the opposite of PIL's `(w, h)`).
  Transposing it produces a portrait ECG that still scores and is silently
  wrong.
- `verify` — the startup self-check's inputs for THIS checkpoint.
  `expected_scores` is the path (relative to the app root) of the run's own
  stored score vector for `tests/fixtures/corpus_sheet.jpg`; pinning it here is
  what keeps a model swap from leaving the check comparing the newly active
  model against another run's numbers. `score_tolerance` overrides
  `settings.verify_score_tolerance` (2e-3). Raise it only against a
  measurement: the default is a bound in PROBABILITY space, so what it permits
  depends on where a run's fixture scores sit on the sigmoid — 2e-3 at p=0.999
  allows a ~2.0 logit shift, at p=0.93 only ~0.03.
- `explain` — attribution defaults for this checkpoint.
  `target_layer` is the Grad-CAM feature map as a dotted module path; `null`
  auto-picks the last 4-D feature map, which is right for every checkpoint
  here (`GET /api/models/<id>/layers` lists the candidates and what auto
  chose). `header_box` is the printed ID/Age/Sex rectangle as
  `[x0, y0, x1, y1]` fractions — **no pixels are altered**, it is the region
  every attribution map is scored against. `header_redacted_in_training` says
  whether this run trained with that block painted out; see below for why that
  changes how a header-heavy map should be read.

## ECG gate

`gates/<id>.yaml` (schema: `backend/schemas/ecg_gate.py`) describes the gate run
on every upload before a capture is created (`services/ecg_gate.py`). Setting
`CARDIOSENTRY_ECG_GATE` names the id; **that one setting switches gates**
(default `convnext_tiny_rfpn_ecg_gate_v1`; empty = off). The descriptor's `kind` picks the
implementation. `registry.discover` only scans `models/*.yaml`, so gates never
appear in `/api/models` and cannot be made active. Rejected = `422 NOT_AN_ECG`,
folder removed, no record; accepted captures store `record.ecg_gate`.

| id | `kind` | passes | cost |
|---|---|---|---|
| `ocr_lead_labels_v1` | `ocr_lead_labels` | ≥ 4 of the 9 labels aVR, aVL, aVF, V1–V6 read | Tesseract binary; ~2–4 s accept, ≤ ~7 s reject |
| `convnext_tiny_rfpn_ecg_gate_v1` *(default)* | `learned` | P(ECG) ≥ 0.5 | 121 MB `.pt`, ~0.1 GB RAM, ~3 s |

### `ocr_lead_labels_v1` (services/ecg_gate_ocr.py)

Replaced the learned gate as default on 2026-10-15 because the learned gate
accepted EEG printouts (grid + traces, no lead labels); the learned gate was
made default again on 2026-10-19.

- **Engine:** the `tesseract` CLI (5.3.4 here; `apt install tesseract-ocr`),
  called directly with `OMP_THREAD_LIMIT=1` — no Python OCR package. Startup
  fails if the binary is missing or its warm-up call fails.
- **Chain:** resize the oriented upload to 2400 px max side (small images are
  upscaled; the labels need ~20 px height), then each `cleanup` pass keeps only
  character-sized ink blobs (ink = darker than 0.55 × local paper brightness),
  so traces, grid and shading drop out; Tesseract `--psm 11` with
  `char_whitelist` reads what is left. Pass 1 uses `max(R,G,B)` (a red/pink grid
  vanishes); pass 2 uses `min(R,G,B)` + grid-line removal for black-grid scans.
  Both start at once; pass 2 is only waited for when pass 1 falls short.
- **Rule:** `score` = distinct `counted_leads` read, accepted at
  `score >= min_leads`. I, II and III are read and reported in `leads_found` but
  not counted: "I" was read on 65 of 131 non-ECG images.
- **Why 4, not 9 (2026-10-15, ecg_gate_v1 test split + 30 synthetic EEG
  sheets; dataset images are ≤ 1600 px, so phone photos read better):**

  | images | n | median counted | max counted | accepted at 4 |
  |---|---|---|---|---|
  | clean12 renders | 25 | 9 | 9 | 25 |
  | MEETI | 25 | 8 | 9 | 25 |
  | ECG-Image-Database D1 | 25 | 7 | 9 | 19 |
  | ECG-Image-Database D0 (black-grid scans) | 25 | 2 | 9 | 8 |
  | ECG-Image-Database D2 (limb-lead-only pages) | 25 | 3 | 6 | 3 |
  | non-ECG: COCO, RVL-CDIP, ChartQA, CORD, look-alikes | 100 | 0 | 2 | 0 |
  | synthetic EEG (10-20 montages, half photographed) | 30 | 0 | 1 | 0 |

  Non-ECG never read more than 2, so 4 leaves a margin of 2. At 9, only 29% of
  the ECGs passed. App fixtures: `corpus_sheet` 9, `photo_clean` 7, `photo_dark`
  8, `photo_tilted` 8 accepted; `photo_small` (sheet ~10% of the frame) and
  `no_paper` 0, rejected.
- **Known misses:** black-grid scans whose labels touch the grid, pages that
  print only some leads, far-away photos (labels too small to read).

### `convnext_tiny_rfpn_ecg_gate_v1` (learned)

- **Weights:** `inference_with_gate.pt` from
  `prototype-results/new_runs/convnext_tiny_v1_rfpn_clean12_ecg_gate_v1_seed42/`
  — the clean12 ConvNeXt-V1 Tiny + RFPN export (fingerprint `177e77611da26805`,
  `model` untouched) plus `gate_head`, `gate_head_spec` and `gate_threshold`.
  Both parts load `strict=True`; `expected_sha256` and
  `expected_protocol_fingerprint` pin the file like a model descriptor. A
  separate file from the diagnostic `convnext_tiny_rfpn_clean12` weights.
- **Architecture:** `arch.convnext_v1_rfpn_clean12` / `convnext_tiny_rfpn_clean12`.
  The gate reads the pooled stage-4 pre-logits (768) + pooled FPN P3–P5 (3×256);
  the 12 diagnostic logits are not computed.
- **Input:** the oriented upload, LANCZOS thumbnail to 1600 px, JPEG q95 (the
  gate dataset's build), then `fit_height_pad` to 768×1024 — the run's `fit`
  geometry. Its `rectify` geometry is not served.
- **Threshold:** `threshold.source: checkpoint` reads `gate_threshold` (0.5). The
  run's recall-0.99 rule chose 0.9746, which rejected 8 real-ECG validation rows
  while every non-ECG scored ≤ 0.061; 0.5 has no validation/test errors.
- **Parity (2026-10-15):** on 20 clean12 renders, including the 4 lowest-scoring,
  the app reproduces the run's stored `fit` probabilities within 9.3e-4 (CPU fp32
  vs the run's GPU eval). Test fixtures: every `photo_*` except `photo_small.jpg`
  scores 1.0; `photo_small.jpg` (sheet ~10% of the frame) 0.016 and
  `no_paper.jpg` 1e-5 are rejected.
- **Known miss:** EEG printouts pass (reported 2026-10-15; its training set had
  no EEG negatives).
- **Not measured:** real-world non-ECG phone photos; the gate dataset's negatives
  are COCO, RVL-CDIP, ChartQA, CORD and synthetic look-alikes.

## The header is not redacted at serving time

The round-3 corpus was built with the printed ID/Age/Sex block painted out
(`hybrids_v2` `REDACT_BOX = [0.10, 0.02, 0.30, 0.18]`), because the record ID
separates STEMI exactly in that synthetic corpus. **The application does not
redact uploaded photographs** — an uploaded sheet reaches the model as
photographed.

That is a deliberate train/serve difference, and it is the kind that belongs in
a writeup rather than in a footnote: the model sees a header band it never saw
printed text in during training. On the checked-in fixture sheet it moves the
score vector by ~1e-4, which is why `scripts/verify_model.py` still reproduces
the prototype's stored numbers well inside its 2e-3 tolerance — but that is one
sheet, and a real photograph carries a real patient header rather than a
synthetic `ECGnnnnnn`.

This is the difference the explainability stage exists to measure rather than
argue about. Every attribution map reports `header_frac` — the share of its
mass inside `explain.header_box` — and `lift`, that share over the box's share
of the sheet *area*. On the checked-in fixture (`corpus_sheet.jpg`, target
layer `attn`) the two round-3 checkpoints do **not** behave the same there:

| Grad-CAM header lift | STEMI | AF | LVH | NORMAL |
|---|---|---|---|---|
| `efficientnetv2_s_nat768` | 0.78 | 0.42 | 0.52 | 1.11 |
| `efficientnetv2_s_cbam_nat768` | 1.64 | 0.50 | 1.86 | 1.62 |
| `resnet50_cbam_nat768` | 0.005 | 0.003 | 0.034 | 0.000 |

A lift of 1.0 is uniform attention, and the peak lands outside the box for
every row here. The plain baseline sits at or below uniform on three of four
labels — better than its CBAM sibling, which puts ~1.6-1.9x uniform weight
there — but nowhere near the two ResNet-50 rows, which are three orders of
magnitude lower. Read that alongside the self-check: painting the training
REDACT_BOX back on moves this checkpoint's AF score by 6.7e-3, against 1.2e-4
for the CBAM run, so the header demonstrably reaches its output. That is one
sheet, so it is a flag rather than a verdict: run the same measurement over
real photographs and report the distribution before quoting this model's STEMI
score anywhere.

## Adding a new model

1. Copy the `.pt` into `weights/`.
2. Write `models/<id>.yaml` (start from `resnet50_cbam_nat768.yaml`);
   fill `expected_sha256` with `sha256sum` of the file, and
   `expected_protocol_fingerprint` from the blob's `protocol_fingerprint`,
   `fingerprint`, or `config_fingerprint` (the runner accepts those spellings
   in that order because the training generations used all three).
3. If the run used an architecture package that is not vendored yet, vendor it
   under `backend/arch/` first — see `backend/arch/README.md`.
4. Point `active.yaml` at it (or set `CARDIOSENTRY_ACTIVE_MODEL=<id>`).
5. Write the run's own stored score for `tests/fixtures/corpus_sheet.jpg` to
   `tests/fixtures/expected_scores_<id>.json` (that sheet is ECG000002, so the
   row is in the run's `predictions/test_predictions.csv`), add it to
   `EXPECTED_SCORES` in `tests/make_fixtures.py`, and point the descriptor's
   `verify.expected_scores` at it. Then restart and run
   `python scripts/verify_model.py --model <id>` — a shape check alone will not
   catch a transposed or wrong geometry, and a matching score vector will. If
   it fails, measure WHY before touching `verify.score_tolerance`: painting the
   training `REDACT_BOX` onto the fixture separates the documented header
   train/serve gap from actual timm/weights drift. If the run never evaluated
   this exact fixture, record a serving-path CPU vector and say so explicitly
   in its `source` field; do not pretend it came from the training report.
6. Sanity-check the Grad-CAM target with
   `curl localhost:8000/api/models/<id>/layers` — `auto_target_layer` should
   be the deepest feature map the head pools (`attn` on a CBAM hybrid,
   `backbone.layer4` on a plain ResNet-50). Pin `explain.target_layer` in the
   YAML if it is not.
7. Old captures can be re-scored by the new model without re-photographing:
   `python scripts/reprocess.py --all --model <id>`. When the new model's
   geometry differs from the one a capture was stored at, the script rebuilds
   `model_input.png` from `corrected.png` rather than resampling a square into
   a rectangle.
