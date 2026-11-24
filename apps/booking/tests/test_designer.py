from datetime import date
from io import BytesIO, StringIO

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.studios.models import Course, CourseProfessor, Semester

from .test_staff import MON, StaffBase


class DesignerBase(StaffBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.designer = User.objects.create_user("d1", password="x", name="설계1",
                                                role=User.Role.DESIGNER, must_change_password=False)
        cls.designer2 = User.objects.create_user("d2", password="x", name="설계2",
                                                 role=User.Role.DESIGNER, must_change_password=False)
        cls.course.designer = cls.designer
        cls.course.save()
        cls.course2 = Course.objects.create(semester=cls.course.semester, code="C2", name="다른과목",
                                            studio=cls.s2, designer=cls.designer2)
        CourseProfessor.objects.create(course=cls.course2, professor=cls.other)

    def setUp(self):
        self.mine = self.reserve(self.slot())
        s2 = self.slot(studio=self.s2)
        self.theirs = type(self.mine).objects.create(
            studio=self.s2, course=self.course2, professor=self.other, slot=s2, date=s2.date,
            start_time=s2.start_time, end_time=s2.end_time)

    def events(self, **params):
        p = {"start": MON.isoformat(), "end": date(2027, 3, 15).isoformat(), **params}
        return self.client.get(reverse("booking:events"), p).json()


class DesignerAccessTest(DesignerBase):
    def test_home_goes_to_calendar(self):
        self.client.force_login(self.designer)
        self.assertRedirects(self.client.get(reverse("home")), reverse("booking:calendar"))

    def test_can_view_calendar_and_list_only(self):
        self.client.force_login(self.designer)
        for name in ["calendar", "reservations", "reservations_export"]:
            self.assertEqual(self.client.get(reverse(f"booking:{name}")).status_code, 200, name)
        for name in ["week_slots", "blackouts", "records", "book", "my_reservations"]:
            self.assertEqual(self.client.get(reverse(f"booking:{name}")).status_code, 403, name)
        self.assertEqual(self.client.get(reverse("manage:courses")).status_code, 403)
        self.assertEqual(self.client.get(reverse("booking:reservation_edit", args=[self.mine.pk])).status_code, 403)
        res = self.client.post(reverse("booking:reservation_cancel", args=[self.mine.pk]))
        self.assertEqual(res.status_code, 403)

    def test_events_only_own_courses_without_slots(self):
        self.client.force_login(self.designer)
        evs = self.events()
        kinds = {e["extendedProps"]["kind"] for e in evs}
        self.assertNotIn("slot", kinds)
        rids = [e["extendedProps"]["id"] for e in evs if e["extendedProps"]["kind"] == "reservation"]
        self.assertEqual(rids, [self.mine.pk])
        self.assertIn("김교수", evs[0]["title"])

    def test_designer_param_ignored_for_designer(self):
        self.client.force_login(self.designer)
        rids = [e["extendedProps"]["id"] for e in self.events(designer=self.designer2.pk)
                if e["extendedProps"]["kind"] == "reservation"]
        self.assertEqual(rids, [self.mine.pk])

    def test_list_only_own_courses_without_edit_buttons(self):
        self.client.force_login(self.designer)
        res = self.client.get(reverse("booking:reservations"), {"start": MON.isoformat()})
        self.assertContains(res, "영상제작")
        self.assertNotContains(res, "다른과목")
        self.assertNotContains(res, "수정·취소")
        self.assertContains(res, "촬영 일정 목록")


class StaffDesignerFilterTest(DesignerBase):
    def test_calendar_filter_by_designer(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("booking:calendar")), "전체 교수설계자")
        evs = self.events(designer=self.designer2.pk)
        rids = [e["extendedProps"]["id"] for e in evs if e["extendedProps"]["kind"] == "reservation"]
        self.assertEqual(rids, [self.theirs.pk])
        self.assertFalse([e for e in evs if e["extendedProps"]["kind"] == "slot"])
        # 필터가 없으면 전체 예약이 보인다
        self.assertEqual(len([e for e in self.events() if e["extendedProps"]["kind"] == "reservation"]), 2)

    def test_list_filter_by_designer(self):
        self.client.force_login(self.staff)
        res = self.client.get(reverse("booking:reservations"), {"start": MON.isoformat(), "designer": self.designer.pk})
        self.assertContains(res, "영상제작")
        self.assertNotContains(res, "다른과목")

    def test_export_has_designer_column(self):
        from openpyxl import load_workbook

        self.client.force_login(self.staff)
        res = self.client.get(reverse("booking:reservations_export"), {"start": MON.isoformat()})
        ws = load_workbook(BytesIO(res.content)).active
        header = [c.value for c in ws[1]]
        col = header.index("교수설계자")
        self.assertEqual({row[col].value for row in ws.iter_rows(min_row=2)}, {"설계1", "설계2"})

    def test_course_form_assigns_designer(self):
        self.client.force_login(self.admin)
        url = reverse("manage:course_edit", args=[self.course2.pk])
        self.assertContains(self.client.get(url), "담당 교수설계자")
        res = self.client.post(url, {
            "semester": self.course2.semester_id, "code": "C2", "name": "다른과목", "studio": self.s2.pk,
            "professors": [self.other.pk], "designer": self.designer.pk, "is_active": "on",
        })
        self.assertEqual(res.status_code, 302)
        self.course2.refresh_from_db()
        self.assertEqual(self.course2.designer, self.designer)
        self.assertContains(self.client.get(reverse("manage:courses")), "설계1")


class SeedDesignersTest(DesignerBase):
    @override_settings(DEBUG=True)
    def test_seed_creates_three_and_assigns_unassigned_courses(self):
        Semester.objects.update(is_current=True)
        c3 = Course.objects.create(semester=self.course.semester, code="C3", name="새과목", studio=self.s1)
        call_command("seed_designers", stdout=StringIO())
        names = set(User.objects.filter(role=User.Role.DESIGNER, username__startswith="designer")
                    .values_list("name", flat=True))
        self.assertEqual(names, {"교수설계자1", "교수설계자2", "교수설계자3"})
        c3.refresh_from_db()
        self.assertEqual(c3.designer.name, "교수설계자1")
        self.course.refresh_from_db()
        self.assertEqual(self.course.designer, self.designer)  # 이미 배정된 과목은 그대로
        call_command("seed_designers", stdout=StringIO())
        self.assertEqual(User.objects.filter(username__startswith="designer").count(), 3)
        u = User.objects.get(username="designer1")
        self.assertTrue(u.check_password("demo1234!"))
