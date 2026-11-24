"""시험용 교수설계자 샘플 계정. 개발 PC에서만 사용하세요 (운영 서버 금지).

    uv run python manage.py seed_designers

교수설계자1~3 (designer1~3@demo.local, 비밀번호 demo1234!)을 만들고,
현재 학기 과목 중 교수설계자가 아직 없는 과목에 돌아가며 배정한다.
여러 번 실행해도 이미 있는 계정·배정은 바꾸지 않는다.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.studios.models import Course, Semester

PASSWORD = "demo1234!"


def seed_designers():
    designers = []
    for i in range(1, 4):
        login = f"designer{i}@demo.local"
        u, created = User.objects.get_or_create(
            username=login,
            defaults={"name": f"교수설계자{i}", "role": User.Role.DESIGNER, "email": login,
                      "must_change_password": False},
        )
        if created:
            u.set_password(PASSWORD)
            u.save()
        designers.append(u)

    sem = Semester.objects.filter(is_current=True).first() or Semester.objects.first()
    assigned = 0
    if sem:
        todo = Course.objects.filter(semester=sem, designer__isnull=True).order_by("studio__code", "name")
        for n, c in enumerate(todo):
            c.designer = designers[n % len(designers)]
            c.save(update_fields=["designer"])
            assigned += 1
    return designers, assigned


class Command(BaseCommand):
    help = "개발용 교수설계자 샘플 계정 3개를 만들고 현재 학기 과목에 배정한다 (DEBUG=True에서만)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("DEBUG=True(개발 환경)에서만 실행할 수 있습니다. "
                               "예: DEBUG=True uv run python manage.py seed_designers")
        _, assigned = seed_designers()
        self.stdout.write(f"완료: 교수설계자1~3 (designer1~3@demo.local / {PASSWORD}), 과목 {assigned}개에 배정")
