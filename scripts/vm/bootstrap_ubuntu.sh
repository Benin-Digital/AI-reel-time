#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script with sudo/root."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

echo "[1/8] System update"
apt-get update -y
apt-get upgrade -y

echo "[2/8] Base packages"
apt-get install -y \
  ca-certificates \
  curl \
  gnupg \
  lsb-release \
  git \
  unzip \
  build-essential \
  software-properties-common

echo "[3/8] Docker repository"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

ARCH="$(dpkg --print-architecture)"
CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
echo \
  "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -y

echo "[4/8] Docker Engine + Compose plugin"
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

if id -u "${SUDO_USER:-}" >/dev/null 2>&1; then
  usermod -aG docker "${SUDO_USER}"
fi

systemctl enable docker
systemctl start docker

echo "[5/8] Python 3.11 toolchain"
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update -y
apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip

echo "[6/8] Node.js 22 LTS"
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs

echo "[7/8] OCR + document conversion"
apt-get install -y tesseract-ocr libreoffice

echo "[8/8] Recommended server folders"
mkdir -p /srv/ai-realtime/storage/cv
mkdir -p /srv/ai-realtime/storage/job
mkdir -p /srv/ai-realtime/storage/archive
mkdir -p /srv/ai-realtime/logs

echo
echo "Bootstrap complete."
echo "IMPORTANT: logout/login (or reboot) so docker group is applied to your user."
echo "Then run: scripts/vm/verify_stack.sh"
