# CardioSentry Web Application

Last verified against the tree: **2026-10-08**.

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
cd cardiosentry-application

# 1. backend deps (system python3; includes psycopg[binary,pool])
python3 -m pip install --user --break-system-packages -e '.[dev]'

# 2. local PostgreSQL (start the existing container if stopped)
docker start postgres-db-cardiosentry
# Configure DATABASE_URL or CARDIOSENTRY_DATABASE_URL in .env (see below).
# Pre-PostgreSQL JSON was imported on 2026-10-08 and archived.
# Restore into an empty database: see §Security & privacy, "Legacy JSON archive".

# 3. weights (gitignored training artifacts — copy from the research tree)
cp ../prototype-results/NEW_convnext_v2_tiny_V1/best.pt models/weights/convnextv2_tiny_v1img_v1.pt
cp ../prototype-results/hybrid_v1/resnet50_hires/weights/best.pt models/weights/resnet50_hires.pt
cp ../prototype-results/hybrid_v1/resnet50_dual/weights/best.pt  models/weights/resnet50_dual.pt
cp ../prototype-results/v1/resnet50/weights/best.pt              models/weights/resnet50_v1.pt

# 4. self-checks: preprocess parity vs the training pipeline + model parity
python3 -m pytest -q
python3 scripts/verify_model.py

# 5. frontend build (needs Node ≥ 18)
(cd frontend && npm install && npm run build)

# 6. serve API + frontend on the LAN (single process, same origin)
python3 -m backend.main
```

The app requires a local PostgreSQL database. It reads `DATABASE_URL` or
`CARDIOSENTRY_DATABASE_URL` from `.env`; the prefixed name wins if both are
set. Use the connection setting shown in `.env.example`, with the actual
password kept private. The configured target is
`127.0.0.1:5432/cardiosentry (user cardiosentry)`, in
`postgres-db-cardiosentry` (`postgres:16-alpine`). A missing or unreachable
database stops startup before the model loads; remote database hosts are refused.

The legacy import completed on 2026-10-08 and was verified field-for-field:
93 captures, 86 runs and 35 explain records, with no missing or extra ids.
The only difference was stripped EXIF NUL padding in 40 captures; ownership
remains `admin` without backfill, and `created_utc` matches. The source JSON
was moved to the legacy archive. `scripts/import_filesystem.py --data-dir
<extracted archive>` is now the restore path (see §Security & privacy,
**Legacy JSON archive**): run it before the first boot of an empty database.
The importer is idempotent and leaves extracted files untouched; existing
database rows always win, including edited or trashed captures. Check reported
problems before continuing. If an extracted legacy tree contains `accounts.json`,
importing before startup seeds admin preserves its credentials; this archive
contains no account file. New installations with no legacy data need no import.

The terminal prints every LAN URL and a QR code. On the phone (same Wi-Fi),
open `http://<laptop-ip>:8000` → *Sign in* or *Create account* → *Take photo*.
The camera hand-off uses `<input capture>` which works over plain HTTP;
live `getUserMedia` preview and
PWA install arrive with HTTPS (`scripts/make_cert.sh`, plan §15.3).

## What it does, stage by stage

```
upload ──▶ ingest ──▶ detect ──▶ corner edit ──▶ rectify ──▶ preprocess ──▶ predict
            (bytes,    (OpenCV     (4 draggable    (homography   (THE training   (sigmoid,
             EXIF,     quad +      handles,        to 1650×1275,  chain: PIL      per-class
             sha256)  fallbacks)   loupe)          +18px margin)  BICUBIC to the  thresholds)
                                                                  model geometry,
                                                                  q95 JPEG)
```

After prediction, runs from a model with reviewed rules (the clean12
ConvNeXt-V1 Base and the earlier ConvNeXt-V2 V1 model) also pass their final
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

Every arrow is a recorded transformation, persisted per capture. Images and
optional binary attribution arrays stay on disk:

```
captures/2026-08-23/2026-08-23_014215_a3f9c1/
├── original.jpg        # uploaded bytes (GPS EXIF stripped by default, recorded)
├── preview.jpg         # ~1280px, phone UI only — never for inference
├── overlay.jpg         # preview + detected/final quad — debugging aid
├── corrected.png       # 1686×1311 rectified sheet, LOSSLESS
├── model_input.png     # the active model's geometry (768×1024 by default),
│                       #   LOSSLESS, exactly the tensorized pixels
└── explain/            # xai_<stamp>_<method>_<model>/ — one per attribution run
                        #   <method>_<LABEL>_{heatmap,overlay}.png
                        #   raw.npz (optional)
```

**Records (PostgreSQL, schema v1):** `accounts`, `sessions`, `captures`,
`prediction_runs`, `explain_runs`, `schema_migrations`. Capture, prediction and
explain records are JSONB, accessed through `RecordStore`; run rows and the
capture's run-id lists change in one transaction. Images are not in the database.

New captures record the creator's permanent account id in
`captures.record.owner`: the username at registration, immutable on rename.
The indexed `captures.owner_id` is `owner_of(record)`: missing or null `owner`
means the `admin` account id, even after it renames itself. Imported record JSON
is not backfilled; PostgreSQL-incompatible NUL padding is stripped from strings.
Account ids are never reused and stay reserved names. `owned_capture` checks
the live database row against `current_account(request).account_id`, never
`.username`, and requires the image folder to exist.

Legacy `capture.json`, prediction JSON and explain `record.json` were moved
out of `captures/` into the legacy archive. `captures/` now holds only images
and arrays; PostgreSQL is the source of truth for records. The app does not
read or write legacy JSON.

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
removes its database row and files outright rather than moving it to `_trash/`.
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
- **Records have one source of truth:** local PostgreSQL, through `AccountStore`
  and `RecordStore`; the filesystem holds images and binary arrays only.
  `atomic_write_json` and filesystem record readers have been removed.

## Models shipped

| id | checkpoint | input (h×w) | call style | purpose |
|---|---|---|---|---|
| `convnextv2_tiny_v1img_v1` *(active)* | convnextv2_v1img | 768×1024 | `tensor` | ConvNeXt-V2 Tiny trained on the clean-only V1 image corpus. Twelve checkpoint heads; nine currently served, with TInv, LQT, and PRWP suppressed reversibly |
| `efficientnetv2_s_nat768` | baselines_v2 | 768×1024 | `tensor` | round-3 **plain baseline** — the unmodified backbone at the sheet's native aspect. Val macro-AUPRC 0.9501 |
| `efficientnetv2_s_cbam_nat768` | hybrids_v2 | 768×1024 | `tensor` | same backbone and geometry, plus CBAM (0.9571) |
| `resnet50_cbam_nat768` | hybrids_v2 | 768×1024 | `tensor` | same protocol, geometry and attention block, other backbone (0.9570) |
| `resnet50_hires` | hybrid_v1 | 768×768 | `view_dict` | round-2 control |
| `resnet50_dual` | hybrid_v1 | 384×384 + 768×768 | `view_dict` | dual-resolution hybrid |
| `resnet50_v1` | runs_v1 | 384×384 | `tensor` | round-1 single stream (exercises the F3 adapter) |

The active model is a **rectangle at the sheet's own aspect**, not a square: the
768×768 geometry squeezed the time axis by 22% and spent ~27% of the vertical
budget on blank paper.

The active checkpoint has twelve logits in this immutable order: `NORM`, `AF`,
`IAVB`, `LBBB`, `RBBB`, `PAC`, `PVC`, `LAFB`, `LAE`, `TInv`, `LQT`, `PRWP`.
The application currently withholds `TInv`, `LQT`, and `PRWP` from scores,
thresholds, positives, reference labels, and explanations through the model
descriptor's `output.suppressed_labels`. The model weights and head order are
unchanged; removing a label from that list and restarting returns it for future
runs without retraining.

This V1 run used clean synthetic ECG images rather than real phone photographs,
so its scores remain research outputs under the same real-photo calibration
caveat as the earlier models. The three older round-3 descriptors still share
protocol fingerprint `36988c5e0ba5d72d` and remain available for controlled
comparison; their documented header-redaction gap is covered in
`models/README.md`.

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
- The local PostgreSQL `accounts` and `sessions` tables hold permanent account
  ids, salted PBKDF2-SHA256 password hashes (600,000 iterations) and SHA-256
  session-token hashes, not plaintext passwords or tokens. Account edits and
  session revocations use database transactions. Legacy accounts missing an
  `account_id` use their username at import.
- Protect and back up both `captures/` and the database in the Docker volume
  **`postgres-db-cardiosentry-data`**. A database backup can be produced with
  `docker exec postgres-db-cardiosentry pg_dump -U cardiosentry cardiosentry`;
  save its output securely, because it contains health records and credential
  hashes. `pg_dump` does not include image files.
- Losing the volume loses accounts, sessions, reserved ids and all database
  records, while image files survive. The legacy archive can be re-imported
  (pre-migration data only), but cannot recover new records or edits made after
  migration. Without a database backup, startup can seed the default admin
  again and old account ids can be claimed by new accounts. Do not resume
  serving before recovery.
- The database connection is local only (loopback or Unix socket); `.env`'s
  connection URL contains a secret and must not be committed or printed.
  Old application versions expect JSON files, not current database records;
  rolling back code restores neither the archived files nor the database.
- Sessions last **30 days** and survive server restarts. The
  `cardiosentry_session` cookie is HttpOnly and SameSite=Lax. It is Secure only
  over HTTPS, deliberately not over plain HTTP so LAN sign-in works. Plain HTTP
  does not encrypt passwords or cookies; use HTTPS on networks you do not trust.
- `captures/` is gitignored **before the first run** — photos may carry
  printed patient identifiers. GPS EXIF is stripped by default (§13.4).
- `.pt` loading uses `torch.load(weights_only=False)` — acceptable only
  because the checkpoints are self-produced and sha-pinned; never accept a
  `.pt` through the API.
- **Legacy JSON archive:** `~/.local/share/cardiosentry/legacy-json/` holds
  `legacy-json.tar.gz` (214 members with relative `<date>/<id>/…` paths),
  `legacy-json.sha256` (per-file manifest), `legacy-json.tar.gz.sha256`
  (tarball checksum), and `VERIFY.txt` (aggregate verifier output, no PHI).
  The archive contains **personal and health data (PHI)**: EXIF device info,
  sheet ids, annotations, privacy acknowledgements, timestamps and model
  results. The archive directory and its `cardiosentry/` parent are owner-only
  **0700**, and files are **0600**. It is outside the repo and `captures/`,
  never served by the app, and **not encrypted at rest** in this prototype;
  encryption with `age`/`gpg` is a later option only. Neither `pg_dump` nor
  image backups include it; any copy of the archive is also PHI.

  Restore into an empty or lost database **before the app's first boot**.
  Run from the app root in Bash:

  ```bash
  umask 077
  ARCH="$HOME/.local/share/cardiosentry/legacy-json"
  (cd "$ARCH" && sha256sum -c legacy-json.tar.gz.sha256)
  R=$(mktemp -d "$ARCH/restore.XXXXXX")
  tar -xzf "$ARCH/legacy-json.tar.gz" -C "$R"
  (cd "$R" && sha256sum --quiet --strict -c "$ARCH/legacy-json.sha256")
  python3 scripts/import_filesystem.py --data-dir "$R"
  rm -rf -- "$R"
  ```

  The importer remains idempotent; existing database rows win. The restore
  drill imported the same 93 captures / 86 runs / 35 explain records with
  `warnings: 0; problems: 0` and passed the field-for-field verifier.

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

The current `PRIVACY_NOTICE_VERSION` is `2026-10-08.3`; the notice also describes
local PostgreSQL records, image files, credential hashes, sign-in sessions,
permanent account ids, capture ownership and signing out other devices when a
password changes.

Before photographing anyone else's ECG, the operator must:

- set `CARDIOSENTRY_PRIVACY_CONTROLLER` and `CARDIOSENTRY_PRIVACY_CONTACT`
  (the notice shows "Not yet configured" until then);
- honour what the notice promises: erase a capture permanently on request
  (in-app delete only sets `captures.trashed_utc` and moves its folder to
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
`captures/_trash/<date>/<capture_id>/` folder and delete its database records.
Run the following in the `cardiosentry` database, replacing `<capture_id>` with
the exact id; child rows must be removed before the capture row:

```sql
BEGIN;
DELETE FROM explain_runs WHERE capture_id = '<capture_id>';
DELETE FROM prediction_runs WHERE capture_id = '<capture_id>';
DELETE FROM captures WHERE capture_id = '<capture_id>';
COMMIT;
```

**Remove the capture from the legacy archive** if retaining it. After the
app trash, `_trash` folder removal and SQL steps above, run in Bash, replacing
`<capture_id>` with the exact id:

```bash
umask 077
ARCH="$HOME/.local/share/cardiosentry/legacy-json"; CID='<capture_id>'; DAY="${CID:0:10}"
cd "$ARCH"
if tar -tzf legacy-json.tar.gz | grep -q "^$DAY/$CID/"; then
  gunzip legacy-json.tar.gz &&
  tar --delete --wildcards -f legacy-json.tar "$DAY/$CID/*" &&
  gzip -9 legacy-json.tar &&
  grep -vF "  $DAY/$CID/" legacy-json.sha256 > legacy-json.sha256.new &&
  mv legacy-json.sha256.new legacy-json.sha256 &&
  sha256sum legacy-json.tar.gz > legacy-json.tar.gz.sha256
fi
tar -tzf legacy-json.tar.gz | grep -c "$CID"
```

The last command must print **0** (`grep` exits 1 when there are no matches).
Captures created after migration have no archive entries, so the `if` skips
them. `gzip`/`gunzip` keep mode 0600; `umask 077` keeps the new manifest at 0600.

Delete the whole archive once it is no longer needed, for example when the
study ends or once verified database backups exist:

```bash
rm -rf -- "$HOME/.local/share/cardiosentry/legacy-json" && rmdir "$HOME/.local/share/cardiosentry"
```

Until then it retains pre-migration records, and a restore would bring back
erased ones unless they were also removed from the archive. Exports, archive
copies and `pg_dump` backups remain the controller's erasure/retention
responsibility; deleting the local archive does not remove those copies.

## Testing

`python3 -m pytest -q --collect-only` collects **165 cases / 93 top-level test
functions**:

| Test file | Cases | Functions |
|---|---:|---:|
| `test_accounts.py` | 2 | 2 |
| `test_api_smoke.py` | 13 | 13 |
| `test_database.py` | 2 | 2 |
| `test_detect.py` | 9 | 9 |
| `test_explain.py` | 19 | 19 |
| `test_guidance.py` | 108 | 37 |
| `test_model_descriptor.py` | 4 | 4 |
| `test_preprocess_parity.py` | 8 | 7 |

`tests/conftest.py` rewrites the settings URL at import to `<db>_test`
(`cardiosentry_test` here); the session fixture recreates it. `isolated_db`
creates a migrated `<db>_test_unit` (`cardiosentry_test_unit`) for each test
that uses it and drops it afterwards. These fixtures use the `postgres`
maintenance database to create/drop test databases, so the configured role
needs that permission. They never open the real application database. Never
bypass the suffix guards or point tests at production data. Test images live
under `$TMPDIR/cardiosentry_test_captures`, not the real `captures/`.

The suite pins `resnet50_cbam_nat768` independently of the active model and runs
real CPU inference; the full suite takes minutes. The shared `client` is logged
in as admin; auth/logout tests use `anon_client` instead of logging it out.


## Layout

```
backend/   FastAPI app: api/ (routes) · services/ (ingest, detect, rectify,
           db, records, accounts, preprocess, quality, registry, runner, storage, explain) · arch/
           (vendored model architectures) · schemas/ (pydantic records)
frontend/  Vite + React 18 + TS PWA (zero client-side image processing)
models/    descriptors + weights
scripts/   verify_model.py · reprocess.py · export_dataset.py · import_filesystem.py · make_cert.sh
tests/     accounts · database/import · preprocess parity (★) · detection
           · API smoke · explainability · clinical guidance (fixtures included)
```

| Important service | Owns |
|---|---|
| `backend/services/db.py` | local-only psycopg connection pool, startup failures without secrets, versioned `MIGRATIONS` under an advisory transaction lock; append versions, never edit v1 |
| `backend/services/accounts.py` | PostgreSQL accounts/sessions, salted PBKDF2-SHA256 (600k), 30-day sessions, missing admin creation at startup, immutable account ids and `owner_of` |
| `backend/services/records.py` | JSONB capture/prediction/explain records, ownership and live-row queries, locked updates and transactional run indexes, NUL stripping, soft delete and idempotent import |
| `backend/services/storage.py` | image/binary directories, ids, file-serving whitelists and moving folders to `_trash/`; no JSON persistence |

## Known v1 limits (all deliberate — see the plan)

- PostgreSQL holds records; files hold images. The original spec's
  "no relational database" requirement and Q9 in
  `../CARDIOSENTRY_WEB_APP_PLAN.md` are superseded by this migration.
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
# cardiosentry-application
# cardiosentry-application
