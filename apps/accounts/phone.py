"""휴대폰 번호 정리·검사. 나중에 문자(SMS)·알림톡 발송에 쓰기 위해 한 가지 형식(010-1234-5678)으로 저장한다."""

import re

from django.core.exceptions import ValidationError

_MOBILE = re.compile(r"^01[016789]\d{7,8}$")


def digits(value):
    """숫자만 남긴다. +82 10-... 같은 국제 형식은 010...으로 바꾼다."""
    d = re.sub(r"\D", "", value or "")
    if d.startswith("82") and len(d) in (11, 12):
        d = "0" + d[2:]
    return d


def normalize_phone(value):
    """휴대폰 번호면 010-1234-5678 형식으로, 아니면 입력값 그대로(앞뒤 공백 제거) 돌려준다."""
    value = (value or "").strip()
    d = digits(value)
    if not _MOBILE.match(d):
        return value
    if len(d) == 10:
        return f"{d[:3]}-{d[3:6]}-{d[6:]}"
    return f"{d[:3]}-{d[3:7]}-{d[7:]}"


def validate_phone(value):
    if value and not _MOBILE.match(digits(value)):
        raise ValidationError("휴대폰 번호 형식이 아닙니다. 예: 010-1234-5678")
