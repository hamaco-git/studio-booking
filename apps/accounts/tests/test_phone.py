from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from apps.accounts.models import User
from apps.accounts.phone import normalize_phone, validate_phone


class PhoneFormatTest(SimpleTestCase):
    def test_normalize(self):
        for raw in ["01012345678", "010-1234-5678", "010 1234 5678", "+82 10-1234-5678", "010.1234.5678"]:
            self.assertEqual(normalize_phone(raw), "010-1234-5678", raw)
        self.assertEqual(normalize_phone("0111234567"), "011-123-4567")
        self.assertEqual(normalize_phone(""), "")
        self.assertEqual(normalize_phone(" 02-123-4567 "), "02-123-4567")  # 휴대폰이 아니면 그대로

    def test_validate(self):
        validate_phone("")
        validate_phone("010-1234-5678")
        for bad in ["02-123-4567", "1234", "010-12-34"]:
            with self.assertRaises(ValidationError):
                validate_phone(bad)


class PhoneSaveTest(TestCase):
    def test_saved_normalized(self):
        u = User.objects.create_user("p", password="x", name="교수", phone="01098765432")
        u.refresh_from_db()
        self.assertEqual(u.phone, "010-9876-5432")
