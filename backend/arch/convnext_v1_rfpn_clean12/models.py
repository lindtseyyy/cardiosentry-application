"""Exact model factory used by the ConvNeXt-V1 + RFPN clean12 training runs.

`build_model` in `prototype-code/clean_convnext_codes/
convnext_v1_base_msff_clean12_colab_v1/make_notebook.py` with `CS_FUSION=rfpn`:
a timm `convnext_base.fb_in22k_ft_in1k_384` (twelve logits, drop-path 0.2,
0.001 classifier init scale) wrapped in `ConvNeXtMultiScaleFusion` with an FPN
neck over timm stages.1-3 (256 channels) and the residual head, whose logits are
the ConvNeXt head's plus a LayerNorm + Linear over the pooled neck maps.
`convnext_tiny_rfpn_clean12` is the same build from
`convnext_tiny_v1_rfpn_clean12_colab_v1/make_notebook.py` (ConvNeXt-V1 Tiny,
drop-path 0.1); the app serves it as diagnostic model
`convnext_tiny_rfpn_clean12` and as the learned ECG gate's frozen feature
extractor (services/ecg_gate.py). `fusion_necks.py` is the runs' own file (identical in
both), copied byte for byte. The init values do not matter once the weights are
loaded; they are kept so the module is built exactly as in training and
`load_state_dict(strict=True)` checks the same architecture.
"""
from __future__ import annotations

REGISTRY = {
    "convnext_base_rfpn_clean12": {
        "timm": "convnext_base.fb_in22k_ft_in1k_384",
        "num_classes": 12,
        "drop_path_rate": 0.2,
        "head_init_scale": 0.001,
        "fusion": "rfpn",
        "fusion_channels": 256,
        "bifpn_repeats": 2,
        "pretrain": "Supervised ImageNet-22K -> ImageNet-1K fine-tuning at 384px",
    },
    "convnext_tiny_rfpn_clean12": {
        "timm": "convnext_tiny.fb_in22k_ft_in1k_384",
        "num_classes": 12,
        "drop_path_rate": 0.1,
        "head_init_scale": 0.001,
        "fusion": "rfpn",
        "fusion_channels": 256,
        "bifpn_repeats": 2,
        "pretrain": "Supervised ImageNet-22K -> ImageNet-1K fine-tuning at 384px",
    },
}


def build(name: str, pretrained: bool = False):
    import timm

    from .fusion_necks import ConvNeXtMultiScaleFusion, resolve_fusion

    if name not in REGISTRY:
        raise KeyError(f"unknown model {name!r}; choose from {list(REGISTRY)}")
    spec = REGISTRY[name]
    backbone = timm.create_model(
        spec["timm"],
        pretrained=pretrained,
        num_classes=spec["num_classes"],
        drop_path_rate=spec["drop_path_rate"],
        head_init_scale=spec["head_init_scale"],
    )
    neck, head_mode = resolve_fusion(spec["fusion"])
    model = ConvNeXtMultiScaleFusion(
        backbone, neck, head_mode, spec["num_classes"],
        channels=spec["fusion_channels"], bifpn_repeats=spec["bifpn_repeats"],
        head_init_scale=spec["head_init_scale"],
    )
    info = {
        **spec,
        "resolved_tag": spec["timm"],
        "params_m_actual": sum(p.numel() for p in model.parameters()) / 1e6,
        "timm_version": getattr(timm, "__version__", "?"),
    }
    return model, info
