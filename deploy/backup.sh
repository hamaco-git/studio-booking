#!/usr/bin/env bash
# 매일 DB 백업, 30일 보관. crontab 예: 0 3 * * * /srv/studio-booking/deploy/backup.sh
set -euo pipefail
DIR=/var/backups/studio-booking
mkdir -p "$DIR"
pg_dump -Fc studio_booking > "$DIR/studio_booking-$(date +%Y%m%d).dump"
find "$DIR" -name '*.dump' -mtime +30 -delete
