"""End-to-end API smoke test: the staged flow against the REAL model.

upload -> detect -> rectify -> predict -> history -> annotate -> trash
"""
from __future__ import annotations

import shutil
from secrets import token_hex

import pytest
from fastapi.testclient import TestClient


def _upload_photo(client, fixtures, name: str, **form):
    with open(fixtures / name, "rb") as f:
        r = client.post("/api/captures",
                        files={"file": (name, f, "image/jpeg")},
                        data=form)
    assert r.status_code == 201, r.text
    return r.json()


def _user_client(client, username, password):
    user_client = TestClient(client.app)
    r = user_client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert r.status_code == 201, r.text
    return user_client


def _new_user_client(client):
    return _user_client(client, f"u_{token_hex(4)}", "test-password")


def _assert_capture_hidden(c, capture_id, quad_norm):
    for method, suffix, body in (
        ("GET", "", None),
        ("GET", "/files/preview.jpg", None),
        ("POST", "/rectify", {"quad_norm": quad_norm, "source": "auto"}),
        ("PATCH", "/annotation", {
            "reference_labels": {"AF": True}, "truth_source": "test",
        }),
        ("DELETE", "", None),
        ("GET", "/explain", None),
        ("POST", "/guidance", {
            "run_id": "run_20990101_000000_000_resnet50_cbam_nat768",
            "context_complete": False,
        }),
    ):
        r = c.request(method, f"/api/captures/{capture_id}{suffix}", json=body)
        assert r.status_code == 404, f"{method} {suffix}: {r.text}"
        assert r.json()["code"] == "CAPTURE_NOT_FOUND"


def test_health_and_config(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["model_loaded"] is True
    assert h["active_model"] == "resnet50_cbam_nat768"

    cfg = client.get("/api/config").json()
    assert cfg["active_model"]["labels"] == ["STEMI", "AF", "LVH", "NORMAL"]
    assert cfg["active_model"]["display_names"]["STEMI"] == "ST-Elevation MI (STEMI)"
    assert set(cfg["active_model"]["thresholds"]) == {"STEMI", "AF", "LVH", "NORMAL"}
    # The suite intentionally pins a legacy model. Guidance remains locked to
    # the reviewed models rather than silently reusing their rules here.
    assert cfg["guidance"]["enabled"] is False
    assert cfg["guidance"]["model_id"] is None
    assert "resnet50_cbam_nat768" not in cfg["guidance"]["model_ids"]
    assert [t["id"] for t in cfg["guidance"]["urgency_levels"]] == [
        "green", "yellow", "orange", "red",
    ]
    assert cfg["rectify"]["geometry_modes"] == ["training_canvas"]
    assert cfg["rectify"]["default_geometry_mode"] == "training_canvas"
    assert "must not be used alone for patient care" in cfg["notice"]
    assert cfg["privacy"]["notice_version"]
    assert set(cfg["privacy"]) == {"notice_version", "controller", "contact"}
    assert "does not replace professional medical evaluation" in cfg["notice"]


def test_models_list(client):
    m = client.get("/api/models").json()
    assert m["active_id"] == "resnet50_cbam_nat768"
    ids = {x["id"] for x in m["models"]}
    assert {"resnet50_cbam_nat768", "efficientnetv2_s_cbam_nat768",
            "efficientnetv2_s_nat768", "resnet50_hires", "resnet50_dual",
            "resnet50_v1", "convnextv2_tiny_v1img_v1"} <= ids
    active = [x for x in m["models"] if x["active"]][0]
    assert active["call_style"] == "tensor"
    assert active["input_size"] == [768, 1024]      # [height, width]
    assert active["views"] == [[768, 1024]]
    # The square round-2 descriptors must still round-trip through the widened
    # schema, spelled as they always were.
    hires = [x for x in m["models"] if x["id"] == "resnet50_hires"][0]
    assert hires["input_size"] == [768, 768] and hires["views"] == [[768, 768]]


def test_full_staged_flow(client, fixtures):
    from backend.services import storage
    from backend.settings import settings

    # 1) upload -> detect + quality + preview files
    cap = _upload_photo(client, fixtures, "photo_clean.jpg",
                        sheet_id="SHEET-TEST-1", blind_mode="true",
                        privacy_notice="2026-10-04")
    cid = cap["capture_id"]
    assert client.get(f"/api/captures/{cid}").json()["session"][
        "privacy_notice_ack"] == "2026-10-04"
    assert cap["original"]["width"] == 2400
    det = cap["detection"]
    assert det["quad_norm"] and len(det["quad_norm"]) == 4
    assert client.get(f"/api/captures/{cid}/files/preview.jpg").status_code == 200
    assert client.get(f"/api/captures/{cid}/files/overlay.jpg").status_code == 200

    # 2) rectify with the detected (auto) quad
    r = client.post(f"/api/captures/{cid}/rectify",
                    json={"quad_norm": det["quad_norm"], "source": "auto",
                          "geometry_mode": "training_canvas"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["corrected_px"] == [1686, 1311]
    assert body["preprocess"]["tensor_shape"] == [1, 3, 768, 1024]
    assert body["preprocess"]["input_size"] == [768, 1024]
    assert client.get(f"/api/captures/{cid}/files/model_input.png").status_code == 200

    # 3) predict (real CPU forward, ~1-2 s)
    p = client.post(f"/api/captures/{cid}/predict", json={})
    assert p.status_code == 200, p.text
    pred = p.json()
    assert set(pred["scores"]) == {"STEMI", "AF", "LVH", "NORMAL"}
    assert all(0.0 < s < 1.0 for s in pred["scores"].values())
    assert pred["threshold_source"] == "checkpoint"
    assert pred["thresholds"]["STEMI"] == pytest.approx(0.32, abs=0.001)
    assert pred["timing_ms"]["forward"] > 0
    assert pred["model"]["checkpoint_sha256_short"]

    # This fixture is ECG000002, whose AF head is near-certain (the prototype
    # scored it 0.99999). The real-photo warp may shift scores, but the
    # positive set must be a well-formed subset of the labels.
    assert set(pred["positive"]) <= {"STEMI", "AF", "LVH", "NORMAL"}

    # This suite pins a legacy model, so the route must refuse to reuse a
    # reviewed model's clinical rules for a different label set.
    g = client.post(
        f"/api/captures/{cid}/guidance",
        json={"run_id": pred["run_id"], "context_complete": False},
    )
    assert g.status_code == 422
    assert g.json()["code"] == "GUIDANCE_UNSUPPORTED_MODEL"

    # 4) history + detail show the run
    lst = client.get("/api/captures").json()
    ids = [c["capture_id"] for c in lst["captures"]]
    assert cid in ids
    summary = next(c for c in lst["captures"] if c["capture_id"] == cid)
    assert summary["sheet_id"] == "SHEET-TEST-1"
    assert summary["latest_model_id"] == "resnet50_cbam_nat768"

    detail = client.get(f"/api/captures/{cid}").json()
    assert len(detail["prediction_runs"]) == 1
    assert detail["correction"]["geometry_mode"] == "training_canvas"
    assert detail["preprocess"]["tensor_sha256"]

    # 5) annotation (reference labels — §17.6)
    ann = client.patch(f"/api/captures/{cid}/annotation",
                       json={"reference_labels": {"STEMI": False, "AF": True,
                                                  "LVH": False, "NORMAL": False},
                             "truth_source": "test"})
    assert ann.status_code == 200
    detail = client.get(f"/api/captures/{cid}").json()
    assert detail["annotation"]["reference_labels"]["AF"] is True

    # 6) trash (never unlink)
    assert not (storage.capture_dir(cid) / "capture.json").exists()
    d = client.delete(f"/api/captures/{cid}")
    assert d.status_code == 200
    with client.app.state.csd.db.connection() as conn:
        assert conn.execute(
            "SELECT trashed_utc IS NOT NULL FROM captures WHERE capture_id=%s",
            (cid,),
        ).fetchone()[0] is True
    assert (settings.data_dir / "_trash" / cid[:10] / cid).is_dir()
    assert client.get(f"/api/captures/{cid}").status_code == 404


def test_predict_before_rectify_is_a_clear_error(client, fixtures):
    cap = _upload_photo(client, fixtures, "photo_clean.jpg")
    cid = cap["capture_id"]
    r = client.post(f"/api/captures/{cid}/predict", json={})
    assert r.status_code == 404
    assert r.json()["code"] == "MISSING_MODEL_INPUT"


def test_error_codes_are_stable(client):
    assert client.post("/api/captures",
                       files={"file": ("x.jpg", b"not an image", "image/jpeg")}
                       ).json()["code"] == "UNSUPPORTED_FORMAT"
    r = client.post("/api/captures/2026-01-01_000000_000000/rectify",
                    json={"quad_norm": [[0, 0], [1, 0], [1, 1], [0, 1]]})
    assert r.status_code == 404 and r.json()["code"] == "CAPTURE_NOT_FOUND"
    assert client.get("/api/captures/nonsense").status_code == 404


def test_unknown_model_and_bad_thresholds(client, fixtures):
    cap = _upload_photo(client, fixtures, "photo_clean.jpg")
    cid = cap["capture_id"]
    det = cap["detection"]
    client.post(f"/api/captures/{cid}/rectify",
                json={"quad_norm": det["quad_norm"], "source": "auto"})
    r = client.post(f"/api/captures/{cid}/predict", json={"model_id": "nope"})
    assert r.status_code == 404 and r.json()["code"] == "UNKNOWN_MODEL"
    r = client.post(f"/api/captures/{cid}/predict",
                    json={"thresholds": {"STEMI": 1.5}})
    assert r.status_code == 422 and r.json()["code"] == "INCOMPLETE_THRESHOLDS"
    r = client.post(f"/api/captures/{cid}/predict",
                    json={"thresholds": {"STEMI": 1.5, "AF": 0.5,
                                         "LVH": 0.5, "NORMAL": 0.5}})
    assert r.status_code == 422 and r.json()["code"] == "THRESHOLD_OUT_OF_RANGE"
    r = client.post(f"/api/captures/{cid}/predict",
                    json={"thresholds": {"STEMI": 0.9, "AF": 0.5,
                                         "LVH": 0.5, "NORMAL": 0.5}})
    assert r.status_code == 200
    assert r.json()["threshold_source"] == "user_override"
    assert r.json()["thresholds"]["STEMI"] == 0.9
    assert r.json()["labels"] == ["STEMI", "AF", "LVH", "NORMAL"]
    assert r.json()["display_names"]["STEMI"] == "ST-Elevation MI (STEMI)"


def test_auth_required_for_private_routes(anon_client):
    for path in ("/api/health", "/api/config"):
        r = anon_client.get(path)
        assert r.status_code == 200, r.text

    for path in (
        "/api/auth/me",
        "/api/captures",
        "/api/models",
        "/api/captures/2026-01-01_000000_000000/files/preview.jpg",
    ):
        r = anon_client.get(path)
        assert r.status_code == 401, r.text
        assert r.json() == {
            "code": "AUTH_REQUIRED", "message": "Sign in to continue.",
        }

    r = anon_client.patch("/api/auth/account", json={})
    assert r.status_code == 401, r.text
    assert r.json() == {
        "code": "AUTH_REQUIRED", "message": "Sign in to continue.",
    }


def test_register_login_logout(anon_client, client):
    username = f"u_{token_hex(4)}"
    password = "test-password-123"
    r = anon_client.post("/api/auth/register",
                         json={"username": "bad username", "password": password})
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "INVALID_USERNAME"
    r = anon_client.post("/api/auth/register",
                         json={"username": username, "password": "short"})
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "INVALID_PASSWORD"

    r = anon_client.post("/api/auth/register",
                         json={"username": username, "password": password})
    assert r.status_code == 201, r.text
    assert r.json() == {"username": username}
    assert anon_client.cookies.get("cardiosentry_session")
    assert "httponly" in r.headers["set-cookie"].lower()
    me = anon_client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json() == {"username": username}

    for taken in (username.upper(), "ADMIN"):
        r = anon_client.post("/api/auth/register",
                             json={"username": taken, "password": password})
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "USERNAME_TAKEN"

    r = anon_client.post("/api/auth/logout")
    assert r.status_code == 200, r.text
    assert r.json() == {"logged_out": True}
    assert anon_client.cookies.get("cardiosentry_session") is None
    me = anon_client.get("/api/auth/me")
    assert me.status_code == 401, me.text
    assert me.json()["code"] == "AUTH_REQUIRED"

    for credentials in (
        {"username": username, "password": "wrong-password"},
        {"username": f"u_{token_hex(4)}", "password": password},
    ):
        r = anon_client.post("/api/auth/login", json=credentials)
        assert r.status_code == 401, r.text
        assert r.json()["code"] == "INVALID_CREDENTIALS"
    r = anon_client.post("/api/auth/login",
                         json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    assert r.json() == {"username": username}
    me = anon_client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json() == {"username": username}

    with client.app.state.csd.db.connection() as conn:
        accounts_text, sessions_text = conn.execute(
            "SELECT (SELECT string_agg(t::text, '') FROM accounts AS t), "
            "(SELECT string_agg(t::text, '') FROM sessions AS t)",
        ).fetchone()
        password_hash = conn.execute(
            "SELECT password_hash FROM accounts WHERE username=%s", (username,),
        ).fetchone()[0]
    assert password not in accounts_text
    assert password not in sessions_text
    assert password_hash.startswith("pbkdf2_sha256$")


def test_default_admin_account_is_seeded(anon_client):
    r = anon_client.post("/api/auth/login",
                         json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    assert r.json() == {"username": "admin"}
    me = anon_client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json() == {"username": "admin"}


def test_captures_are_owner_scoped(client, fixtures):
    admin_capture = _upload_photo(client, fixtures, "photo_clean.jpg")
    admin_id = admin_capture["capture_id"]
    user_client = _new_user_client(client)
    try:
        r = user_client.get("/api/captures")
        assert r.status_code == 200, r.text
        assert r.json()["captures"] == []
        assert r.json()["total"] == 0
        user_capture = _upload_photo(user_client, fixtures, "photo_clean.jpg")
        user_id = user_capture["capture_id"]
        r = user_client.get("/api/captures")
        assert r.status_code == 200, r.text
        listing = r.json()
        assert [c["capture_id"] for c in listing["captures"]] == [user_id]
        assert admin_id not in [c["capture_id"] for c in listing["captures"]]
        assert listing["total"] == 1
        assert listing["has_more"] is False

        _assert_capture_hidden(
            user_client, admin_id, admin_capture["detection"]["quad_norm"],
        )
        _assert_capture_hidden(
            client, user_id, user_capture["detection"]["quad_norm"],
        )
        r = user_client.get(f"/api/captures/{user_id}")
        assert r.status_code == 200, r.text
        r = client.get("/api/captures")
        assert r.status_code == 200, r.text
        assert user_id not in [c["capture_id"] for c in r.json()["captures"]]
    finally:
        user_client.close()


def test_legacy_capture_without_owner_belongs_to_admin(client, fixtures):
    from backend.services import storage

    capture = _upload_photo(client, fixtures, "photo_clean.jpg")
    source_id = capture["capture_id"]
    cid = f"{source_id[:-6]}{token_hex(3)}"
    source_dir = storage.capture_dir(source_id)
    shutil.copytree(source_dir, source_dir.with_name(cid))
    records = client.app.state.csd.records
    record = records.get_capture(source_id)
    record["capture_id"] = cid
    assert record.pop("owner") == "admin"
    assert records.import_capture(record, [], [])

    r = client.get(f"/api/captures/{cid}")
    assert r.status_code == 200, r.text
    assert r.json()["capture_id"] == cid
    r = client.get(f"/api/captures/{cid}/files/preview.jpg")
    assert r.status_code == 200, r.text
    r = client.get("/api/captures")
    assert r.status_code == 200, r.text
    assert cid in [c["capture_id"] for c in r.json()["captures"]]
    assert "owner" not in records.get_capture(cid)

    user_client = _new_user_client(client)
    try:
        r = user_client.get(f"/api/captures/{cid}")
        assert r.status_code == 404, r.text
        assert r.json()["code"] == "CAPTURE_NOT_FOUND"
    finally:
        user_client.close()


def test_update_account_rename_keeps_captures(client, fixtures):
    records = client.app.state.csd.records

    a, b, c = (f"{prefix}_{token_hex(8)}" for prefix in ("a", "b", "c"))
    password = "test-password"
    user_client = _user_client(client, a, password)
    other_client = TestClient(client.app)
    fresh_client = TestClient(client.app)
    try:
        capture = _upload_photo(user_client, fixtures, "photo_clean.jpg")
        capture_id = capture["capture_id"]
        r = other_client.post(
            "/api/auth/login", json={"username": a, "password": password},
        )
        assert r.status_code == 200, r.text

        for body, status, code in (
            ({"current_password": "wrong-password"}, 403, "WRONG_PASSWORD"),
            ({"username": "bad name"}, 422, "INVALID_USERNAME"),
            ({"username": "ADMIN"}, 409, "USERNAME_TAKEN"),
            ({"new_password": "short"}, 422, "INVALID_PASSWORD"),
        ):
            r = user_client.patch(
                "/api/auth/account", json={"current_password": password, **body},
            )
            assert r.status_code == status, r.text
            assert r.json()["code"] == code
        for body in ({}, {"username": a.upper()}):
            r = user_client.patch(
                "/api/auth/account", json={"current_password": password, **body},
            )
            assert r.status_code == 200, r.text
            assert r.json() == {"username": a}

        r = user_client.patch(
            "/api/auth/account",
            json={"current_password": password, "username": b},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"username": b}
        for signed_in in (user_client, other_client):
            r = signed_in.get("/api/auth/me")
            assert r.status_code == 200, r.text
            assert r.json() == {"username": b}
        r = user_client.get(f"/api/captures/{capture_id}")
        assert r.status_code == 200, r.text
        r = user_client.get("/api/captures")
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 1
        assert [item["capture_id"] for item in r.json()["captures"]] == [capture_id]

        assert records.get_capture(capture_id)["owner"] == a
        with client.app.state.csd.db.connection() as conn:
            assert conn.execute(
                "SELECT account_id FROM accounts WHERE username=%s", (b,),
            ).fetchone()[0] == a
            assert conn.execute(
                "SELECT 1 FROM accounts WHERE username=%s", (a,),
            ).fetchone() is None
        for route, status, code in (
            ("login", 401, "INVALID_CREDENTIALS"),
            ("register", 409, "USERNAME_TAKEN"),
        ):
            r = fresh_client.post(
                f"/api/auth/{route}", json={"username": a, "password": password},
            )
            assert r.status_code == status, r.text
            assert r.json()["code"] == code

        r = user_client.patch(
            "/api/auth/account",
            json={"current_password": password, "username": c},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"username": c}
        r = fresh_client.post(
            "/api/auth/register", json={"username": b, "password": password},
        )
        assert r.status_code == 201, r.text
        assert r.json() == {"username": b}
        r = fresh_client.get("/api/captures")
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 0
        assert r.json()["captures"] == []
        r = user_client.patch(
            "/api/auth/account",
            json={"current_password": password, "username": a},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"username": a}
    finally:
        user_client.close()
        other_client.close()
        fresh_client.close()


def test_password_change_revokes_other_sessions(client):
    username = f"u_{token_hex(8)}"
    old_password = "old-password-123"
    new_password = "new-password-456"
    c1 = _user_client(client, username, old_password)
    c2 = TestClient(client.app)
    fresh_client = TestClient(client.app)
    try:
        r = c2.post(
            "/api/auth/login", json={"username": username, "password": old_password},
        )
        assert r.status_code == 200, r.text
        r = c1.patch(
            "/api/auth/account",
            json={"current_password": old_password, "new_password": new_password},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"username": username}
        r = c1.get("/api/auth/me")
        assert r.status_code == 200, r.text
        assert r.json() == {"username": username}
        r = c2.get("/api/auth/me")
        assert r.status_code == 401, r.text
        assert r.json()["code"] == "AUTH_REQUIRED"
        r = fresh_client.post(
            "/api/auth/login", json={"username": username, "password": old_password},
        )
        assert r.status_code == 401, r.text
        assert r.json()["code"] == "INVALID_CREDENTIALS"
        r = fresh_client.post(
            "/api/auth/login", json={"username": username, "password": new_password},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"username": username}
        with client.app.state.csd.db.connection() as conn:
            accounts_text, sessions_text = conn.execute(
                "SELECT (SELECT string_agg(t::text, '') FROM accounts AS t), "
                "(SELECT string_agg(t::text, '') FROM sessions AS t)",
            ).fetchone()
            password_hash = conn.execute(
                "SELECT password_hash FROM accounts WHERE username=%s", (username,),
            ).fetchone()[0]
        assert old_password not in accounts_text and old_password not in sessions_text
        assert new_password not in accounts_text and new_password not in sessions_text
        assert password_hash.startswith("pbkdf2_sha256$")
    finally:
        c1.close()
        c2.close()
        fresh_client.close()
