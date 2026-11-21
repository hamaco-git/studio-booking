from datetime import date, time

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import User
from apps.booking.models import Blackout, OpenSlot, Reservation
from apps.studios.models import Course, CourseProfessor, Semester, Studio

DAY = date(2027, 3, 8)


class BookingRulesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.s1 = Studio.objects.create(code="studio1", name="Studio 1")
        cls.s2 = Studio.objects.create(code="studio2", name="Studio 2")
        sem = Semester.objects.create(name="2027-1", start_date=date(2027, 3, 1), end_date=date(2027, 6, 30))
        cls.prof = User.objects.create_user("kim@wcu.ac.kr", password="x", name="김교수", role=User.Role.PROFESSOR)
        cls.other = User.objects.create_user("lee@wcu.ac.kr", password="x", name="이교수", role=User.Role.PROFESSOR)
        cls.course = Course.objects.create(semester=sem, code="C101", name="영상제작", studio=cls.s1)
        CourseProfessor.objects.create(course=cls.course, professor=cls.prof)
        cls.am = OpenSlot.objects.create(studio=cls.s1, date=DAY, start_time=time(9), end_time=time(12), label="오전")
        cls.pm = OpenSlot.objects.create(studio=cls.s1, date=DAY, start_time=time(13), end_time=time(18), label="오후")

    def make(self, slot=None, **kw):
        slot = slot or self.am
        data = dict(studio=slot.studio, course=self.course, professor=self.prof, slot=slot,
                    date=slot.date, start_time=slot.start_time, end_time=slot.end_time)
        data.update(kw)
        return Reservation(**data)

    def test_valid_reservation(self):
        r = self.make()
        r.full_clean()
        r.save()

    def test_db_blocks_overlapping_confirmed_reservations(self):
        self.make().save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make().save()

    def test_cancelled_reservation_frees_slot(self):
        self.make(status=Reservation.Status.CANCELLED).save()
        self.make().save()

    def test_other_slot_same_day_ok(self):
        self.make().save()
        self.make(slot=self.pm).save()

    def test_overlapping_slots_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            OpenSlot.objects.create(studio=self.s1, date=DAY, start_time=time(11), end_time=time(14))

    def test_same_time_different_studio_ok(self):
        OpenSlot.objects.create(studio=self.s2, date=DAY, start_time=time(9), end_time=time(12))

    def test_clean_rejects_wrong_studio(self):
        slot = OpenSlot.objects.create(studio=self.s2, date=DAY, start_time=time(9), end_time=time(12))
        with self.assertRaisesMessage(ValidationError, "지정된 스튜디오"):
            self.make(slot=slot).full_clean()

    def test_clean_rejects_professor_not_on_course(self):
        with self.assertRaisesMessage(ValidationError, "담당하는 과목"):
            self.make(professor=self.other).full_clean()

    def test_clean_rejects_outside_open_slot(self):
        with self.assertRaisesMessage(ValidationError, "예약 가능 시간"):
            self.make(start_time=time(12), end_time=time(13)).full_clean()

    def test_clean_rejects_blackout_all_studios(self):
        Blackout.objects.create(date=DAY, reason="장비 점검")
        with self.assertRaisesMessage(ValidationError, "촬영 불가일"):
            self.make().full_clean()

    def test_clean_rejects_partial_blackout(self):
        Blackout.objects.create(studio=self.s1, date=DAY, start_time=time(10), end_time=time(11))
        with self.assertRaisesMessage(ValidationError, "촬영 불가일"):
            self.make().full_clean()
        self.make(slot=self.pm).full_clean()
