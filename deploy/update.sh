#!/usr/bin/env bash
# 서버에서 새 버전 반영 (sudo 권한이 있는 관리자 계정으로 실행):
#   sudo /srv/studio-booking/deploy/update.sh
set -euo pipefail
cd /srv/studio-booking
sudo -u studio git pull --ff-only
sudo -u studio uv sync --frozen
sudo -u studio uv run python manage.py migrate
sudo -u studio uv run python manage.py collectstatic --noinput
systemctl restart studio-booking
