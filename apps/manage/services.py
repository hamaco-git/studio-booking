"""계정 생성·비밀번호 초기화·CSV 일괄 등록."""

import csv
import io
import secrets
import string

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.phone import normalize_phone, validate_phone
from apps.booking import audit
from apps.booking.models import AuditLog
from apps.studios.models import Course

CSV_HEADERS = ["이메일", "이름", "휴대폰 번호", "과목코드"]


def temp_password():
    """임시 비밀번호 (예: wcu-4821-kqmt). 첫 로그인 때 바꾸도록 강제된다."""
    digits = "".join(secrets.choice(string.digits) for _ in range(4))
    letters = "".join(secrets.choice("abcdefghijkmnpqrstuvwxyz") for _ in range(4))
    return f"wcu-{digits}-{letters}"


def _user_snapshot(user):
    return {k: getattr(user, k) for k in ("id", "username", "name", "phone", "role", "is_active")}


def create_user(actor, user):
    """폼에서 만든 (저장 전) 사용자에 임시 비밀번호를 정해 저장하고 비밀번호를 돌려준다."""
    pw = temp_password()
    user.set_password(pw)
    user.must_change_password = True
    user.save()
    audit.log(actor, AuditLog.Action.CREATE, user, after=_user_snapshot(user))
    return pw


def reset_password(actor, user):
    pw = temp_password()
    user.set_password(pw)
    user.must_change_password = True
    user.save(update_fields=["password", "must_change_password"])
    audit.log(actor, AuditLog.Action.UPDATE, user, after={"password": "초기화"})
    return pw


def log_update(actor, user, before):
    audit.log(actor, AuditLog.Action.UPDATE, user, before=before, after=_user_snapshot(user))


def decode_csv(raw: bytes) -> str:
    """엑셀에서 저장한 CSV는 CP949(EUC-KR)인 경우가 많아 둘 다 시도한다."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValidationError("파일 인코딩을 읽을 수 없습니다. UTF-8 또는 CP949로 저장해 주세요.")


def import_professors(actor, text, semester=None):
    """CSV(이메일,이름,휴대폰 번호,과목코드)로 교수 계정을 만들고 과목에 배정한다.

    과목코드는 세미콜론(;)으로 여러 개. 이미 있는 계정은 새로 만들지 않고 과목 배정만 하며,
    휴대폰 번호 칸이 채워져 있으면 그 계정의 번호를 새 값으로 바꾼다.
    돌려주는 값: 행마다 dict(row, email, name, status, password, message)
    """
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if rows and rows[0] and rows[0][0].strip().lstrip("\ufeff") in ("이메일", "email", "Email"):
        rows = rows[1:]
    results = []
    for i, cols in enumerate(rows, start=2):
        cols = [c.strip() for c in cols] + [""] * 4
        email, name, phone, codes = cols[0].lower(), cols[1], cols[2], cols[3]
        if not any(cols[:4]):
            continue
        res = {"row": i, "email": email, "name": name, "status": "", "password": "", "message": ""}
        results.append(res)
        try:
            validate_email(email)
        except ValidationError:
            res.update(status="오류", message="이메일 형식이 올바르지 않습니다.")
            continue
        try:
            validate_phone(phone)
        except ValidationError as e:
            res.update(status="오류", message=e.messages[0])
            continue
        phone = normalize_phone(phone)
        code_list = [c.strip() for c in codes.split(";") if c.strip()]
        courses = []
        if code_list:
            if not semester:
                res.update(status="오류", message="과목코드가 있으면 기준 학기를 선택해야 합니다.")
                continue
            found = {c.code: c for c in Course.objects.filter(semester=semester, code__in=code_list)}
            missing = [c for c in code_list if c not in found]
            if missing:
                res.update(status="오류", message=f"{semester} 학기에 없는 과목코드: {', '.join(missing)}")
                continue
            courses = [found[c] for c in code_list]
        with transaction.atomic():
            user = User.objects.filter(username__iexact=email).first()
            if user:
                if user.role != User.Role.PROFESSOR:
                    res.update(status="오류", message="교수가 아닌 계정입니다.")
                    continue
                res["status"] = "기존 계정"
                res["name"] = user.name
                if phone and phone != user.phone:
                    before = _user_snapshot(user)
                    user.phone = phone
                    user.save(update_fields=["phone"])
                    log_update(actor, user, before)
                    res["message"] = "휴대폰 번호 갱신"
            else:
                if not name:
                    res.update(status="오류", message="이름이 비어 있습니다.")
                    continue
                user = User(username=email, email=email, name=name, phone=phone, role=User.Role.PROFESSOR)
                res["password"] = create_user(actor, user)
                res["status"] = "생성"
            for c in courses:
                c.professors.add(user)
            if courses:
                note = "배정: " + ", ".join(c.name for c in courses)
                res["message"] = f"{res['message']} · {note}" if res["message"] else note
    return results
