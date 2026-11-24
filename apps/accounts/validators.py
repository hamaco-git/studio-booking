import re

from django.core.exceptions import ValidationError

LOGIN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
LOGIN_ID_HELP = "영문, 숫자와 . _ - 만 쓸 수 있습니다. 이메일 주소(@)는 넣지 않습니다. 예: prof01"


def validate_login_id(value):
    """로그인 아이디: 이메일이 아닌 일반 아이디 (예: admin, studio1, prof01)."""
    if "@" in (value or ""):
        raise ValidationError("아이디에는 @를 쓸 수 없습니다. 이메일 주소가 아니라 아이디만 넣어 주세요.", code="email")
    if not LOGIN_ID_RE.match(value or ""):
        raise ValidationError("아이디는 영문, 숫자와 . _ - 만 쓸 수 있습니다.", code="invalid")
