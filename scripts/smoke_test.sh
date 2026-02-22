#!/usr/bin/env bash
set -euo pipefail

BASE_URL=${1:-http://127.0.0.1:5050}
PROCESS_URL="$BASE_URL/process"

TMP_DIR=$(mktemp -d)
export TMP_DIR
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

python - <<'PY'
from pathlib import Path
from PIL import Image
import os

out_dir = Path(os.environ["TMP_DIR"])
for i in range(3):
    img = Image.new("RGB", (64, 64), (120 + i * 10, 120, 120))
    img.save(out_dir / f"sample_{i}.jpg", format="JPEG", quality=90)
PY

HEADER_FILE="$TMP_DIR/headers.txt"

curl -s -o /dev/null -D "$HEADER_FILE" \
  -F "photos=@$TMP_DIR/sample_0.jpg" \
  -F "photos=@$TMP_DIR/sample_1.jpg" \
  -F "photos=@$TMP_DIR/sample_2.jpg" \
  -F "scale=4" \
  -F "target_mb=20" \
  "$PROCESS_URL"

LOCATION=$(awk '/^Location: /{print $2}' "$HEADER_FILE" | tr -d '\r')
if [[ -z "$LOCATION" ]]; then
  echo "No Location header returned. Is the server running?"
  exit 1
fi

JOB_ID=${LOCATION##*/}
STATUS_URL="$BASE_URL/status/$JOB_ID"
DOWNLOAD_URL=""

for _ in {1..120}; do
  STATUS_JSON=$(curl -s "$STATUS_URL")
  STATUS=$(STATUS_JSON="$STATUS_JSON" python - <<'PY'
import json
import os

payload = json.loads(os.environ["STATUS_JSON"])
print(payload.get("status", ""))
PY
)

  if [[ "$STATUS" == "done" ]]; then
    DOWNLOAD_URL=$(STATUS_JSON="$STATUS_JSON" python - <<'PY'
import json
import os

payload = json.loads(os.environ["STATUS_JSON"])
print(payload.get("download_url", ""))
PY
)
    break
  elif [[ "$STATUS" == "failed" ]]; then
    echo "Job failed."
    exit 1
  fi
  sleep 2
 done

if [[ -z "$DOWNLOAD_URL" ]]; then
  echo "No download URL available."
  exit 1
fi

curl -s -o "$TMP_DIR/output.zip" "$BASE_URL$DOWNLOAD_URL"

python - <<PY
import zipfile
from pathlib import Path
import sys

zip_path = Path("${TMP_DIR}") / "output.zip"
if not zip_path.exists():
    sys.exit("ZIP not found")

with zipfile.ZipFile(zip_path, "r") as zf:
    if "_report.tsv" not in zf.namelist():
        sys.exit("_report.tsv missing")
print("Smoke test OK")
PY
