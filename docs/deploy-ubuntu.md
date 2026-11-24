# Ubuntu 24.04 서버 배포 안내

배포 단계(8단계)에서 실제 서버에 맞춰 다시 점검합니다. 아래는 기본 절차입니다.

## 1. 패키지 설치

```bash
sudo apt update
sudo apt install -y postgresql nginx git curl
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv 설치
```

Ubuntu 24.04의 기본 PostgreSQL은 16, Python은 3.12로 개발 환경과 같습니다.

## 2. 서비스 계정과 DB

```bash
sudo adduser --system --group --home /srv/studio-booking studio
sudo -u postgres psql -c "CREATE USER studio WITH PASSWORD '강한-비밀번호';"
sudo -u postgres psql -c "CREATE DATABASE studio_booking OWNER studio;"
```

## 3. 코드와 설정

```bash
sudo -u studio git clone https://github.com/hamaco-git/studio-booking.git /srv/studio-booking
cd /srv/studio-booking
sudo -u studio cp .env.example .env
sudo -u studio nano .env   # DEBUG=False, SECRET_KEY, DATABASE_URL, ALLOWED_HOSTS=<도메인>, SECURE_COOKIES=True
sudo -u studio uv sync --frozen
sudo -u studio uv run python manage.py migrate
sudo -u studio uv run python manage.py seed_studios
sudo -u studio uv run python manage.py collectstatic --noinput
sudo -u studio uv run python manage.py createsuperuser
```

`.env`의 `ALLOWED_HOSTS`에는 사용자가 브라우저에 입력할 도메인을 적습니다(여러 개면 쉼표로 구분).
`CSRF_TRUSTED_ORIGINS`는 비워 두면 `https://<도메인>`이 자동으로 들어갑니다. 도메인을 바꾸면
`deploy/nginx-studio-booking.conf`의 `server_name`도 같이 바꾸고 `sudo systemctl restart studio-booking`으로 다시 켭니다.

## 4. Gunicorn(systemd)과 Nginx

```bash
sudo cp deploy/studio-booking.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now studio-booking

sudo cp deploy/nginx-studio-booking.conf /etc/nginx/sites-available/studio-booking
sudo ln -s /etc/nginx/sites-available/studio-booking /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 5. HTTPS

학교 인증서가 있으면 Nginx에 등록하고, 없으면 Let's Encrypt를 사용합니다.

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d studio.example.ac.kr
```

## 6. 교수 알림 문자 (알리고)

예약이 확정되면 바로, 촬영 2일 전 오전 9시, 촬영 당일 오전 9시에 교수 휴대폰으로 문자를 보냅니다.
담당자가 예약 일정을 바꾸거나 취소해도 안내 문자가 갑니다. 보낸 기록은 예약 상세 화면과
관리자 화면(문자 발송 기록)에서 볼 수 있습니다.

1. **알리고에 서버 IP 등록**: 알리고 사이트 > 문자 API > 발송 서버 IP에 이 서버의 공인 IP를 등록합니다.
   (`curl -s https://api.ipify.org` 로 확인). 등록되지 않은 IP에서는 발송이 거절됩니다.
2. **.env 설정** (키는 .env에만 적고 Git에는 올리지 않습니다)

   ```bash
   sudo -u studio nano /srv/studio-booking/.env
   #   SMS_MODE=test
   #   ALIGO_API_KEY=...
   #   ALIGO_USER_ID=...
   #   ALIGO_SENDER=1577-4990         # 알리고에 등록된 발신번호
   #   SMS_CONTACT=스튜디오 담당자 02-xxxx-xxxx   # 선택
   sudo chmod 600 /srv/studio-booking/.env
   sudo systemctl restart studio-booking
   ```

3. **시험**: `SMS_MODE=test`는 알리고 테스트 모드라 실제로 발송·과금되지 않고 설정만 확인합니다.

   ```bash
   cd /srv/studio-booking
   sudo -u studio uv run python manage.py sms_test 010-1234-5678
   sudo -u studio uv run python manage.py send_sms_reminders --dry-run   # 오늘 보낼 알림 미리 보기
   ```

   성공하면 `.env`를 `SMS_MODE=live`로 바꾸고 `sudo systemctl restart studio-booking`.
4. **매일 09:00 자동 발송 (systemd 타이머)**

   ```bash
   sudo cp deploy/studio-booking-sms.service deploy/studio-booking-sms.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now studio-booking-sms.timer
   systemctl list-timers studio-booking-sms.timer         # 다음 실행 시각 확인
   journalctl -u studio-booking-sms.service -n 50         # 최근 실행 결과
   ```

   같은 알림은 한 번만 보내므로 명령을 여러 번 실행해도 중복 발송되지 않습니다. 실패한 건은
   `sudo systemctl start studio-booking-sms.service`로 다시 실행하면 재시도합니다.

## 7. 백업

```bash
sudo crontab -u postgres -e
# 0 3 * * * /srv/studio-booking/deploy/backup.sh
```

## 8. 업데이트

```bash
sudo /srv/studio-booking/deploy/update.sh
```
