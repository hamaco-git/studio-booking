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

## 6. 백업

```bash
sudo crontab -u postgres -e
# 0 3 * * * /srv/studio-booking/deploy/backup.sh
```

## 7. 업데이트

```bash
sudo /srv/studio-booking/deploy/update.sh
```
