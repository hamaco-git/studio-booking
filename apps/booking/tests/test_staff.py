from datetime import date, time, timedelta

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.booking import services
from apps.booking.models import AuditLog, Blackout, OpenSlot, Reservation, SlotTemplate
from apps.studios.models import Course, CourseProfessor, Semester, Studio, StudioStaff

MON = date(2027, 3, 8)  # 월요일


class StaffBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.s1 = Studio.objects.create(code="studio1", name="Studio 1")
        cls.s2 = Studio.objects.create(code="studio2", name="Studio 2")
        cls.staff = User.objects.create_user("staff1@wcu.ac.kr", password="x", name="담당1",
                                             role=User.Role.STAFF, must_change_password=False)
        StudioStaff.objects.create(studio=cls.s1, staff=cls.staff)
        cls.admin = User.objects.create_user("admin@wcu.ac.kr", password="x", name="관리자",
                                             role=User.Role.SUPER, must_change_password=False)
        cls.prof = User.objects.create_user("kim@wcu.ac.kr", password="x", name="김교수",
                                            role=User.Role.PROFESSOR, must_change_password=False)
        cls.other = User.objects.create_user("lee@wcu.ac.kr", password="x", name="이교수",
                                             role=User.Role.PROFESSOR, must_change_password=False)
        sem = Semester.objects.create(name="2027-1", start_date=date(2027, 3, 1), end_date=date(2027, 6, 30))
        cls.course = Course.objects.create(semester=sem, code="C1", name="영상제작", studio=cls.s1)
        CourseProfessor.objects.create(course=cls.course, professor=cls.prof)
        cls.am, cls.pm = SlotTemplate.objects.order_by("order")[:2]

    def slot(self, studio=None, day=MON, tpl=None):
        tpl = tpl or self.am
        return OpenSlot.objects.create(studio=studio or self.s1, date=day, start_time=tpl.start_time,
                                       end_time=tpl.end_time, label=tpl.label)

    def reserve(self, slot, prof=None):
        return Reservation.objects.create(studio=slot.studio, course=self.course, professor=prof or self.prof,
                                          slot=slot, date=slot.date, start_time=slot.start_time,
                                          end_time=slot.end_time)


class PermissionTest(StaffBase):
    def test_professor_cannot_open_staff_pages(self):
        self.client.force_login(self.prof)
        for name in ["calendar", "week_slots", "blackouts", "reservations"]:
            self.assertEqual(self.client.get(reverse(f"booking:{name}")).status_code, 403, name)

    def test_staff_home_goes_to_calendar(self):
        self.client.force_login(self.staff)
        self.assertRedirects(self.client.get(reverse("home")), reverse("booking:calendar"))

    def test_staff_cannot_edit_other_studio_slots(self):
        self.client.force_login(self.staff)
        res = self.client.post(reverse("booking:week_slots"),
                               {"studio": self.s2.pk, "week": MON.isoformat(), "cell": [f"{MON}_{self.am.pk}"]})
        # 담당이 아닌 스튜디오 값은 무시되고 담당 스튜디오(studio1)로 처리된다
        self.assertEqual(res.status_code, 302)
        self.assertFalse(OpenSlot.objects.filter(studio=self.s2).exists())
        self.assertTrue(OpenSlot.objects.filter(studio=self.s1).exists())

    def test_staff_cannot_edit_other_studio_reservation(self):
        r = self.reserve(self.slot(studio=self.s2))
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("booking:reservation_edit", args=[r.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("booking:reservation_cancel", args=[r.pk])).status_code, 403)

    def test_staff_cannot_create_all_studio_blackout(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("booking:blackouts"), {"studio": "", "start_date": MON, "all_day": "on"})
        self.assertFalse(Blackout.objects.exists())

    def test_super_admin_can_create_all_studio_blackout(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("booking:blackouts"), {"studio": "", "start_date": MON, "all_day": "on"})
        self.assertTrue(Blackout.objects.filter(studio__isnull=True).exists())


class WeekSlotsTest(StaffBase):
    def setUp(self):
        self.client.force_login(self.staff)

    def post_week(self, cells, **extra):
        data = {"studio": self.s1.pk, "week": MON.isoformat(), "cell": cells, **extra}
        return self.client.post(reverse("booking:week_slots"), data)

    def test_page_renders(self):
        res = self.client.get(reverse("booking:week_slots"), {"week": (MON + timedelta(days=3)).isoformat()})
        self.assertContains(res, "2027년 3월 8일")
        self.assertContains(res, "오전")

    def test_save_creates_and_deletes(self):
        self.post_week([f"{MON}_{self.am.pk}", f"{MON}_{self.pm.pk}", f"{MON + timedelta(days=1)}_{self.am.pk}"])
        self.assertEqual(OpenSlot.objects.filter(studio=self.s1).count(), 3)
        self.post_week([f"{MON}_{self.am.pk}"])
        self.assertEqual(OpenSlot.objects.filter(studio=self.s1).count(), 1)
        self.assertEqual(AuditLog.objects.filter(target_table="booking_openslot", action="DELETE").count(), 2)

    def test_reserved_slot_is_kept(self):
        s = self.slot()
        self.reserve(s)
        self.post_week([])
        self.assertTrue(OpenSlot.objects.filter(pk=s.pk).exists())

    def test_copy_previous_week(self):
        self.slot(day=MON - timedelta(days=7))
        self.slot(day=MON - timedelta(days=5), tpl=self.pm)
        self.post_week([], copy_prev="1")
        days = sorted(OpenSlot.objects.filter(date__gte=MON).values_list("date", flat=True))
        self.assertEqual(days, [MON, MON + timedelta(days=2)])

    def test_overlap_with_custom_slot_is_reported(self):
        OpenSlot.objects.create(studio=self.s1, date=MON, start_time=time(11), end_time=time(14))
        res = services.save_week(self.staff, self.s1, MON, {f"{MON}_{self.am.pk}"})
        self.assertEqual(res.created, 0)
        self.assertEqual(len(res.conflicts), 1)


class BlackoutTest(StaffBase):
    def setUp(self):
        self.client.force_login(self.staff)

    def test_range_creates_one_row_per_day_and_warns(self):
        self.reserve(self.slot(day=MON + timedelta(days=1)))
        res = self.client.post(reverse("booking:blackouts"), {
            "studio": self.s1.pk, "start_date": MON, "end_date": MON + timedelta(days=2),
            "all_day": "on", "reason": "장비 점검",
        }, follow=True)
        self.assertEqual(Blackout.objects.count(), 3)
        self.assertContains(res, "확정 예약 1건")

    def test_partial_day_requires_times(self):
        self.client.post(reverse("booking:blackouts"), {"studio": self.s1.pk, "start_date": MON})
        self.assertFalse(Blackout.objects.exists())

    def test_delete(self):
        b = Blackout.objects.create(studio=self.s1, date=MON)
        self.client.post(reverse("booking:blackout_delete", args=[b.pk]))
        self.assertFalse(Blackout.objects.exists())


class ReservationManageTest(StaffBase):
    def setUp(self):
        self.client.force_login(self.staff)

    def test_cancel_logs_audit(self):
        r = self.reserve(self.slot())
        self.client.post(reverse("booking:reservation_cancel", args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.CANCELLED)
        self.assertTrue(AuditLog.objects.filter(target_id=r.pk, action="CANCEL").exists())

    def test_move_to_other_open_slot(self):
        r = self.reserve(self.slot())
        pm = self.slot(tpl=self.pm)
        res = self.client.post(reverse("booking:reservation_edit", args=[r.pk]), {
            "studio": self.s1.pk, "date": MON, "start_time": "13:00", "end_time": "18:00", "memo": "오후로 변경",
        })
        self.assertRedirects(res, reverse("booking:reservations"))
        r.refresh_from_db()
        self.assertEqual(r.slot, pm)
        self.assertEqual(r.updated_by, self.staff)

    def test_move_to_unopened_time_rejected(self):
        r = self.reserve(self.slot())
        res = self.client.post(reverse("booking:reservation_edit", args=[r.pk]), {
            "studio": self.s1.pk, "date": MON, "start_time": "19:00", "end_time": "20:00",
        })
        self.assertContains(res, "예약 가능 시간이 아닙니다")

    def test_list_filters(self):
        self.reserve(self.slot())
        res = self.client.get(reverse("booking:reservations"), {"start": MON, "end": MON, "q": "김"})
        self.assertContains(res, "김교수")
        res = self.client.get(reverse("booking:reservations"), {"start": MON, "end": MON, "q": "박"})
        self.assertNotContains(res, "김교수")


class EventsApiTest(StaffBase):
    def get(self, user, **params):
        self.client.force_login(user)
        return self.client.get(reverse("booking:events"), {"start": MON, "end": MON + timedelta(days=7), **params}).json()

    def test_staff_sees_names_and_free_slots(self):
        self.reserve(self.slot())
        self.slot(tpl=self.pm)
        Blackout.objects.create(studio=None, date=MON + timedelta(days=1), reason="휴일")
        kinds = {e["extendedProps"]["kind"]: e for e in self.get(self.staff)}
        self.assertIn("김교수", kinds["reservation"]["title"])
        self.assertIn("예약 가능", kinds["slot"]["title"])
        self.assertTrue(kinds["blackout"]["allDay"])

    def test_professor_sees_only_assigned_studio_and_no_other_names(self):
        CourseProfessor.objects.create(course=self.course, professor=self.other)
        self.reserve(self.slot(), prof=self.other)
        self.slot(studio=self.s2)
        events = self.get(self.prof)
        self.assertTrue(all(e["extendedProps"].get("studio", self.s1.pk) == self.s1.pk for e in events))
        res = [e for e in events if e["extendedProps"]["kind"] == "reservation"][0]
        self.assertNotIn("이교수", res["title"])
        self.assertIn("예약됨", res["title"])

    def test_calendar_page_renders(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("booking:calendar")), "현황 달력")
