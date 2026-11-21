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
| 4 | 담당자 기능 (현황 달력, 주간 슬롯 설정, 촬영 불가일, 예약 수정·취소) | 완료 (과목·배정 관리 화면은 6단계에서) |
| 5 | 교수 예약 기능 (예약 달력, 신청·취소), 담당자 대리 예약 | 완료 |
| 6 | 계정 일괄 등록, 엑셀 내려받기, 변경 이력 | 예정 |
| 7 | 사용자 테스트 | 예정 |
| 8 | Ubuntu 서버 배포 | 예정 |

## Mac 개발 환경 설치

[Homebrew](https://brew.sh)가 설치되어 있다는 가정입니다. 터미널에서 순서대로 실행합니다.

### 1. 필요한 프로그램 설치

```bash
brew install uv postgresql@16 git
brew services start postgresql@16
grep -q 'postgresql@16/bin' ~/.zshrc || echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

세 번째 줄은 `psql` 명령을 쓸 수 있게 PATH를 추가합니다. 이미 추가되어 있으면 다시 넣지 않으므로 여러 번 실행해도 됩니다.
(Intel Mac은 경로가 `/usr/local/opt/postgresql@16/bin`입니다.)

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
uv run python manage.py createsuperuser  # 슈퍼관리자 계정 만들기
```

`createsuperuser`는 차례로 다음을 묻습니다.

- 사용자 이름(로그인 ID): 학교 이메일 권장
- 이메일 주소
- 이름: 화면에 표시될 이름 (예: 홍길동)
- 비밀번호, 비밀번호 확인: 너무 짧거나 쉬우면 경고가 나오며, `y`를 눌러 그대로 쓸 수도 있습니다.

### 5. 실행

```bash
uv run python manage.py runserver
```

- 사용자 화면: http://127.0.0.1:8000/
- 관리자 화면: http://127.0.0.1:8000/admin/ (슈퍼관리자로 로그인)

관리자 화면에서 학기, 과목(지정 스튜디오·담당 교수), 담당자·교수 계정, 예약 가능 슬롯을 등록해 볼 수 있습니다.
새로 만든 담당자·교수 계정은 처음 로그인할 때 비밀번호를 바꾸도록 안내됩니다.

### 6. 데모 데이터로 둘러보기 (선택)

```bash
uv run python manage.py seed_demo
```

담당자 `staff1@demo.local`~`staff4@demo.local`, 교수 `prof1@demo.local`~`prof6@demo.local`
(비밀번호 모두 `demo1234!`)과 데모 과목, 이번 주·다음 주 평일 오전/오후 슬롯, 예약 몇 건이 만들어집니다.
`.env`의 `DEBUG=True`일 때만 실행되므로 운영 서버에서는 동작하지 않습니다.

담당자로 로그인하면 다음 메뉴가 보입니다.

| 메뉴 | 내용 |
| --- | --- |
| 현황 달력 | 4개 스튜디오의 예약·예약 가능 슬롯·촬영 불가일을 월/주/목록으로 보기. 담당 스튜디오 예약을 누르면 수정 화면 |
| 주간 슬롯 설정 | 주를 고르고 요일별 오전/오후 칸을 체크해 저장. "지난주 설정 복사" 지원. 예약이 있는 칸은 잠김 |
| 촬영 불가일 | 날짜(또는 기간)·종일/시간·사유 등록, 삭제. 겹치는 확정 예약이 있으면 경고 |
| 예약 목록 | 기간·스튜디오·교수/과목 검색, 수정·취소 (모든 변경은 이력에 기록) |

교수로 로그인하면 다음 메뉴가 보입니다.

| 메뉴 | 내용 |
| --- | --- |
| 촬영 예약 | 과목을 고르면 그 과목의 지정 스튜디오 달력이 나옴. 초록색 "예약 가능" 칸을 누르고 "예약하기" (메모 선택). 다른 교수 예약은 "예약됨"으로만 표시 |
| 내 예약 | 예정된 예약과 지난·취소된 예약. 촬영 2일 전까지 직접 취소 가능, 이후에는 담당자에게 문의 |

담당자는 현황 달력에서 담당 스튜디오의 "예약 가능" 칸을 누르면 교수 대신 예약(대리 예약)할 수 있습니다.
교수 취소 마감(기본 2일 전)은 `.env`의 `PROFESSOR_CANCEL_DAYS_BEFORE`로 바꿀 수 있습니다.

담당자는 자기 담당 스튜디오만 수정할 수 있고 다른 스튜디오는 조회만 됩니다.
"전체 스튜디오" 불가일은 슈퍼관리자만 등록할 수 있습니다.
오전/오후 시간대는 슈퍼관리자가 관리자 화면의 "시간대 템플릿"에서 바꿀 수 있습니다.

### 7. 테스트

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
static/vendor/     Bootstrap, FullCalendar 파일 (인터넷 CDN 없이 동작하도록 저장소에 포함)
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
| booking_slottemplate | 주간 설정 화면의 시간대 (기본: 오전 09~12, 오후 13~18) |
| booking_openslot | 담당자가 연 예약 가능 시간대 슬롯 |
| booking_blackout | 촬영 불가일 (스튜디오 비우면 전체, 시간 비우면 종일) |
| booking_reservation | 예약 (삭제 대신 상태를 '취소'로 변경) |
| booking_auditlog | 변경 이력 |

같은 스튜디오에서 시간이 겹치는 확정 예약과 겹치는 슬롯은 PostgreSQL 제약으로 막혀 있어,
두 사람이 동시에 같은 시간을 눌러도 하나만 저장됩니다.

## 운영 서버(Ubuntu 24.04) 배포

[docs/deploy-ubuntu.md](docs/deploy-ubuntu.md)를 참고하세요.
