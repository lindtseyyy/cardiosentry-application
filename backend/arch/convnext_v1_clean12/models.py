"""Exact model factory used by the ConvNeXt-V1 Base clean12 training run.

`build_model` in `prototype-code/clean_convnext_codes/convnext_v1_base_clean12_v1/
make_notebook.py` is a bare timm model: twelve logits, drop-path 0.2 and a
0.001 classifier init scale. The init scale does not matter once the weights
are loaded, but it is kept so the module is built exactly as in training and
`load_state_dict(strict=True)` checks the same architecture.
"""
from __future__ import annotations

REGISTRY = {
    "convnext_base_clean12": {
        "timm": "convnext_base.fb_in22k_ft_in1k_384",
        "num_classes": 12,
        "drop_path_rate": 0.2,
        "head_init_scale": 0.001,
        "pretrain": "Supervised ImageNet-22K -> ImageNet-1K fine-tuning at 384px",
    }
}


def build(name: str, pretrained: bool = False):
    import timm

    if name not in REGISTRY:
        raise KeyError(f"unknown model {name!r}; choose from {list(REGISTRY)}")
    spec = REGISTRY[name]
    model = timm.create_model(
        spec["timm"],
        pretrained=pretrained,
        num_classes=spec["num_classes"],
        drop_path_rate=spec["drop_path_rate"],
        head_init_scale=spec["head_init_scale"],
    )
    info = {
        **spec,
        "resolved_tag": spec["timm"],
        "params_m_actual": sum(p.numel() for p in model.parameters()) / 1e6,
        "timm_version": getattr(timm, "__version__", "?"),
    }
    return model, info
