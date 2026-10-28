#!/bin/bash
# CardioSentry prototype setup on the ECS (run as root). Idempotent.
set -euo pipefail
BASE=/opt/cardiosentry
APP=$BASE/app

id cardiosentry >/dev/null 2>&1 || useradd --system --home-dir $BASE --shell /usr/sbin/nologin cardiosentry

# Code: HEAD of origin/main
if [ ! -d $APP/.git ]; then
  git clone -q https://github.com/lindtseyyy/cardiosentry-application.git $APP
else
  git -c safe.directory=$APP -C $APP pull -q --ff-only
fi

# Models dir with only the served model + the ECG gate (registry validates every *.yaml it finds)
M=$BASE/models
mkdir -p $M/gates
ln -sfn $BASE/weights $M/weights
ln -sfn $APP/models/convnext_tiny_rfpn_clean12_aug.yaml $M/convnext_tiny_rfpn_clean12_aug.yaml
ln -sfn convnext_tiny_rfpn_clean12_aug.yaml $M/active.yaml
ln -sfn $APP/models/gates/convnext_tiny_rfpn_ecg_gate_v1.yaml $M/gates/convnext_tiny_rfpn_ecg_gate_v1.yaml
mkdir -p $BASE/captures

# Python venv, CPU-only torch
[ -x $BASE/venv/bin/python ] || python3 -m venv $BASE/venv
$BASE/venv/bin/pip install -q --upgrade pip
$BASE/venv/bin/pip install -q --index-url https://download.pytorch.org/whl/cpu torch torchvision
$BASE/venv/bin/pip install -q -e $APP

# Frontend
cd $APP/frontend && npm ci --no-audit --no-fund --loglevel=error && npm run build >/dev/null

# PostgreSQL role + db (password generated once, kept only in .env)
ENV=$APP/.env
if [ ! -f $ENV ]; then
  PW=$(openssl rand -hex 24)
  sudo -u postgres psql -q -v ON_ERROR_STOP=1 -c "CREATE ROLE cardiosentry LOGIN PASSWORD '$PW'"
  sudo -u postgres createdb -O cardiosentry cardiosentry
  cat > $ENV <<EOF
CARDIOSENTRY_DATABASE_URL=postgresql://cardiosentry:$PW@127.0.0.1:5432/cardiosentry
CARDIOSENTRY_LOCAL_ONLY=true
CARDIOSENTRY_PORT=8000
CARDIOSENTRY_MODELS_DIR=$M
CARDIOSENTRY_DATA_DIR=$BASE/captures
CARDIOSENTRY_NUM_THREADS=4
EOF
fi
chown -R cardiosentry:cardiosentry $BASE
chmod 600 $ENV
chmod 750 $BASE/captures
echo SETUP-OK
