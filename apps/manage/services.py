"""계정 생성·비밀번호 초기화·CSV 일괄 등록."""

import csv
import io
import secrets
import string

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.phone import normalize_phone, validate_phone
from apps.accounts.validators import validate_login_id
from apps.booking import audit
from apps.booking.models import AuditLog
from apps.studios.models import Course

CSV_HEADERS = ["아이디", "이름", "휴대폰 번호", "과목코드"]
# 첫 행이 이 값으로 시작하면 머리글로 보고 건너뛴다 (예전 양식의 "이메일" 포함).
HEADER_FIRST_CELLS = ("아이디", "id", "ID", "이메일", "email", "Email")


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
    """CSV(아이디,이름,휴대폰 번호,과목코드)로 교수 계정을 만들고 과목에 배정한다.

    과목코드는 세미콜론(;)으로 여러 개. 이미 있는 계정은 새로 만들지 않고 과목 배정만 하며,
    휴대폰 번호 칸이 채워져 있으면 그 계정의 번호를 새 값으로 바꾼다.
    돌려주는 값: 행마다 dict(row, username, name, status, password, message)
    """
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if rows and rows[0] and rows[0][0].strip().lstrip("\ufeff") in HEADER_FIRST_CELLS:
        rows = rows[1:]
    results = []
    for i, cols in enumerate(rows, start=2):
        cols = [c.strip() for c in cols] + [""] * 4
        username, name, phone, codes = cols[0].lower(), cols[1], cols[2], cols[3]
        if not any(cols[:4]):
            continue
        res = {"row": i, "username": username, "name": name, "status": "", "password": "", "message": "",
               "warning": False}
        results.append(res)
        try:
            validate_login_id(username)
        except ValidationError as e:
            res.update(status="오류", message=e.messages[0])
            continue
        try:
            validate_phone(phone)
        except ValidationError as e:
            res.update(status="오류", message=e.messages[0])
            continue
        phone = normalize_phone(phone)
        code_list = list(dict.fromkeys(c.strip() for c in codes.replace(",", ";").split(";") if c.strip()))
        courses, warnings = [], []
        if code_list:
            if not semester:
                warnings.append("기준 학기를 고르지 않아 과목 배정은 건너뜀")
            else:
                found = {c.code: c for c in Course.objects.filter(semester=semester, code__in=code_list)}
                missing = [c for c in code_list if c not in found]
                if missing:
                    # 과목이 아직 없어도 계정은 만든다. 나중에 과목 CSV의 담당 교수 칸에 이 아이디가 있으면 배정된다.
                    warnings.append(f"{semester} 학기에 아직 없는 과목코드라 배정 건너뜀: {', '.join(missing)} "
                                    "(과목 일괄 등록에서 담당 교수 아이디로 이 아이디를 넣으면 배정됩니다)")
                courses = [found[c] for c in code_list if c in found]
        with transaction.atomic():
            user = User.objects.filter(username__iexact=username).first()
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
                user = User(username=username, name=name, phone=phone, role=User.Role.PROFESSOR)
                res["password"] = create_user(actor, user)
                res["status"] = "생성"
            for c in courses:
                c.professors.add(user)
            notes = [res["message"]] if res["message"] else []
            if courses:
                notes.append("배정: " + ", ".join(c.name for c in courses))
            notes += [f"⚠ {w}" for w in warnings]
            res["message"] = " · ".join(notes)
            res["warning"] = bool(warnings)
    return results


# ── 과목 CSV 일괄 등록 ─────────────────────────────────────

COURSE_CSV_HEADERS = ["학기", "과목코드", "과목명", "스튜디오", "담당 교수 아이디", "교수설계자 아이디", "사용 여부"]
COURSE_HEADER_FIRST_CELLS = ("학기", "semester", "Semester")
CLEAR_WORDS = ("-", "없음")  # 담당 교수·교수설계자 칸에 쓰면 배정을 지운다
ACTIVE_WORDS = {"사용": True, "y": True, "yes": True, "o": True, "1": True, "true": True,
                "중지": False, "n": False, "no": False, "x": False, "0": False, "false": False}


def _split_ids(value):
    return [v.strip().lower() for v in value.replace(",", ";").split(";") if v.strip()]


def _course_snapshot(course):
    data = audit.snapshot(course)
    data["professors"] = list(course.professors.values_list("name", flat=True))
    return data


def _match_professors(keys, warnings):
    """아이디(없으면 이름)로 교수를 찾는다. (찾은 교수 목록, 건너뛴 것이 있는지)를 돌려준다."""
    found, missing, wrong, off, ambiguous = [], [], [], [], []
    for key in keys:
        u = User.objects.filter(username__iexact=key).first()
        if not u:
            by_name = list(User.objects.filter(name=key, role=User.Role.PROFESSOR))
            if len(by_name) > 1:
                ambiguous.append(key)
                continue
            u = by_name[0] if by_name else None
        if not u:
            missing.append(key)
        elif u.role != User.Role.PROFESSOR:
            wrong.append(u.username)
        elif not u.is_active:
            off.append(u.username)
        elif u not in found:
            found.append(u)
    if missing:
        warnings.append(f"아직 없는 교수 아이디라 배정 건너뜀: {', '.join(missing)} "
                        "(교수 일괄 등록에서 이 과목코드를 넣어 올리면 배정됩니다)")
    if ambiguous:
        warnings.append(f"같은 이름의 교수가 여러 명이라 배정 건너뜀: {', '.join(ambiguous)} (아이디로 적어 주세요)")
    if wrong:
        warnings.append(f"교수 계정이 아니라 배정 건너뜀: {', '.join(wrong)}")
    if off:
        warnings.append(f"사용 중지된 교수 계정이라 배정 건너뜀: {', '.join(off)}")
    return found, bool(missing or ambiguous or wrong or off)


def _match_designer(key, warnings):
    """교수설계자를 아이디 또는 이름(예: 어복희)으로 찾는다. 못 찾으면 경고를 남기고 None."""
    u = User.objects.filter(username__iexact=key, role=User.Role.DESIGNER).first()
    if not u:
        by_name = list(User.objects.filter(name=key, role=User.Role.DESIGNER))
        if len(by_name) > 1:
            warnings.append(f"같은 이름의 교수설계자가 여러 명이라 건너뜀: {key} (아이디로 적어 주세요)")
            return None
        u = by_name[0] if by_name else None
    if not u:
        if User.objects.filter(username__iexact=key).exists():
            warnings.append(f"교수설계자 계정이 아니라 건너뜀: {key}")
        else:
            warnings.append(f"없는 교수설계자라 건너뜀: {key} (교수설계자 계정을 만든 뒤 다시 올리면 배정됩니다)")
        return None
    if not u.is_active:
        warnings.append(f"사용 중지된 교수설계자 계정이라 건너뜀: {key}")
        return None
    return u


def parse_courses(actor, text, default_semester=None):
    """과목 CSV를 검사해 행마다 무엇이 바뀔지 돌려준다 (DB는 바꾸지 않는다).

    열: 학기, 과목코드, 과목명, 스튜디오, 담당 교수 아이디, 교수설계자 아이디, 사용 여부
    - 학기+과목코드가 이미 있으면 갱신, 없으면 새 과목.
    - 갱신할 때 빈 칸은 기존 값을 그대로 둔다. 담당 교수·교수설계자 칸에 '-' 또는 '없음'을 쓰면 배정을 지운다.
    - 담당 교수 칸을 채우면 그 교수들로 바꾼다 (여러 명은 세미콜론으로 구분).
    돌려주는 값: 행마다 dict(row, semester, code, name, studio, professors, designer, active,
                            status, message, data)  ※ data는 적용에 쓰는 내부 값
    """
    from apps.booking.permissions import editable_studios
    from apps.studios.models import Semester, Studio

    rows = list(csv.reader(io.StringIO(text)))
    if rows and rows[0] and rows[0][0].strip().lstrip("﻿") in COURSE_HEADER_FIRST_CELLS:
        rows = rows[1:]
    editable = set(editable_studios(actor).values_list("pk", flat=True))
    studios = list(Studio.objects.filter(is_active=True))
    semesters = {s.name: s for s in Semester.objects.all()}
    seen = set()
    results = []
    for i, cols in enumerate(rows, start=2):
        cols = [c.strip() for c in cols] + [""] * 7
        sem_name, code, name, studio_txt, prof_txt, designer_txt, active_txt = cols[:7]
        if not any(cols[:7]):
            continue
        res = {"row": i, "semester": sem_name, "code": code, "name": name, "studio": studio_txt,
               "professors": prof_txt, "designer": designer_txt, "active": active_txt,
               "status": "", "message": "", "warning": False, "data": None}
        results.append(res)

        def error(msg, res=res):
            res.update(status="오류", message=msg)

        # 학기
        if sem_name:
            semester = semesters.get(sem_name)
            if not semester:
                error(f"등록되지 않은 학기: {sem_name}")
                continue
        elif default_semester:
            semester = default_semester
            res["semester"] = semester.name
        else:
            error("학기가 비어 있습니다.")
            continue
        # 과목코드
        if not code:
            error("과목코드가 비어 있습니다.")
            continue
        if len(code) > 30:
            error("과목코드는 30자 이하여야 합니다.")
            continue
        if (semester.pk, code) in seen:
            error("파일 안에 같은 학기·과목코드가 이미 있습니다.")
            continue
        seen.add((semester.pk, code))
        if len(name) > 100:
            error("과목명은 100자 이하여야 합니다.")
            continue
        course = Course.objects.filter(semester=semester, code=code).first()
        if course and course.studio_id not in editable:
            error("담당 스튜디오가 아닌 과목은 바꿀 수 없습니다.")
            continue
        if not course and not name:
            error("새 과목은 과목명이 필요합니다.")
            continue
        # 스튜디오: 코드(studio1) 또는 이름(Studio 1)
        studio = None
        if studio_txt:
            key = studio_txt.replace(" ", "").lower()
            studio = next((s for s in studios if key in (s.code.lower(), s.name.replace(" ", "").lower())), None)
            if not studio:
                error(f"없는 스튜디오: {studio_txt}")
                continue
            if studio.pk not in editable:
                error(f"담당 스튜디오가 아닙니다: {studio.name}")
                continue
        elif not course:
            error("새 과목은 스튜디오가 필요합니다.")
            continue
        # 담당 교수: 아직 없는 아이디는 경고만 하고 과목은 등록한다 (나중에 교수 CSV로 배정 가능)
        warnings = []
        professors, prof_add_only = None, False  # None이면 그대로 둔다
        if prof_txt in CLEAR_WORDS:
            professors = []
        elif prof_txt:
            # 일부를 못 찾았으면 기존 배정은 지우지 않고 찾은 교수만 더한다
            professors, prof_add_only = _match_professors(_split_ids(prof_txt), warnings)
        # 교수설계자: 아이디 또는 이름. 못 찾으면 경고만 하고 기존 값을 둔다
        designer, set_designer = None, False
        if designer_txt in CLEAR_WORDS:
            set_designer = True
        elif designer_txt:
            designer = _match_designer(designer_txt, warnings)
            set_designer = designer is not None
        # 사용 여부
        active = None
        if active_txt:
            active = ACTIVE_WORDS.get(active_txt.lower())
            if active is None:
                error("사용 여부는 '사용' 또는 '중지'로 적어 주세요.")
                continue

        # 무엇이 바뀌는지 정리
        changes = []
        if course:
            if name and name != course.name:
                changes.append(f"과목명 {course.name} → {name}")
            if studio and studio.pk != course.studio_id:
                changes.append(f"스튜디오 {course.studio.name} → {studio.name}")
            if professors is not None:
                old = set(course.professors.values_list("username", flat=True))
                new = {p.username for p in professors}
                if (not new <= old) if prof_add_only else (old != new):
                    changes.append("담당 교수 변경")
            if set_designer and (designer.pk if designer else None) != course.designer_id:
                changes.append("교수설계자 변경")
            if active is not None and active != course.is_active:
                changes.append("사용" if active else "중지")
            res["status"] = "갱신" if changes else "변경 없음"
            res["message"] = ", ".join(changes)
        else:
            res["status"] = "신규"
        if warnings:
            res["warning"] = True
            res["message"] = " · ".join(([res["message"]] if res["message"] else []) + [f"⚠ {w}" for w in warnings])
        if res["status"] == "변경 없음":
            continue
        res["data"] = {"course": course, "semester": semester, "code": code, "name": name, "studio": studio,
                       "professors": professors, "prof_add_only": prof_add_only,
                       "designer": designer, "set_designer": set_designer, "active": active}
    return results


def apply_courses(actor, results):
    """parse_courses() 결과 중 신규·갱신 행을 저장한다. 저장한 과목 수를 돌려준다."""
    n = 0
    with transaction.atomic():
        for r in results:
            d = r.get("data")
            if r["status"] not in ("신규", "갱신") or not d:
                continue
            course = d["course"]
            if course:
                before = _course_snapshot(course)
                if d["name"]:
                    course.name = d["name"]
                if d["studio"]:
                    course.studio = d["studio"]
                if d["set_designer"]:
                    course.designer = d["designer"]
                if d["active"] is not None:
                    course.is_active = d["active"]
                course.save()
                action = AuditLog.Action.UPDATE
            else:
                before = None
                course = Course.objects.create(
                    semester=d["semester"], code=d["code"], name=d["name"], studio=d["studio"],
                    designer=d["designer"], is_active=True if d["active"] is None else d["active"])
                action = AuditLog.Action.CREATE
            if d["professors"] is not None:
                if d.get("prof_add_only"):
                    course.professors.add(*d["professors"])
                else:
                    course.professors.set(d["professors"])
            audit.log(actor, action, course, before=before, after=_course_snapshot(course))
            n += 1
    return n
