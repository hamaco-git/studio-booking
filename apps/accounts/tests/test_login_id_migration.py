from importlib import import_module
from io import StringIO
from contextlib import redirect_stdout

from django.apps import apps as django_apps
from django.test import TestCase

from apps.accounts.models import User

strip_email_domain = import_module("apps.accounts.migrations.0004_login_id_not_email").strip_email_domain


class StripEmailDomainTest(TestCase):
    def run_migration(self):
        out = StringIO()
        with redirect_stdout(out):
            strip_email_domain(django_apps, None)
        return out.getvalue()

    def test_strips_domain_and_keeps_email(self):
        u = User.objects.create_user("prof1@demo.local", password="x", name="교수1")
        keep = User.objects.create_user("admin", password="x", name="관리자", email="a@wcu.ac.kr")
        mailed = User.objects.create_user("kim@wcu.ac.kr", password="x", name="김교수", email="other@wcu.ac.kr")
        out = self.run_migration()
        u.refresh_from_db(); keep.refresh_from_db(); mailed.refresh_from_db()
        self.assertEqual(u.username, "prof1")
        self.assertEqual(u.email, "prof1@demo.local")  # 비어 있던 이메일 칸에 원래 값 보관
        self.assertTrue(u.check_password("x"))
        self.assertEqual(keep.username, "admin")
        self.assertEqual(mailed.username, "kim")
        self.assertEqual(mailed.email, "other@wcu.ac.kr")  # 이미 있던 이메일은 그대로
        self.assertIn("2개 변경", out)

    def test_conflicts_are_left_unchanged_and_reported(self):
        User.objects.create_user("prof1", password="x", name="기존")
        a = User.objects.create_user("prof1@demo.local", password="x", name="데모")
        b = User.objects.create_user("lee@a.kr", password="x", name="이1")
        c = User.objects.create_user("LEE@b.kr", password="x", name="이2")
        out = self.run_migration()
        for u in (a, b, c):
            old = u.username
            u.refresh_from_db()
            self.assertEqual(u.username, old)
        self.assertIn("prof1@demo.local", out)
        self.assertIn("lee@a.kr", out)
        self.assertIn("0개 변경", out)
