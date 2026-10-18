# CardioSentry Web Application

Last verified against the tree: **2026-10-16**.

> This is the local JSON-storage variant of `../cardiosentry-application/` (the PostgreSQL build), kept for presentation hosting; its on-disk format is the one the PostgreSQL build's `scripts/import_filesystem.py` imports.

An **instrument, not a product**: a password-account web app that puts a real
smartphone photograph of a real printed 12-lead ECG sheet into the CardioSentry
image-space multi-label classifier through a preprocessing chain that
**byte-for-byte mirrors the training pipeline**, and records everything about
how that happened — original, detected quad, corrected sheet, exact model
input, the model's served sigmoid scores, thresholds, timing, and versions.

It answers one question: *what does the model do when the input is a real
photograph instead of a synthetic render?* Everything else follows from that.
Full design rationale: [`CARDIOSENTRY_WEB_APP_PLAN.md`](../CARDIOSENTRY_WEB_APP_PLAN.md).

## Run it

```bash
cd cardiosentry-application-local

# 1. backend deps (system python3) + Tesseract, which the default ECG gate
#    runs as a subprocess
python3 -m pip install --user --break-system-packages -e '.[dev]'
sudo apt install tesseract-ocr

# 2. no database: records and accounts are JSON files under captures/

# 3. weights (gitignored training artifacts — copy from the research tree)
cp ../prototype-results/new_runs/convnext_tiny_v1_rfpn_clean12_colab_a100_seed42/convnext_tiny_rfpn/inference.pt \
   models/weights/convnext_tiny_rfpn_clean12_inference.pt
cp ../prototype-results/convnext_v1_base_rfpn_clean12_colab_a100_seed42/inference.pt \
   models/weights/convnext_v1_base_rfpn_clean12_inference.pt
cp ../prototype-results/new_runs/convnext_tiny_v1_rfpn_clean12_ecg_gate_v1_seed42/inference_with_gate.pt \
   models/weights/convnext_tiny_rfpn_ecg_gate_v1.pt     # learned ECG gate (optional)
cp ../prototype-results/NEW_convnext_v2_tiny_V1/best.pt models/weights/convnextv2_tiny_v1img_v1.pt
cp ../prototype-results/hybrid_v1/resnet50_hires/weights/best.pt models/weights/resnet50_hires.pt
cp ../prototype-results/hybrid_v1/resnet50_dual/weights/best.pt  models/weights/resnet50_dual.pt
cp ../prototype-results/v1/resnet50/weights/best.pt              models/weights/resnet50_v1.pt

# 4. self-checks: preprocess parity vs the training pipeline + model parity
python3 -m pytest -q
python3 scripts/verify_model.py

# 5. frontend build (needs Node ≥ 20)
(cd frontend && npm install && npm run build)

# 6. serve API + frontend on the LAN (single process, same origin)
python3 -m backend.main
```

No database server is needed. Records and accounts are JSON files under
`CARDIOSENTRY_DATA_DIR` (default `captures/`), written atomically (temp file +
`os.replace`). The server is a single process (one worker); one in-process
lock serialises read-modify-write of each `capture.json`, so do not run two
servers, or `scripts/reprocess.py`, against the same folder at once.

The terminal prints every LAN URL and a QR code. On the phone (same Wi-Fi),
open `http://<laptop-ip>:8000` → *Sign in* or *Create account* → *Take photo*.
The camera hand-off uses `<input capture>` which works over plain HTTP;
live `getUserMedia` preview and
PWA install arrive with HTTPS (`scripts/make_cert.sh`, plan §15.3).

## Set up on another computer

The steps below take a fresh machine from `git clone` to a running server.
The app was developed on Linux; macOS should work the same way, and on Windows
use WSL2 (the scripts are bash and `models/active.yaml` is a symlink).

**Prerequisites:** Git, Python ≥ 3.12 with pip, Node.js ≥ 20 with npm and
Tesseract. No database server. The weights alone take 2.6 GB of disk; for
Grad-CAM memory use see §Memory.

**What the repository does *not* contain:** model weights (`models/weights/`,
2.6 GB), `.env`, `captures/` (records, accounts and images — PHI) and
`certs/`. You copy or create these yourself.

```bash
# 1. get the tree (this variant lives next to ../cardiosentry-application/)
cd cardiosentry-application-local

# 2. Python dependencies. Linux: install the CPU-only PyTorch wheels first,
#    or pip pulls the multi-GB CUDA build. Skip that line on macOS.
python3 -m pip install --user --break-system-packages torch torchvision \
    --index-url https://download.pytorch.org/whl/cpu
python3 -m pip install --user --break-system-packages -e '.[dev]'
# (--break-system-packages is for Debian/Ubuntu system Python. A virtualenv
#  also works: python3 -m venv .venv && . .venv/bin/activate, then drop
#  --user --break-system-packages from both commands.)
# Tesseract for the default ECG gate (macOS: brew install tesseract)
sudo apt install tesseract-ocr

# 3. no database: records and accounts are JSON files under captures/

# 4. settings (optional): .env is gitignored
cp .env.example .env
chmod 600 .env
# optionally set CARDIOSENTRY_PRIVACY_CONTROLLER / _CONTACT (see .env.example)

# 5. weights: copy ALL .pt files from an existing install (or the
#    research tree, see §Run it step 3). Startup validates every descriptor in
#    models/, so one missing file stops the server.
mkdir -p models/weights
rsync -av --progress <old-host>:<path>/cardiosentry-application-local/models/weights/ models/weights/

# 6. frontend
(cd frontend && npm ci && npm run build)

# 7. checks: the self-check compares scores with the descriptor's verify block
python3 scripts/verify_model.py
python3 -m pytest -q                  # optional, takes minutes on CPU

# 8. serve
python3 -m backend.main
```

Each weight file is checked against its descriptor's `expected_sha256` at
startup. A corrupt or partial copy fails with a hash-mismatch message; copy it
again rather than editing the hash. Every descriptor in `models/` needs its
weight file:

| descriptor | weight file |
|---|---|
| `convnext_v1_base_clean12` | `convnext_v1_base_clean12_best.pt` |
| `convnext_tiny_rfpn_clean12` | `convnext_tiny_rfpn_clean12_inference.pt` |
| `convnext_v1_base_rfpn_clean12` | `convnext_v1_base_rfpn_clean12_inference.pt` |
| `convnextv2_tiny_v1img_v1` | `convnextv2_tiny_v1img_v1.pt` |
| `efficientnetv2_s_cbam_nat768` | `efficientnetv2_s_cbam_nat768.pt` |
| `efficientnetv2_s_nat768` | `efficientnetv2_s_nat768.pt` |
| `resnet50_cbam_nat768` | `resnet50_cbam_nat768.pt` (also used by the test suite) |
| `resnet50_dual` | `resnet50_dual.pt` |
| `resnet50_hires` | `resnet50_hires.pt` |
| `resnet50_v1` | `resnet50_v1.pt` |

**First sign-in.** With no `accounts.json`, the first boot creates the account
`admin` with password `admin` and logs a WARNING. Sign in and change the
password at once under **Settings**.

**Phone access.** The phone and computer must be on the same Wi-Fi. If a
firewall is active, open the port (Ubuntu: `sudo ufw allow 8000/tcp`). For
HTTPS (live camera preview, PWA install), install
[mkcert](https://github.com/FiloSottile/mkcert), run `./scripts/make_cert.sh`,
and start with the `uvicorn … --ssl-keyfile` command printed in that script.
The certificate is issued for the new machine's LAN IP, so run it there.

**Choosing the served model.** `models/active.yaml` is a symlink in git. If a
checkout turns it into a plain text file (Windows without symlink support),
set `CARDIOSENTRY_ACTIVE_MODEL=<model id>` in `.env` instead.

**Optional: move existing records.** Accounts, captures and runs all live in
`captures/`. Copy the whole folder with both servers stopped, **before the new
install's first boot** (otherwise the first boot seeds a fresh
`accounts.json`). The folder is PHI: move it over an encrypted channel and
delete the copies afterwards.

```bash
# old machine (server stopped)
tar czf captures.tgz captures/

# new machine: after step 5, before step 8
tar xzf captures.tgz
```

Account passwords move with `accounts.json`.
## What it does, stage by stage

```
upload ──▶ ingest ──▶ ECG gate ──▶ detect ──▶ corner edit ──▶ rectify ──▶ preprocess ──▶ predict
            (bytes,    (not an ECG: (OpenCV     (4 draggable    (homography   (THE training   (sigmoid,
             EXIF,     422, nothing quad +      handles,        to 1650×1275,  chain: PIL      per-class
             sha256)   stored)      fallbacks)  loupe)          +18px margin)  BICUBIC to the  thresholds)
                                                                             model geometry,
                                                                             q95 JPEG)
```

The **ECG gate** (`services/ecg_gate.py`, `models/gates/*.yaml`, setting
`CARDIOSENTRY_ECG_GATE`) checks the whole oriented upload before detection. The
default, `ocr_lead_labels_v1`, runs Tesseract over the photo after removing
everything that is not character-sized and accepts it when at least 4 of the
printed lead labels aVR, aVL, aVF, V1–V6 are read (~2–4 s; EEG printouts and
other non-ECGs read at most 2). Otherwise the upload returns `422 NOT_AN_ECG`,
its folder is removed and no record is written, so the corner editor and the
model are never reached; the screen tells the user to upload an ECG with its
lead labels visible, or to move closer if it is one. Accepted captures store
the labels read in `record.ecg_gate`. Labels must be legible, so a sheet filling
~10% of the frame (test fixture `photo_small.jpg`) is rejected. Setting
`CARDIOSENTRY_ECG_GATE=convnext_tiny_rfpn_ecg_gate_v1` switches to the learned
gate (a head on a frozen clean12 ConvNeXt-V1 Tiny + RFPN; it lets EEG printouts
through). `models/README.md` §ECG gate has the measurements.

After prediction, runs from a model with reviewed rules (the clean12
ConvNeXt-V1 models and the earlier ConvNeXt-V2 V1 model) also pass their final
served positives into a versioned **Urgency and Recommended Next Steps**
decision-support layer with four tiers of increasing urgency: **Green**
(read as Normal, no extra action from this result), **Yellow**
(routine clinician review), **Orange** (same-day medical assessment), and
**Red** (call emergency services now). Each flagged condition has a baseline
tier; optional symptom, age-group, and history questions can raise it;
emergency symptoms override model findings; and clinically relevant
multi-label combinations use the highest applicable tier. The browser never
submits findings—the backend resolves the stored run and re-applies its
suppression policy. Rules and sources are documented in
[`docs/clinical-guidance.md`](docs/clinical-guidance.md).

Every arrow is a recorded transformation, persisted per capture as files:

```
captures/
├── accounts.json       # users + session-token hashes (schema_version 1)
└── 2026-08-23/2026-08-23_014215_a3f9c1/
    ├── capture.json        # the capture record (owner, EXIF, quad, privacy ack…)
    ├── original.jpg        # uploaded bytes (GPS EXIF stripped by default, recorded)
    ├── preview.jpg         # ~1280px, phone UI only — never for inference
    ├── overlay.jpg         # preview + detected/final quad — debugging aid
    ├── corrected.png       # 1686×1311 rectified sheet, LOSSLESS
    ├── model_input.png     # the active model's geometry (768×1024 by default),
    │                       #   LOSSLESS, exactly the tensorized pixels
    ├── predictions/        # <run_id>.json — one per prediction run
    └── explain/            # xai_<stamp>_<method>_<model>/ — one per attribution run
                            #   record.json (not file-served)
                            #   <method>_<LABEL>_{heatmap,overlay}.png
                            #   raw.npz (optional)
```

**Records (JSON files):** `RecordStore` reads and writes `capture.json`,
`predictions/<run_id>.json` and `explain/<explain_id>/record.json`;
`AccountStore` owns `accounts.json`. Writes are atomic.

New captures record the creator's permanent account id in the record's
`owner`: the username at registration, immutable on rename.
`owner_of(record)` maps a missing or null `owner` to the `admin` account id,
even after it renames itself. Account ids are never reused and stay reserved
names. Listing scans every `capture.json`, filters by owner, then pages.
`owned_capture` checks the record's owner against
`current_account(request).account_id`, never `.username`.

### Explainability — where the model looked

A fourth, opt-in stage runs on the **same stored `model_input.png`** the scores
came from, so a map and a score always describe the same pixels:

| method | what it answers | resolution | cost (CPU, 768×1024) |
|---|---|---|---|
| **Grad-CAM** | which *region* of the sheet | the final feature grid — a lead, not a segment | one forward plus a partial backward per served label |

Grad-CAM is the only method served. It defaults to the whole head, and
`GET /api/config` quotes the pass count before the wait. Runs of the removed
Integrated Gradients and Jacobian methods already stored under a capture still
list and serve, but new ones are refused with a 422.

### Memory — the thing that will bite you

Enabling autograd on this model at 768×1024 from the input costs **~2.3 GB of
stored activations**, against 84 MB for the same forward under `no_grad`. On a
laptop serving the app with a browser open (~2.6 GB free, no swap) that is not
"slow": it is the OOM killer taking the whole server down mid-request.

**Grad-CAM records no graph before its target layer.** Its gradient is
`dlogit/dA` for `A` the target layer's output, so nothing upstream appears in
it. The forward runs under `no_grad`, and a hook on the target detaches `A`
into a leaf and switches recording on for the remainder. Same derivative,
**bit-identical CAMs**, and `+2307 MB` becomes `+44 MB`. If even that will not
fit, the request is **refused with a 507 naming both numbers** rather than
gambling on the OOM killer.

The one thing every run reports, and the point of the feature:

- **`header_frac` / `lift`** — how much attribution mass landed on the printed
  ID/Age/Sex block, over that block's share of the sheet *area*. The record ID
  printed there separates STEMI **exactly** in the synthetic corpus, and the
  `nat768` checkpoints trained with it painted out while the app deliberately
  does not redact an upload. `lift ≈ 1` is a fair share; `lift ≥ 2` raises a
  loud badge in the UI and a caveat in the record.

```bash
curl -c jar -H 'Content-Type: application/json' \
     -d '{"username":"admin","password":"admin"}' localhost:8000/api/auth/login
curl -b jar -X POST localhost:8000/api/captures/$CID/explain \
     -H 'Content-Type: application/json' -d '{"method":"gradcam"}'
curl -b jar localhost:8000/api/models/active/layers  # Grad-CAM target candidates
```

Attribution runs are **derived data** — every one is reproducible from
`model_input.png` plus the parameters in its stored record — so deleting one
removes its folder (including its `record.json`) outright rather than moving it to `_trash/`.
Re-rectifying a capture marks its existing runs `stale`: they explain pixels
the capture no longer has. Fetch a record with
`GET /api/captures/{id}/explain/{xid}`; the old
`GET …/explain/{xid}/files/record.json` returns `404 UNKNOWN_FILE`.

`predict` operates on the persisted `model_input.png`, so the **same real
photograph** can be re-scored by a different `.pt` with a bit-identical input:

```bash
python3 scripts/reprocess.py --all --model resnet50_dual
python3 scripts/export_dataset.py --out captures_export.csv
```

## The non-negotiables (why this code looks the way it does)

- **The original is sacred.** Uploaded bytes are written unmodified before
  anything else touches them; all geometry applies to the full-resolution
  oriented original.
- **Preprocessing lives in exactly one module** — `backend/services/preprocess.py`,
  importable by API and scripts. It reproduces the training chain exactly
  (PIL BICUBIC — *not* OpenCV — for the final resize, in-memory q95 JPEG
  round-trip, ToTensor, ImageNet normalize), and `tests/test_preprocess_parity.py`
  proves it against the actual training code to `1e-6` before any real capture.
- **The model is data, not code.** One `.pt` + one YAML descriptor
  (`models/*.yaml`); architectures are vendored verbatim under `backend/arch/`
  with provenance. `verify_model.py` catches timm/weights drift.
- **Per-class thresholds are frozen training artifacts**, read from the
  checkpoint or written explicitly in its descriptor; a silent 0.5 default is
  refused at startup.
- **Independent sigmoid heads**, displayed in checkpoint order, never argmax
  and never sorted by score. A descriptor may temporarily suppress selected
  heads at the serving boundary without changing the checkpoint; the UI says
  "Model score", never a probability of disease.
- **Warn, never block** on image quality: a rejected photo is a missing data
  point.
- **Blind mode + reference labels** (§17.6): the app records what the ECG
  actually shows, and can hide scores until labels are entered, so the dataset
  is defensible.
- **Records live next to their images:** JSON files under `captures/`, through
  `AccountStore` and `RecordStore`, written atomically with
  `storage.atomic_write_json`.

## Models shipped

| id | checkpoint | input (h×w) | call style | purpose |
|---|---|---|---|---|
| `convnext_tiny_rfpn_clean12` *(active)* | convnext_v1_rfpn_clean12 | 768×1024 | `tensor` | ConvNeXt-V1 Tiny + Residual FPN (`CS_FUSION=rfpn`) trained on the HEEDB clean12 renders; 12 heads, all served, no gate head. Test pathology macro AP 0.923 |
| `convnext_v1_base_rfpn_clean12` | convnext_v1_rfpn_clean12 | 768×1024 | `tensor` | ConvNeXt-V1 Base + Residual FPN (`CS_FUSION=rfpn`) trained on the HEEDB clean12 renders; 12 heads, all served. Test pathology macro AP 0.923 |
| `convnext_v1_base_clean12` | convnext_v1_clean12 | 768×1024 | `tensor` | the same run recipe without the FPN neck (plain V1 Base); 12 heads, all served |
| `convnextv2_tiny_v1img_v1` | convnextv2_v1img | 768×1024 | `tensor` | ConvNeXt-V2 Tiny trained on the clean-only V1 image corpus. Twelve checkpoint heads; nine currently served, with TInv, LQT, and PRWP suppressed reversibly |
| `efficientnetv2_s_nat768` | baselines_v2 | 768×1024 | `tensor` | round-3 **plain baseline** — the unmodified backbone at the sheet's native aspect. Val macro-AUPRC 0.9501 |
| `efficientnetv2_s_cbam_nat768` | hybrids_v2 | 768×1024 | `tensor` | same backbone and geometry, plus CBAM (0.9571) |
| `resnet50_cbam_nat768` | hybrids_v2 | 768×1024 | `tensor` | same protocol, geometry and attention block, other backbone (0.9570) |
| `resnet50_hires` | hybrid_v1 | 768×768 | `view_dict` | round-2 control |
| `resnet50_dual` | hybrid_v1 | 384×384 + 768×768 | `view_dict` | dual-resolution hybrid |
| `resnet50_v1` | runs_v1 | 384×384 | `tensor` | round-1 single stream (exercises the F3 adapter) |

The active model is a **rectangle at the sheet's own aspect**, not a square: the
768×768 geometry squeezed the time axis by 22% and spent ~27% of the vertical
budget on blank paper.

The active checkpoint has twelve logits in this order: `NORM`, `SB`, `STACH`,
`LBBB`, `LQT`, `AF`, `AFL`, `3AVB`, `2AVB`, `1AVB`, `STEMI`, `STE`, all served.
`convnextv2_tiny_v1img_v1` withholds `TInv`, `LQT`, and `PRWP` from scores,
thresholds, positives, reference labels, and explanations through its
descriptor's `output.suppressed_labels`; the weights and head order are
unchanged, and removing a label from that list and restarting returns it for
future runs without retraining.

The clean12 runs used clean rendered ECG images rather than real phone
photographs, so their scores remain research outputs under the same real-photo
calibration caveat as the earlier models. The three older round-3 descriptors still share
protocol fingerprint `36988c5e0ba5d72d` and remain available for controlled
comparison; their documented header-redaction gap is covered in
`models/README.md`.

The ECG gates (`ocr_lead_labels_v1`, default, and `convnext_tiny_rfpn_ecg_gate_v1`)
are not diagnostic models and are not listed by `/api/models`; see
`models/README.md` §ECG gate.

## Security & privacy (read before serving)

- Bind `0.0.0.0` only on networks you own; on shared Wi-Fi use
  `CARDIOSENTRY_LOCAL_ONLY=true` or set `CARDIOSENTRY_APP_TOKEN`.
- No port forwarding, no public tunnels: password accounts are for trusted LAN
  use, not a public deployment.
- Sign in or register before using the app; the topbar **Settings** button
  (or mobile hamburger menu) opens the **Settings** screen (`#/settings`), which contains username/password editing and **Sign out**. Every `/api/*`
  path except health, config, auth login,
  register and logout requires a valid session (`401 AUTH_REQUIRED` otherwise).
  The optional shared token gate still applies in addition, even to those
  session-public routes.
- Capture routes are owner-scoped, including files, guidance and explanations.
  Another user's capture returns `404 CAPTURE_NOT_FOUND`; lists are filtered
  before paging. Admin sees only its own captures plus legacy captures without
  an owner, not every user's scans.
- Startup creates **`admin` / `admin`** only if the permanent `admin` account id
  is missing and logs a WARNING; an existing account is never overwritten or
  recreated after a rename. **Change the default admin password first**: sign
  in, click the topbar username, and use the Account screen to set a new password.
  The screen changes the username and/or password through
  `PATCH /api/auth/account`, always requiring the current password. A rename
  keeps all of the account's sessions; a password change signs out its other
  sessions, keeping the current one.
- `captures/accounts.json` holds permanent account ids, salted PBKDF2-SHA256
  password hashes (600,000 iterations) and SHA-256 session-token hashes, not
  plaintext passwords or tokens. It is rewritten atomically; expired sessions
  are pruned on write. A corrupt `accounts.json` refuses startup.
- Back up by copying the whole `captures/` folder (with the server stopped):
  it contains `accounts.json` (credential/session hashes), the health records
  and the images. Protect every copy as PHI.
- Losing `accounts.json` loses accounts, sessions and reserved ids; startup
  then seeds the default admin again and old account ids can be claimed by
  new accounts. Restore it from backup before serving again.
- Sessions last **30 days** and survive server restarts. The
  `cardiosentry_session` cookie is HttpOnly and SameSite=Lax. It is Secure only
  over HTTPS, deliberately not over plain HTTP so LAN sign-in works. Plain HTTP
  does not encrypt passwords or cookies; use HTTPS on networks you do not trust.
- `captures/` is gitignored **before the first run** — photos may carry
  printed patient identifiers. GPS EXIF is stripped by default (§13.4).
- `.pt` loading uses `torch.load(weights_only=False)` — acceptable only
  because the checkpoints are self-produced and sha-pinned; never accept a
  `.pt` through the API.
- Records stay in this machine's `captures/` folder; there is no network
  database and no outbound connection.

### Accounts API

All five routes are implemented in `backend/api/auth.py`:

| Method & path | Session | Success |
|---|---|---|
| `POST /api/auth/register` | Public | `201 {"username": "<lowercased>"}` + session cookie (signed in immediately) |
| `POST /api/auth/login` | Public | `200 {"username": "<lowercased>"}` + session cookie |
| `POST /api/auth/logout` | Public | `200 {"logged_out": true}`; revokes session and clears cookie |
| `GET /api/auth/me` | Required | `200 {"username": "<lowercased>"}`; otherwise `401 AUTH_REQUIRED` |
| `PATCH /api/auth/account` | Required; current password required | `200 {"username": "<lowercased>"}`; changes username and/or password, retaining the current session |

Login/register accept JSON `{"username": "...", "password": "..."}`. Usernames
are trimmed, lowercased and use 3–32 letters, numbers, dots, dashes or underscores;
new passwords must be 8–128 characters. The seeded `admin` password remains
valid for login despite being shorter. Curl callers must keep the login cookie
(`-c jar`) and send it on subsequent private requests (`-b jar`), as shown above.

Account edits accept JSON `{"current_password": "...", "username": "...",
"new_password": "..."}`. Omit `username` or `new_password` (or send `null`) to
keep that field unchanged; the username/password rules above still apply.
An incorrect current password returns `403 WRONG_PASSWORD`; invalid new values
return `422 INVALID_USERNAME` or `422 INVALID_PASSWORD`; a taken username or
another account's reserved id returns `409 USERNAME_TAKEN`. Renaming back to
your own account id is allowed. No new cookie is needed after an edit.

### Data Privacy Notice (Philippines, RA 10173)

An ECG photograph is health information — *sensitive personal information*
under the Data Privacy Act of 2012. The app ships an in-app **Data Privacy
Notice** (`#/privacy`, linked in the footer of every screen), and the capture
screen hides *Take photo* / *Choose photo* until the current notice version is
accepted. Each upload records the accepted version in
the capture record's `session.privacy_notice_ack` as the proof of consent
(`null` = an API or script caller that never saw it).

The current `PRIVACY_NOTICE_VERSION` is `2026-10-16.1`; the notice also describes
records and accounts stored as files in the captures folder, image files,
credential hashes, sign-in sessions, permanent account ids, capture ownership,
signing out other devices when a password changes, and that uploads the ECG
gate rejects are not stored.

Before photographing anyone else's ECG, the operator must:

- set `CARDIOSENTRY_PRIVACY_CONTROLLER` and `CARDIOSENTRY_PRIVACY_CONTACT`
  (the notice shows "Not yet configured" until then);
- honour what the notice promises: erase a capture permanently on request
  (in-app delete only moves its folder, records included, to
  `captures/_trash/`), delete everything when the study ends, never copy data
  off the machine without consent, and report a breach to the National Privacy
  Commission within 72 hours;
- obtain research-ethics approval where the institution requires it.

The notice states facts about this code (GPS stripped, nothing sent off the
machine, guidance answers not saved, account hashes and capture ownership).
Change any of those and update
`frontend/src/components/PrivacyNotice.tsx` and bump `PRIVACY_NOTICE_VERSION`
in `backend/api/config.py`, which re-prompts every browser.

For permanent erasure, first trash the capture in the app, then remove its
`captures/_trash/<date>/<capture_id>/` folder (or delete
`captures/<date>/<capture_id>/` directly). The folder holds all of the
capture's records, so nothing else needs deleting. Exports and backup copies
of `captures/` remain the controller's erasure/retention responsibility.

## Testing

`python3 -m pytest -q --collect-only` collects **246 cases / 117 top-level test
functions**. The suite runs the real model and uses no database.

| Test file | Cases | Functions |
|---|---:|---:|
| `test_accounts.py` | 2 | 2 |
| `test_api_smoke.py` | 14 | 14 |
| `test_detect.py` | 9 | 9 |
| `test_ecg_gate.py` | 8 | 5 |
| `test_explain.py` | 19 | 19 |
| `test_guidance.py` | 182 | 57 |
| `test_model_descriptor.py` | 4 | 4 |
| `test_preprocess_parity.py` | 8 | 7 |

`tests/conftest.py` sets `CARDIOSENTRY_DATA_DIR` to
`$TMPDIR/cardiosentry_local_test_captures` before importing `backend.*`, asserts
that is the data dir and wipes it at import (fresh accounts and records each
session), so tests
never touch the real `captures/`. Never point tests at production data.

The suite pins `resnet50_cbam_nat768` independently of the active model and runs
real CPU inference; the full suite takes minutes. The shared `client` is logged
in as admin; auth/logout tests use `anon_client` instead of logging it out.
Store access is `client.app.state.csd.{records,accounts}`.


## Layout

```
backend/   FastAPI app: api/ (routes) · services/ (ingest, detect, rectify,
           records, accounts, preprocess, quality, registry, runner, storage, explain) · arch/
           (vendored model architectures) · schemas/ (pydantic records)
frontend/  Vite + React 18 + TS + Tailwind CSS v4 PWA (zero client-side image processing)
models/    descriptors + weights
scripts/   verify_model.py · reprocess.py · export_dataset.py · make_cert.sh
tests/     accounts · preprocess parity (★) · detection
           · API smoke · explainability · clinical guidance (fixtures included)
```

| Important service | Owns |
|---|---|
| `backend/services/accounts.py` | `accounts.json` users/sessions, salted PBKDF2-SHA256 (600k), 30-day sessions, missing admin creation at startup, immutable account ids and `owner_of` |
| `backend/services/records.py` | JSON capture/prediction/explain records, owner-filtered listing, lock-serialised updates, trash moves |
| `backend/services/storage.py` | image/binary directories, ids, file-serving whitelists, `atomic_write_json` and moving folders to `_trash/` |

## Known v1 limits (all deliberate — see the plan)

- Records are JSON files on disk with one in-process lock: single server
  process only, no concurrent writers from other processes.
- No waveform digitization, no queue (single process, CPU inference ~0.5–2 s),
  no ONNX/TorchScript (fidelity over speed); the service worker only registers
  once HTTPS is set up (phase 3, `scripts/make_cert.sh`).
- Scores are **not calibrated** on real photographs; threshold-derived labels
  are provisional by design (§17.5).
- Urgency guidance is a screening aid, not a diagnosis or treatment plan. It is
  deliberately available only for reviewed models with their exact served
  label/suppression policy; a new model or policy change has no guidance until
  its rule set is reviewed and added.
- Grad-CAM runs synchronously in the request — there is no job queue — but it
  is one forward plus a partial backward per label, so seconds, not minutes.
