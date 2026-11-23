import tempfile
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.accounts.models import User
from apps.studios.models import Studio, StudioStaff

CSV = """역할,이메일,이름,연락처,담당스튜디오,초기비밀번호
슈퍼관리자,admin@wcu.ac.kr,관리자,,,Zt4k-Qm8w-Hp3x-Va7n
담당자,s1@wcu.ac.kr,담당자일,,studio1,
교수,,,,,Ab3d-Ef5g-Hj7k
교수,p1@wcu.ac.kr,김교수,010-0000-0000,,Kq7m-x2Pf-9tWb
"""


class LoadAccountsTest(TestCase):
    def setUp(self):
        Studio.objects.create(code="studio1", name="Studio 1")

    def run_cmd(self, text, *args):
        f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        f.write(text)
        f.close()
        out = StringIO()
        call_command("load_accounts", f.name, *args, stdout=out)
        return out.getvalue()

    def test_dry_run_saves_nothing(self):
        self.run_cmd(CSV)
        self.assertFalse(User.objects.exists())

    def test_apply_creates_accounts(self):
        out = self.run_cmd(CSV, "--apply")
        admin = User.objects.get(username="admin@wcu.ac.kr")
        self.assertTrue(admin.is_superuser and admin.must_change_password)
        self.assertTrue(admin.check_password("Zt4k-Qm8w-Hp3x-Va7n"))
        self.assertTrue(StudioStaff.objects.filter(staff__username="s1@wcu.ac.kr", studio__code="studio1").exists())
        self.assertEqual(User.objects.get(username="p1@wcu.ac.kr").role, User.Role.PROFESSOR)
        self.assertEqual(User.objects.count(), 3)  # 이메일 빈 행은 건너뜀
        self.assertIn("건너뜀", out)
        # 다시 실행해도 기존 계정은 그대로
        self.run_cmd(CSV, "--apply")
        self.assertEqual(User.objects.count(), 3)

    def test_weak_password_rejected(self):
        with self.assertRaises(CommandError):
            self.run_cmd("역할,이메일,이름,연락처,담당스튜디오,초기비밀번호\n교수,p2@wcu.ac.kr,박교수,,,1234\n", "--apply")
        self.assertFalse(User.objects.exists())
