#!/usr/bin/env bash
# Starts the Django backend (port 8000) and frontend (port 5173). Needs Python 3.12 and Node 18+.
set -e
cd "$(dirname "$0")"
PY=$(command -v python3.12 || true)
[ -z "$PY" ] && [ -x /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 ] && PY=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
[ -z "$PY" ] && { echo "Python 3.12 not found. See README.md (Python 3.14 will not work)."; exit 1; }
command -v npm >/dev/null || { echo "Node.js 18+ is required: https://nodejs.org"; exit 1; }
cd backend
if [ -d .venv ] && ! .venv/bin/python --version 2>&1 | grep -q "3.12"; then rm -rf .venv; fi
[ -d .venv ] || "$PY" -m venv .venv
. .venv/bin/activate
#pip install -q --upgrade pip && pip install -q -r requirements.txt

# Use compatible wheels on Intel macOS.
PIP_CONSTRAINT_ARGS=()
if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "x86_64" ]; then
  PIP_CONSTRAINT_ARGS=(-c constraints-intel-macos.txt)
fi

python -m pip install --upgrade pip
python -m pip install "${PIP_CONSTRAINT_ARGS[@]}" -r requirements.txt









# Model dependencies (PyTorch, transformers, MediaPipe, OpenCV). Large download; set SATYAPAN_ML=0 to skip (the site then runs with the model checks reported as unavailable).
if [ "${SATYAPAN_ML:-1}" = "1" ]; then
  python -m pip install "${PIP_CONSTRAINT_ARGS[@]}" -r requirements-ml.txt \
    || {
      echo "ERROR: Required AI/ML dependencies failed to install."
      exit 1
    }
fi
#if [ "${SATYAPAN_ML:-1}" = "1" ]; then
 # pip install -q -r requirements-ml.txt || echo "WARNING: model dependencies failed to install. The site still starts, but the model-based checks will show as unavailable."
#fi
[ -f .env ] || cp .env.example .env
# The project was refactored into several apps: migration files are generated here on first run.
# If you upgraded from the single-app version, delete the old satyapan.db first (the tables moved).
python manage.py setup_db || { echo "Database setup failed - see the messages above."; exit 1; }
python manage.py create_demo_users || true  # development only: officer / customer demo logins (refuses to run in production)
daphne -b 0.0.0.0 -p 8000 satyapan.asgi:application &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT INT TERM
cd ../frontend
[ -d node_modules ] || npm install

if [ -f certs/lan.crt ] && [ -f certs/lan.key ]; then
  SCHEME="https"
  echo ""
  echo "HTTPS is enabled - the camera will work on LAN devices."
else
  SCHEME="http"
  echo ""
  echo "WARNING: No TLS cert found. The camera will NOT work on other LAN devices over HTTP."
  echo "         Run ./setup-https.sh to generate a certificate."
fi

echo ""
echo "Open ${SCHEME}://localhost:5173  (API docs: http://127.0.0.1:8000/docs)"
echo "Demo logins (development only):  officer / officer-pass-123   customer / customer-pass-123"
echo "Use two browser profiles (or a private window) to be the customer and the officer at the same time."
npm run dev
