"""배포용 계정 일괄 생성. 운영 서버에서도 사용할 수 있다.

    uv run python manage.py load_accounts 계정목록.csv            # 확인만 (저장 안 함)
    uv run python manage.py load_accounts 계정목록.csv --apply    # 실제로 저장

CSV 열 (첫 줄은 제목): 역할, 이메일, 이름, 연락처, 담당스튜디오, 초기비밀번호
- 역할: 슈퍼관리자 / 담당자 / 교수 (SUPER / STAFF / PROFESSOR 도 가능)
- 이메일: 로그인 ID. 비어 있는 행은 건너뛴다 (아직 정해지지 않은 자리)
- 담당스튜디오: 담당자만. studio1 처럼 코드, 여러 개면 세미콜론(;)
- 초기비밀번호: 비우면 강한 무작위 값을 만들어 결과에 보여 준다

만든 계정은 모두 첫 로그인 때 비밀번호를 바꾸도록 설정된다.
이미 있는 계정은 바꾸지 않는다 (--reset-password 를 주면 비밀번호만 CSV 값으로 다시 설정).
이 CSV에는 비밀번호가 들어 있으므로 저장소에 올리지 말고, 사용 후 서버에서 지운다.
"""

import csv
import secrets

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from apps.accounts.models import User
from apps.studios.models import Studio, StudioStaff

ROLES = {
    "슈퍼관리자": User.Role.SUPER, "SUPER": User.Role.SUPER,
    "담당자": User.Role.STAFF, "스튜디오 담당자": User.Role.STAFF, "STAFF": User.Role.STAFF,
    "교수": User.Role.PROFESSOR, "PROFESSOR": User.Role.PROFESSOR,
}
# 헷갈리기 쉬운 글자(0/O, 1/l/I)를 뺀 문자
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


def strong_password(groups=3):
    """예: Kq7m-x2Pf-9tWb (약 70비트). 슈퍼관리자는 groups=4 권장."""
    while True:
        pw = "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(groups))
        if any(c.isdigit() for c in pw) and any(c.isupper() for c in pw) and any(c.islower() for c in pw):
            return pw


class Command(BaseCommand):
    help = "CSV(역할,이메일,이름,연락처,담당스튜디오,초기비밀번호)로 배포용 계정을 만든다."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--apply", action="store_true", help="실제로 저장 (없으면 확인만)")
        parser.add_argument("--reset-password", action="store_true", help="이미 있는 계정의 비밀번호를 CSV 값으로 다시 설정")

    def handle(self, csv_path, apply, reset_password, **options):
        rows = self._read(csv_path)
        studios = {s.code: s for s in Studio.objects.all()}
        errors, plans = [], []
        seen = set()
        for line, cols in rows:
            role_txt, email, name, phone, studio_txt, pw = (cols + [""] * 6)[:6]
            email = email.lower()
            if not email:
                self.stdout.write(f"{line}행: 건너뜀 (이메일 비어 있음)")
                continue
            role = ROLES.get(role_txt) or ROLES.get(role_txt.upper())
            try:
                validate_email(email)
            except ValidationError:
                errors.append(f"{line}행: 이메일 형식 오류 ({email})")
                continue
            if email in seen:
                errors.append(f"{line}행: 이메일 중복 ({email})")
                continue
            seen.add(email)
            if not role:
                errors.append(f"{line}행: 역할을 알 수 없음 ({role_txt})")
                continue
            if not name:
                errors.append(f"{line}행: 이름이 비어 있음")
                continue
            codes = [c.strip() for c in studio_txt.split(";") if c.strip()]
            missing = [c for c in codes if c not in studios]
            if missing:
                errors.append(f"{line}행: 없는 스튜디오 {', '.join(missing)} (seed_studios를 먼저 실행하세요)")
                continue
            if codes and role != User.Role.STAFF:
                errors.append(f"{line}행: 담당스튜디오는 담당자만 지정할 수 있음")
                continue
            generated = not pw
            pw = pw or strong_password(4 if role == User.Role.SUPER else 3)
            try:
                validate_password(pw, User(username=email, email=email, name=name))
            except ValidationError as e:
                errors.append(f"{line}행: 비밀번호 규칙 위반 - {' '.join(e.messages)}")
                continue
            plans.append(dict(line=line, role=role, email=email, name=name, phone=phone,
                              studios=[studios[c] for c in codes], password=pw, generated=generated))

        if errors:
            raise CommandError("아래 오류를 고친 뒤 다시 실행하세요. (아무것도 저장하지 않음)\n" + "\n".join(errors))

        with transaction.atomic():
            for p in plans:
                user = User.objects.filter(username__iexact=p["email"]).first()
                if user:
                    status = "기존 계정"
                    if reset_password:
                        user.set_password(p["password"])
                        user.must_change_password = True
                        user.save(update_fields=["password", "must_change_password"])
                        status = "기존 계정, 비밀번호 재설정"
                else:
                    user = User(username=p["email"], email=p["email"], name=p["name"], phone=p["phone"],
                                role=p["role"], must_change_password=True)
                    user.set_password(p["password"])
                    user.save()
                    status = "생성"
                for s in p["studios"]:
                    StudioStaff.objects.get_or_create(studio=s, staff=user)
                shown = f" 비밀번호 {p['password']}" if p["generated"] and status != "기존 계정" else ""
                where = f" [{', '.join(s.code for s in p['studios'])}]" if p["studios"] else ""
                self.stdout.write(f"{p['line']}행: {status} - {user.get_role_display()} {p['name']} {p['email']}{where}{shown}")
            if not apply:
                transaction.set_rollback(True)
        if apply:
            self.stdout.write(self.style.SUCCESS(f"완료: {len(plans)}개 행 처리. 사용한 CSV 파일은 서버에서 지우세요."))
        else:
            self.stdout.write(self.style.WARNING(f"확인만 했습니다 ({len(plans)}개 행). 저장하려면 --apply 를 붙여 다시 실행하세요."))

    def _read(self, path):
        try:
            raw = open(path, "rb").read()
        except OSError as e:
            raise CommandError(f"파일을 열 수 없습니다: {e}")
        for enc in ("utf-8-sig", "cp949"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise CommandError("파일 인코딩을 읽을 수 없습니다. UTF-8 또는 CP949로 저장해 주세요.")
        rows = []
        for i, cols in enumerate(csv.reader(text.splitlines()), start=1):
            cols = [c.strip() for c in cols]
            if i == 1 and cols and cols[0] in ("역할", "role"):
                continue
            if any(cols):
                rows.append((i, cols))
        return rows
