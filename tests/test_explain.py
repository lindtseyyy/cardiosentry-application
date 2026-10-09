"""Explainability against the REAL model: Grad-CAM, end to end."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image
import io

from backend.services import explain as xai

LABELS = ["STEMI", "AF", "LVH", "NORMAL"]


@pytest.fixture(scope="module")
def rectified(client, fixtures):
    """One capture carried all the way to a stored model_input.png."""
    with open(fixtures / "photo_clean.jpg", "rb") as f:
        r = client.post("/api/captures",
                        files={"file": ("photo_clean.jpg", f, "image/jpeg")},
                        data={"sheet_id": "XAI-1"})
    assert r.status_code == 201, r.text
    cap = r.json()
    cid = cap["capture_id"]
    r = client.post(f"/api/captures/{cid}/rectify",
                    json={"quad_norm": cap["detection"]["quad_norm"],
                          "source": "auto", "geometry_mode": "training_canvas"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/captures/{cid}/predict", json={})
    assert r.status_code == 200, r.text
    return cid, r.json()


# ------------------------------------------------------------------- config
def test_config_advertises_explain(client):
    cfg = client.get("/api/config").json()["explain"]
    assert cfg["enabled"] is True
    assert cfg["methods"] == ["gradcam"]
    # The active checkpoint trained on a redacted corpus and the app does not
    # redact — the UI cannot warn about that unless config says so.
    assert cfg["header_redacted_in_training"] is True
    assert cfg["header_box"] == [0.10, 0.02, 0.30, 0.18]
    # Cost must be quotable BEFORE the run, not after.
    assert cfg["cost"]["gradcam"]["backward_full"] == 0
    assert cfg["cost"]["gradcam"]["backward_partial"] == len(LABELS)
    assert "default_ig_steps" not in cfg


def test_layers_endpoint(client):
    r = client.get("/api/models/resnet50_cbam_nat768/layers")
    assert r.status_code == 200, r.text
    body = r.json()
    # `attn` is the CBAM output — the tensor forward_head actually pools.
    assert body["auto_target_layer"] == "attn"
    assert body["descriptor_target_layer"] == "attn"
    auto = [l for l in body["layers"] if l["auto"]][0]
    assert auto["grid"] == [24, 32] and auto["channels"] == 2048
    assert auto["cell_px"] == [32.0, 32.0]


def test_auto_target_layer_per_family(client):
    """The auto rule must land on the deepest map of EVERY vendored family.

    The dual-stream case is the one that catches a wrong rule: its low-res
    stream has the coarsest grid, so a "coarsest grid" heuristic would explain
    the 384 view instead of the 768 detail view.
    """
    expected = {"resnet50_cbam_nat768": "attn",
                "efficientnetv2_s_cbam_nat768": "attn",
                # baselines_v2: an UNWRAPPED timm backbone, so there is no
                # `attn` to find — the deepest map is the activated conv_head
                # output the classifier pools.
                "efficientnetv2_s_nat768": "bn2",
                "resnet50_hires": "backbone.layer4",
                "resnet50_dual": "hi.layer4",
                "resnet50_v1": "layer4"}
    for model_id, layer in expected.items():
        body = client.get(f"/api/models/{model_id}/layers").json()
        assert body["auto_target_layer"] == layer, model_id


# ------------------------------------------------------------------ grad-cam
def test_gradcam_all_labels(client, rectified):
    cid, pred = rectified
    r = client.post(f"/api/captures/{cid}/explain", json={"method": "gradcam"})
    assert r.status_code == 201, r.text
    body = r.json()

    assert body["method"] == "gradcam"
    assert body["labels"] == LABELS          # cheap per label -> whole head
    assert body["meta"]["target_layer"] == "attn"
    assert body["meta"]["feature_grid"] == [24, 32]
    # Provenance: the map must name the pixels it attributed.
    assert body["model_input_sha256"] == pred["model_input_sha256"]
    assert body["run_id"] == pred["run_id"]

    for a in body["attributions"]:
        # The score the map explains travels WITH the map.
        assert a["score"] == pytest.approx(pred["scores"][a["label"]])
        assert a["threshold"] == pytest.approx(pred["thresholds"][a["label"]])
        assert 0.0 <= a["header"]["frac"] <= 1.0
        assert a["header"]["box"] == [0.10, 0.02, 0.30, 0.18]
        for kind in ("heatmap", "overlay"):
            f = client.get(a["files"][kind])
            assert f.status_code == 200, a["files"][kind]
            assert f.headers["content-type"] == "image/png"
            im = Image.open(io.BytesIO(f.content))
            # Overlays are drawn ON the model input, so they must BE its size.
            assert im.size == (1024, 768)

    assert any("not a clinical finding" in c for c in body["caveats"])
    assert any("cell is about" in c for c in body["caveats"])


def test_gradcam_named_layer_is_shallower(client, rectified):
    """A named target layer must actually be used, not silently ignored."""
    cid, _ = rectified
    r = client.post(f"/api/captures/{cid}/explain",
                    json={"method": "gradcam", "labels": ["STEMI"],
                          "target_layer": "backbone.layer3"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["meta"]["target_layer"] == "backbone.layer3"
    assert body["meta"]["feature_grid"] == [48, 64]     # one stage shallower
    assert len(body["attributions"]) == 1


def test_unknown_target_layer_is_a_readable_422(client, rectified):
    cid, _ = rectified
    r = client.post(f"/api/captures/{cid}/explain",
                    json={"method": "gradcam", "target_layer": "layer4"})
    assert r.status_code == 422
    assert r.json()["code"] == "UNKNOWN_TARGET_LAYER"
    assert "backbone.layer4" in r.json()["message"]     # suggests the near miss


def test_map_geometry_follows_the_stored_png_not_the_descriptor(client, rectified):
    """A 768x768 model explaining a 768x1024 capture must still draw on the sheet.

    `predict` deliberately lets any model score any stored model_input.png, so
    a map anchored to `descriptor.preprocess.input_hw` instead of the file's own
    size would composite a square map onto a rectangular photograph.
    """
    cid, _ = rectified
    r = client.post(f"/api/captures/{cid}/explain",
                    json={"method": "gradcam", "model_id": "resnet50_hires",
                          "labels": ["STEMI"]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["model"]["id"] == "resnet50_hires"
    assert body["model"]["input_size"] == [768, 768]     # the MODEL is square
    assert body["meta"]["map_hw"] == [768, 1024]         # the SHEET is not
    f = client.get(body["attributions"][0]["files"]["overlay"])
    assert f.status_code == 200
    assert Image.open(io.BytesIO(f.content)).size == (1024, 768)


def test_gradcam_records_no_graph_before_its_target(client, rectified):
    """Grad-CAM's backward stops at the target layer, so nothing upstream of it
    is recorded. That is the difference between +44 MB and +2307 MB on this
    model — i.e. between an explanation and an OOM-killed server."""
    cid, _ = rectified
    body = client.post(f"/api/captures/{cid}/explain",
                       json={"method": "gradcam", "labels": ["STEMI"]}).json()
    assert body["meta"]["graph_from"] == body["meta"]["target_layer"]
    assert body["meta"]["memory"]["estimated_need_mb"] < 500


def test_memory_plan_refuses_rather_than_risk_the_oom_killer(client, monkeypatch):
    from backend.errors import ApiError
    import backend.main as main

    lm = main.app.state.csd.active_model
    monkeypatch.setattr(xai, "available_mb", lambda: 16_000.0)
    assert xai.plan_memory(lm)["estimated_need_mb"] < 500

    monkeypatch.setattr(xai, "available_mb", lambda: 10.0)
    with pytest.raises(ApiError) as e:
        xai.plan_memory(lm)
    assert e.value.code == "EXPLAIN_INSUFFICIENT_MEMORY"
    assert e.value.status_code == 507


# ------------------------------------------------------------- list / delete
def test_list_get_and_delete(client, rectified):
    cid, _ = rectified
    # Own its own run rather than inheriting one from an earlier test, so the
    # suite stays runnable one test at a time.
    xid = client.post(f"/api/captures/{cid}/explain",
                      json={"method": "gradcam", "labels": ["STEMI"]}
                      ).json()["explain_id"]
    lst = client.get(f"/api/captures/{cid}/explain").json()
    assert lst["total"] >= 1
    assert xid in {e["explain_id"] for e in lst["explanations"]}
    assert all(e["stale"] is False for e in lst["explanations"])
    assert lst["explanations"][0]["explain_id"] == xid      # newest first
    rec = client.get(f"/api/captures/{cid}/explain/{xid}").json()
    assert rec["explain_id"] == xid
    assert rec["env"]["torch"]                      # versions travel with data

    # The capture record indexes its runs, like it does predictions.
    cap = client.get(f"/api/captures/{cid}").json()
    assert xid in cap["explanations"]

    d = client.delete(f"/api/captures/{cid}/explain/{xid}")
    assert d.status_code == 200 and d.json()["deleted"] is True
    assert client.get(f"/api/captures/{cid}/explain/{xid}").status_code == 404
    cap = client.get(f"/api/captures/{cid}").json()
    assert xid not in cap["explanations"]


def test_legacy_runs_of_removed_methods_still_list(client, rectified):
    """Captures made before Integrated Gradients and the Jacobian were removed
    still hold their imported runs. Listing them must not 500."""
    cid, _ = rectified
    xid = "xai_20260101_000000_000_jacobian_resnet50_cbam_nat768"
    client.app.state.csd.records.add_explanation(cid, {
        "explain_id": xid, "method": "jacobian",
        "model": {"id": "resnet50_cbam_nat768"},
        "created_utc": "2026-01-01T00:00:00Z", "labels": ["STEMI"],
        "attributions": [], "model_input_sha256": "0" * 64})
    try:
        r = client.get(f"/api/captures/{cid}/explain")
        assert r.status_code == 200, r.text
        assert "jacobian" in {e["method"] for e in r.json()["explanations"]}
    finally:
        client.delete(f"/api/captures/{cid}/explain/{xid}")


def test_rerectify_marks_existing_maps_stale(client, rectified):
    """A map explains the pixels it was computed on. Re-rectifying replaces
    those pixels, and the run must say so rather than keep looking current."""
    cid, _ = rectified
    client.post(f"/api/captures/{cid}/explain",
                json={"method": "gradcam", "labels": ["STEMI"]})
    cap = client.get(f"/api/captures/{cid}").json()
    quad = cap["detection"]["quad_norm"]
    nudged = [[min(1.0, x + 0.01), y] for x, y in quad]
    r = client.post(f"/api/captures/{cid}/rectify",
                    json={"quad_norm": nudged, "source": "manual",
                          "geometry_mode": "training_canvas"})
    assert r.status_code == 200, r.text
    lst = client.get(f"/api/captures/{cid}/explain").json()
    assert lst["total"] >= 1
    assert all(e["stale"] is True for e in lst["explanations"])


# ------------------------------------------------------------------- errors
def test_explain_needs_a_rectified_capture(client, fixtures):
    with open(fixtures / "photo_clean.jpg", "rb") as f:
        cap = client.post("/api/captures",
                          files={"file": ("photo_clean.jpg", f, "image/jpeg")}).json()
    r = client.post(f"/api/captures/{cap['capture_id']}/explain",
                    json={"method": "gradcam"})
    assert r.status_code == 404
    assert r.json()["code"] == "MISSING_MODEL_INPUT"


def test_unknown_method_and_label(client, rectified):
    cid, _ = rectified
    for gone in ("lime", "integrated_gradients", "jacobian"):
        assert client.post(f"/api/captures/{cid}/explain",
                           json={"method": gone}).status_code == 422, gone
    r = client.post(f"/api/captures/{cid}/explain",
                    json={"method": "gradcam", "labels": ["BRUGADA"]})
    assert r.status_code == 422 and r.json()["code"] == "UNKNOWN_LABEL"


def test_explain_file_serving_refuses_traversal(client, rectified):
    cid, _ = rectified
    xid = client.post(f"/api/captures/{cid}/explain",
                      json={"method": "gradcam", "labels": ["STEMI"]}
                      ).json()["explain_id"]
    for bad in ("..%2F..%2Fcapture.json", "evil.sh", "gradcam_X_heatmap.jpg"):
        r = client.get(f"/api/captures/{cid}/explain/{xid}/files/{bad}")
        assert r.status_code == 404, bad
    r = client.get(f"/api/captures/{cid}/explain/not_an_id/files/record.json")
    assert r.status_code == 404


def test_label_slug_stays_servable():
    """Filenames are constrained by storage.EXPLAIN_FILE_RE. A label the
    descriptor is free to spell must never produce a file that 404s."""
    from backend.api.explain import _slug
    from backend.services import storage

    assert _slug("STEMI", 0) == "STEMI"          # the common case is untouched
    for label in ("STEMI", "ST elevation", "../evil", "ünïcode", ""):
        name = f"gradcam_{_slug(label, 0)}_heatmap.png"
        assert storage.EXPLAIN_FILE_RE.fullmatch(name), label
        assert "/" not in name and ".." not in name


# -------------------------------------------------------------- unit-level
def test_box_fraction_lift_is_area_normalized():
    """lift = 1.0 when attention is uniform, whatever the box's size."""
    m = np.ones((100, 100), dtype=np.float32)
    r = xai.box_fraction(m, [0.0, 0.0, 0.5, 0.5])
    assert r["box_area_frac"] == pytest.approx(0.25)
    assert r["frac"] == pytest.approx(0.25)
    assert r["lift"] == pytest.approx(1.0)

    m = np.zeros((100, 100), dtype=np.float32)
    m[:50, :50] = 1.0                       # ALL the mass inside the box
    r = xai.box_fraction(m, [0.0, 0.0, 0.5, 0.5])
    assert r["frac"] == pytest.approx(1.0)
    assert r["lift"] == pytest.approx(4.0)
    assert r["peak_inside"] is True


def test_normalize_map_is_robust_to_one_hot_pixel():
    m = np.zeros((64, 64), dtype=np.float32)
    m[:, :] = 0.1
    m[0, 0] = 1000.0                        # a single outlier
    n, info = xai.normalize_map(m, pct=99.0)
    assert info["scale"] == pytest.approx(0.1, abs=1e-6)
    assert n.max() == pytest.approx(1.0)    # the bulk is not crushed to black
    assert n[32, 32] == pytest.approx(1.0)


def test_map_summary_concentration():
    diffuse = np.ones((100, 100), dtype=np.float32)
    peaked = np.zeros((100, 100), dtype=np.float32)
    peaked[49:51, 49:51] = 1.0
    assert (xai.map_summary(peaked)["mass_half_area_frac"]
            < xai.map_summary(diffuse)["mass_half_area_frac"])
    assert xai.map_summary(peaked)["peak_xy"] == pytest.approx([0.49, 0.49])
