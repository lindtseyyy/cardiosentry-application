# Vendored architecture code — provenance

The `.pt` files this application loads are **not** self-contained modules. Each
is a `{"model": state_dict, "thresholds": [...], ...}` blob that must be
rebuilt with the exact `nn.Module` classes the training run used. These
subpackages are pinned copies of that code.

## Provenance

| Package | Copied from | Serves |
|---|---|---|
| `convnext_v1_clean12/` | `build_model` in `prototype-code/clean_convnext_codes/convnext_v1_base_clean12_v1/make_notebook.py` | HEEDB clean12 `convnext_base.fb_in22k_ft_in1k_384`: bare timm module, 12 logits, `drop_path_rate=0.2`, `head_init_scale=0.001`, plain-tensor forward. The checkpoint is the full training `best.pt`; the runner serves its `selected_weight_source` (EMA) |
| `convnext_v1_rfpn_clean12/` | `fusion_necks.py` verbatim + `build_model` in `prototype-code/clean_convnext_codes/convnext_v1_base_msff_clean12_colab_v1/make_notebook.py` (`CS_FUSION=rfpn`); `convnext_tiny_rfpn_clean12` from `convnext_tiny_v1_rfpn_clean12_colab_v1/make_notebook.py` (identical `build_model` and `fusion_necks.py` in `convnext_tiny_v1_rfpn_clean12_aug_colab_v1/`) | HEEDB clean12 `convnext_base.fb_in22k_ft_in1k_384` (12 logits, `drop_path_rate=0.2`, `head_init_scale=0.001`) wrapped in `ConvNeXtMultiScaleFusion`: FPN neck over timm stages.1-3 at 256 channels, residual head (ConvNeXt logits + LayerNorm/Linear over the pooled neck). Keys `backbone.*`, `neck.*`, `fuse_norm.*`, `fuse_fc.*`; plain-tensor forward. The checkpoint is the run's `inference.pt` (selected EMA weights under `model`). `convnext_tiny_rfpn_clean12` is the same build on `convnext_tiny.fb_in22k_ft_in1k_384` (`drop_path_rate=0.1`), served as diagnostic models `convnext_tiny_rfpn_clean12` (run `convnext_tiny_v1_rfpn_clean12_colab_a100_seed42` `inference.pt`) and `convnext_tiny_rfpn_clean12_aug` (run `convnext_tiny_v1_rfpn_clean12_aug_colab_a100_seed42` `inference.pt`, clean + augmented sheets), and as the ECG gate's frozen feature extractor (`services/ecg_gate.py`) |
| `convnextv2_v1img/` | factory in `prototype-code/convnextv2_tiny_v1img_v1/make_notebook.py` | V1 clean-image `convnextv2_tiny.fcmae_ft_in22k_in1k_384`: bare timm module, 12 logits, `drop_path_rate=0.2`, plain-tensor forward |
| `hybrids_v2/` | `prototype-code/cardiosentry_hybrids_v2/{config,dimensions,hybrids,models}.py` | round-3 geometry-study checkpoints (`resnet50_cbam`, `efficientnetv2_s_cbam`, …), the ones trained on a RECTANGLE. Forward signature: **plain tensor**. `REGISTRY` and `build()` live in `models.py` |
| `hybrids_v1/` | `prototype-code/cardiosentry_hybrids_v1/{config,hybrids}.py` | round-2 hybrid checkpoints (`resnet50_hires`, `resnet50_dual`, …). Forward signature: **dict** `{768: tensor}` |
| `baselines_v2/` | `prototype-code/cardiosentry_baselines_v2/models.py` + the `{config,dimensions}.py` the two v2 packages share | round-3 **plain baselines** (`efficientnetv2_s`, `resnet50`, …) — the unmodified backbones the hybrids are measured against. `build()` is a bare `timm.create_model(tag, num_classes=4)` with no wrapper, so the checkpoints are bare timm state_dicts (`conv_stem…classifier`). Forward signature: **plain tensor**. `REGISTRY` and `build()` live in `models.py` |
| `runs_v1/` | `prototype-code/cardiosentry_runs_v1/{config,models}.py` | round-1 checkpoints (`resnet50`, `vgg16`, …). Forward signature: **plain tensor** |

Source repository: `CardioSentry` (commit `9c19a22`, first commit).
`hybrids_v1/` and `runs_v1/` vendored on 2026-08-23, `hybrids_v2/` on
2026-08-27, `baselines_v2/` on 2026-08-29, `convnextv2_v1img/` on
2026-09-19, `convnext_v1_clean12/` on 2026-10-03, and `convnext_v1_rfpn_clean12/`
on 2026-10-09. `baselines_v2/config.py` and
`baselines_v2/dimensions.py` are byte-identical to the `hybrids_v2/` copies —
the two research packages share those files verbatim — and are duplicated
rather than cross-imported so each package stays pinned on its own: a future
run vendored at a different geometry must not be able to move another
package's `DIM_NAME` out from under its checkpoints. Trained with `timm 1.0.28`, `torch 2.x` — **do not upgrade timm**
without re-running `scripts/verify_model.py` (timm `create_model` tag semantics
have changed across versions and these modules depend on them).

## The documented deviations

**1. Relative imports.** `hybrids_v1/hybrids.py`, `runs_v1/models.py`, all
three importing modules under `hybrids_v2/` and `baselines_v2/{config,models}.py`
originally used top-level imports (`import config as C`, `import hybrids as H`,
`import dimensions as DIM`). For them to work as subpackages here, those lines
were changed to `from . import …` and each is marked with a comment.

**2. `hybrids_v2/config.py` and `baselines_v2/config.py` pin `DIM_NAME`.** The research copy read the input
geometry from the `CS_DIM` environment variable. Serving must not inherit
whichever shell it was started from, so the vendored copy hard-codes
`DIM_NAME = "nat768"`. This is the geometry the vendored checkpoints were
trained at, and it reproduces both published fingerprints exactly
(`fingerprint()` = `e0fef6cd72607f35`, `protocol_fingerprint()` =
`36988c5e0ba5d72d`). What actually resizes a capture is the descriptor's
`preprocess.input_size`, not this constant — a run at a different geometry
needs its own vendored package, not an env var.

Everything else is byte-for-byte identical to the source files, including the
`REGISTRY` tables, the `build()` factories, and all default hyperparameters.

**3. ConvNeXt-V2 factory extraction.** The V1 training source is a generated
notebook rather than a Python architecture package. `convnextv2_v1img/models.py`
extracts its `build_model` call verbatim in behavior: the same timm tag,
`num_classes=12`, and `drop_path_rate=0.2`. It deliberately omits training-only
optimizer, loss, data-loader, and S3 code.

**4. ConvNeXt-V1 RFPN factory extraction.** `convnext_v1_rfpn_clean12/
fusion_necks.py` is the run's file byte for byte (sha256 `7570a280…`, identical
in the A100, L4 and EC2 folders; the notebook inlines it). `models.py` extracts
`build_model` with the run's `CS_FUSION=rfpn` resolution fixed: the same timm
tag and arguments, then `ConvNeXtMultiScaleFusion(backbone, "fpn", "residual",
12, channels=256, bifpn_repeats=2, head_init_scale=0.001)`. Environment
variables are not read. The Tiny run's `fusion_necks.py` is byte-identical to
this copy; its `REGISTRY` entry (added 2026-10-15) differs only in the timm tag
and the Tiny recipe's `drop_path_rate=0.1` (inactive at eval).
