"""시험용 데모 데이터. 개발 PC에서만 사용하세요 (운영 서버 금지).

    uv run python manage.py seed_demo

담당자 staff1~4@demo.local, 교수 prof1~6@demo.local, 교수설계자 designer1~3@demo.local
(비밀번호 모두 demo1234!)과
현재 학기·과목, 이번 주와 다음 주 슬롯, 예약 몇 건을 만든다.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.booking.models import OpenSlot, Reservation, SlotTemplate
from apps.studios.models import Course, CourseProfessor, Semester, Studio, StudioStaff

from .seed_designers import seed_designers

PASSWORD = "demo1234!"


class Command(BaseCommand):
    help = "개발용 데모 계정·과목·슬롯·예약을 만든다 (DEBUG=True에서만)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("DEBUG=True(개발 환경)에서만 실행할 수 있습니다.")
        studios = list(Studio.objects.order_by("code"))
        if len(studios) < 4:
            raise CommandError("먼저 seed_studios를 실행하세요.")

        def user(login, name, role):
            u, created = User.objects.get_or_create(
                username=login, defaults={"name": name, "role": role, "email": login, "must_change_password": False}
            )
            if created:
                u.set_password(PASSWORD)
                u.save()
            return u

        for i, s in enumerate(studios, 1):
            StudioStaff.objects.get_or_create(studio=s, staff=user(f"staff{i}@demo.local", f"담당자{i}", User.Role.STAFF))
        profs = [user(f"prof{i}@demo.local", f"교수{i}", User.Role.PROFESSOR) for i in range(1, 7)]

        today = timezone.localdate()
        sem, _ = Semester.objects.get_or_create(
            name="데모학기", defaults={"start_date": today - timedelta(days=30), "end_date": today + timedelta(days=120),
                                    "is_current": not Semester.objects.filter(is_current=True).exists()}
        )
        courses = []
        for i, p in enumerate(profs):
            c, _ = Course.objects.get_or_create(
                semester=sem, code=f"DEMO{i + 1}", defaults={"name": f"데모과목{i + 1}", "studio": studios[i % 4]}
            )
            CourseProfessor.objects.get_or_create(course=c, professor=p)
            courses.append(c)

        seed_designers()

        monday = today - timedelta(days=today.weekday())
        templates = list(SlotTemplate.objects.filter(is_active=True))
        made = 0
        for s in studios:
            for d in range(12):  # 이번 주·다음 주 평일
                day = monday + timedelta(days=d)
                if day.weekday() >= 5:
                    continue
                for t in templates:
                    _, c = OpenSlot.objects.get_or_create(
                        studio=s, date=day, start_time=t.start_time, end_time=t.end_time, defaults={"label": t.label}
                    )
                    made += c
        for c, p in zip(courses, profs):
            slot = OpenSlot.objects.filter(studio=c.studio, date__gte=today, reservations__isnull=True).first()
            if slot and not Reservation.objects.filter(professor=p).exists():
                Reservation.objects.create(studio=c.studio, course=c, professor=p, slot=slot, date=slot.date,
                                           start_time=slot.start_time, end_time=slot.end_time)
        self.stdout.write(f"완료: 슬롯 {made}개 추가. 담당자 staff1~4@demo.local, 교수 prof1~6@demo.local, "
                          f"교수설계자 designer1~3@demo.local / 비밀번호 {PASSWORD}")
