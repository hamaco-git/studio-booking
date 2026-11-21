# 스튜디오 촬영 예약 시스템

세계사이버대학 스튜디오(studio1~studio4)의 교수 촬영 일정 예약 시스템입니다.

- 교수: 담당 과목에 지정된 스튜디오의 달력을 보고 빈 시간대 슬롯(예: 오전/오후)을 예약
- 스튜디오 담당자: 주 단위로 예약 가능 슬롯을 열고, 촬영 불가일을 지정하고, 예약을 수정·삭제
- 슈퍼관리자: 계정·스튜디오·과목 관리

기술 스택: Python 3.12, Django 5.2 LTS, PostgreSQL 16 (Mac 개발 → Ubuntu 24.04 운영)

## 현재 진행 단계

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 1 | 협의·설계 확정 | 완료 |
| 2 | 환경 구성 (프로젝트 구조, 설정, 설치 안내) | 완료 |
| 3 | DB·계정 (테이블 10개, 로그인, 역할, 첫 로그인 비밀번호 변경) | 완료 |
| 4 | 담당자 기능 (주간 슬롯 설정, 불가일, 현황 달력) | 예정 |
| 5 | 교수 예약 기능 (예약 달력, 신청·취소) | 예정 |
| 6 | 계정 일괄 등록, 엑셀 내려받기, 변경 이력 | 예정 |
| 7 | 사용자 테스트 | 예정 |
| 8 | Ubuntu 서버 배포 | 예정 |

## Mac 개발 환경 설치

[Homebrew](https://brew.sh)가 설치되어 있다는 가정입니다. 터미널에서 순서대로 실행합니다.

### 1. 필요한 프로그램 설치

```bash
brew install uv postgresql@16 git
brew services start postgresql@16
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

`uv`는 Python 3.12와 라이브러리를 프로젝트 안에 자동으로 설치해 주는 도구입니다.

### 2. 데이터베이스 만들기

```bash
psql postgres -c "CREATE USER studio WITH PASSWORD 'studio' CREATEDB;"
psql postgres -c "CREATE DATABASE studio_booking OWNER studio;"
```

`CREATEDB` 권한은 테스트 실행 시 임시 테스트 DB를 만드는 데 필요합니다.

### 3. 코드 받기와 설정

```bash
git clone https://github.com/hamaco-git/studio-booking.git
cd studio-booking
cp .env.example .env        # 개발용 기본값 그대로 사용 가능
uv sync                     # Python 3.12와 라이브러리 설치
```

### 4. 테이블 생성과 초기 데이터

```bash
uv run python manage.py migrate          # 테이블 생성
uv run python manage.py seed_studios     # studio1~studio4 등록
uv run python manage.py createsuperuser  # 슈퍼관리자 계정 만들기 (아이디는 이메일 권장)
```

### 5. 실행

```bash
uv run python manage.py runserver
```

- 사용자 화면: http://127.0.0.1:8000/
- 관리자 화면: http://127.0.0.1:8000/admin/ (슈퍼관리자로 로그인)

관리자 화면에서 학기, 과목(지정 스튜디오·담당 교수), 담당자·교수 계정, 예약 가능 슬롯을 등록해 볼 수 있습니다.
새로 만든 담당자·교수 계정은 처음 로그인할 때 비밀번호를 바꾸도록 안내됩니다.

### 6. 테스트

```bash
uv run python manage.py test
```

## 폴더 구조

```
config/            Django 설정 (settings.py는 .env 값을 읽음)
apps/accounts/     계정·역할·로그인
apps/studios/      스튜디오, 담당자 배정, 학기, 과목, 과목 담당 교수
apps/booking/      예약 가능 슬롯, 촬영 불가일, 예약, 변경 이력
templates/         화면 템플릿 (Bootstrap 5)
docs/              설계·배포 문서
```

## 데이터베이스 구조

| 테이블 | 용도 |
| --- | --- |
| accounts_user | 모든 계정. role = SUPER(슈퍼관리자) / STAFF(담당자) / PROFESSOR(교수) |
| studios_studio | 스튜디오 4개 |
| studios_studiostaff | 담당자 ↔ 스튜디오 |
| studios_semester | 학기 |
| studios_course | 과목 (학기별, 지정 스튜디오 1개) |
| studios_courseprofessor | 과목 ↔ 교수 (다대다) |
| booking_openslot | 담당자가 연 예약 가능 시간대 슬롯 |
| booking_blackout | 촬영 불가일 (스튜디오 비우면 전체, 시간 비우면 종일) |
| booking_reservation | 예약 (삭제 대신 상태를 '취소'로 변경) |
| booking_auditlog | 변경 이력 |

같은 스튜디오에서 시간이 겹치는 확정 예약과 겹치는 슬롯은 PostgreSQL 제약으로 막혀 있어,
두 사람이 동시에 같은 시간을 눌러도 하나만 저장됩니다.

## 운영 서버(Ubuntu 24.04) 배포

[docs/deploy-ubuntu.md](docs/deploy-ubuntu.md)를 참고하세요.
