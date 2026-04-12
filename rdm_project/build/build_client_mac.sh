#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

pyinstaller rdm_client_app.py \
  --name "RDM_Client" \
  --noconsole \
  --windowed \
  --icon "rdm_project/assets/icon.icns" \
  --noconfirm \
  --clean \
  --optimize 2 \
  --add-data "rdm_project:rdm_project" \
  --hidden-import=PyQt6.sip \
  --hidden-import=cv2 \
  --hidden-import=numpy \
  --hidden-import=psutil \
  --hidden-import=mss

DMG_PATH="dist/RDM_Client.dmg"
if command -v hdiutil >/dev/null 2>&1; then
  rm -f "$DMG_PATH" || true
  hdiutil create -volname "RDM Client" -srcfolder "dist/RDM_Client.app" -ov -format UDZO "$DMG_PATH"
fi

echo "Built: dist/RDM_Client.app"
