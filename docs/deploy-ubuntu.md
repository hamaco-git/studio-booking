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
```

`.env`의 `ALLOWED_HOSTS`에는 사용자가 브라우저에 입력할 도메인을 적습니다(여러 개면 쉼표로 구분).
`CSRF_TRUSTED_ORIGINS`는 비워 두면 `https://<도메인>`이 자동으로 들어갑니다. 도메인을 바꾸면
`deploy/nginx-studio-booking.conf`의 `server_name`도 같이 바꾸고 `sudo systemctl restart studio-booking`으로 다시 켭니다.

## 3-1. 계정 만들기 (슈퍼관리자·담당자·교수)

계정 목록 CSV(열: 역할, 아이디, 이름, 연락처, 담당스튜디오, 초기비밀번호)를 서버에 올려 한 번에 만듭니다.
이 파일에는 비밀번호가 들어 있으므로 **저장소에 올리지 말고**, 서버의 저장소 폴더 밖에 두었다가 사용 후 지웁니다.

```bash
# Mac에서: scp 계정목록.csv 사용자@서버:/tmp/accounts.csv
sudo chown studio /tmp/accounts.csv && sudo chmod 600 /tmp/accounts.csv
sudo -u studio uv run python manage.py load_accounts /tmp/accounts.csv           # 확인만
sudo -u studio uv run python manage.py load_accounts /tmp/accounts.csv --apply   # 저장
sudo shred -u /tmp/accounts.csv
```

- 아이디는 학교 이메일 또는 `studio1` 같은 영문·숫자. 아이디가 비어 있는 행은 건너뜁니다. 나중에 채워서 다시 실행하면 새 행만 추가되고 기존 계정은 그대로입니다.
- 초기비밀번호를 비우면 강한 무작위 값을 만들어 화면에 보여 줍니다.
- `test1234`처럼 흔한 공통 초기 비밀번호는 규칙 검사에 걸리므로 `--skip-password-check`를 붙여 실행합니다. 첫 로그인 때 변경이 강제됩니다.
- 모든 계정은 첫 로그인 때 비밀번호를 바꾸기 전에는 다른 화면을 쓸 수 없습니다.
- 담당자는 담당스튜디오 칸의 스튜디오(studio1 등)에 배정됩니다.
- 교수의 과목 배정은 계정을 만든 뒤 "관리 > 과목·교수 배정" 또는 "교수 일괄 등록"(기존 계정은 배정만)에서 합니다.

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
