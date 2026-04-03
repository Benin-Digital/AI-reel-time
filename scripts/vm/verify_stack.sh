#!/usr/bin/env bash
set -euo pipefail

check_cmd() {
  local cmd="$1"
  if command -v "$cmd" >/dev/null 2>&1; then
    printf "[OK] %s\n" "$cmd"
  else
    printf "[MISSING] %s\n" "$cmd"
  fi
}

echo "== Command checks =="
check_cmd git
check_cmd docker
check_cmd python3.11
check_cmd pip3
check_cmd node
check_cmd npm
check_cmd tesseract
check_cmd libreoffice

echo
echo "== Version checks =="
docker --version || true
docker compose version || true
python3.11 --version || true
node --version || true
npm --version || true
tesseract --version | head -n 1 || true
libreoffice --version || true

echo
echo "== Docker daemon =="
if docker info >/dev/null 2>&1; then
  echo "[OK] Docker daemon reachable"
else
  echo "[WARN] Docker daemon not reachable (check group membership/session)"
fi

echo
echo "== Storage paths =="
for p in /srv/ai-realtime/storage/cv /srv/ai-realtime/storage/job /srv/ai-realtime/storage/archive /srv/ai-realtime/logs; do
  if [[ -d "$p" ]]; then
    echo "[OK] $p"
  else
    echo "[MISSING] $p"
  fi
done

echo
echo "Verification complete."
