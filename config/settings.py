"""스튜디오 예약 시스템 Django 설정.

환경마다 달라지는 값(비밀키, DB 접속 정보, DEBUG 등)은 모두 프로젝트 루트의
.env 파일에서 읽는다. Mac 개발 환경과 Ubuntu 운영 서버는 .env만 다르고
코드는 같다. 예시는 .env.example 참고.
"""

from pathlib import Path

import environ

from config.netutil import https_origins, local_network_hosts

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    SECURE_COOKIES=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")

# 접속 허용 주소(도메인·IP). 운영 서버는 .env에 도메인을 적는다.
#   ALLOWED_HOSTS=studio.example.ac.kr
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# Mac에서 runserver 0.0.0.0:8000 으로 띄워 같은 내부망의 다른 PC에서 접속할 때,
# 이 컴퓨터의 내부망(사설) IP와 호스트명(.local)을 자동으로 허용한다.
# IP가 바뀌어도 서버를 다시 켜면 새 IP가 반영된다. 기본값은 DEBUG와 같음.
LAN_ACCESS = env.bool("LAN_ACCESS", default=DEBUG)
if LAN_ACCESS:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, *local_network_hosts()]

# 로그인 등 POST를 허용할 출처. 비워 두면 ALLOWED_HOSTS의 도메인마다
# https://도메인 을 자동으로 넣는다(IP·localhost 제외). 필요할 때만 직접 적는다.
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS") or https_origins(ALLOWED_HOSTS)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "apps.accounts",
    "apps.studios",
    "apps.booking",
    "apps.manage",
    "apps.notify",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# DATABASE_URL 예: postgres://studio:비밀번호@localhost:5432/studio_booking
DATABASES = {"default": env.db("DATABASE_URL")}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 운영(HTTPS) 환경에서는 .env에 SECURE_COOKIES=True
SESSION_COOKIE_SECURE = env("SECURE_COOKIES")
CSRF_COOKIE_SECURE = env("SECURE_COOKIES")
# 보안 토큰 검증 실패 시 한국어 안내 화면 (templates/403_csrf.html)
CSRF_FAILURE_VIEW = "apps.accounts.views.csrf_failure"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Django 메시지 → Bootstrap 알림 색상
from django.contrib.messages import constants as message_constants  # noqa: E402

MESSAGE_TAGS = {message_constants.ERROR: "danger"}

# 교수 본인 예약 취소 마감: 촬영일 N일 전까지 (그 이후는 담당자에게 요청)
PROFESSOR_CANCEL_DAYS_BEFORE = env.int("PROFESSOR_CANCEL_DAYS_BEFORE", default=2)

# ── 교수 알림 문자 (알리고) ──
# SMS_MODE: off(기본, 안 보냄) / console(기록만) / test(알리고 테스트 모드) / live(실제 발송)
SMS_MODE = env.str("SMS_MODE", default="off").strip().lower()
if SMS_MODE not in ("off", "console", "test", "live"):
    raise ValueError("SMS_MODE는 off, console, test, live 중 하나여야 합니다.")
# 키·아이디·발신번호는 .env 에만 적는다 (Git에 올리지 않음)
ALIGO_API_KEY = env.str("ALIGO_API_KEY", default="")
ALIGO_USER_ID = env.str("ALIGO_USER_ID", default="")
ALIGO_SENDER = env.str("ALIGO_SENDER", default="")  # 알리고에 등록된 발신번호
SMS_ORG_NAME = env.str("SMS_ORG_NAME", default="세계사이버대학")  # 문자 머리말 [세계사이버대학]
SMS_CONTACT = env.str("SMS_CONTACT", default="")  # 문자 끝 "문의: ..." (비우면 생략)

# 허용되지 않은 주소로 접속하면(400 Bad Request) DEBUG와 관계없이 콘솔에
# 어떤 주소가 막혔는지 표시한다. → 그 주소를 .env의 ALLOWED_HOSTS에 추가
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django.security.DisallowedHost": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "apps.notify": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
