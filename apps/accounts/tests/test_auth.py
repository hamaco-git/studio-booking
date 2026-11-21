from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User


class AuthFlowTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("kim@wcu.ac.kr", password="Init-pass-123", name="김교수")

    def test_home_requires_login(self):
        res = self.client.get(reverse("home"))
        self.assertRedirects(res, f"{reverse('login')}?next=/")

    def test_first_login_forces_password_change(self):
        self.client.login(username="kim@wcu.ac.kr", password="Init-pass-123")
        self.assertRedirects(self.client.get(reverse("home")), reverse("password_change"))
        res = self.client.post(reverse("password_change"), {
            "old_password": "Init-pass-123",
            "new_password1": "Studio-new-2027!",
            "new_password2": "Studio-new-2027!",
        })
        self.assertRedirects(res, reverse("home"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertFalse(self.user.must_change_password)
        self.assertRedirects(self.client.get(reverse("home")), reverse("booking:book"))

    def test_super_role_gets_admin_rights(self):
        u = User.objects.create_user("admin@wcu.ac.kr", password="x", name="관리자", role=User.Role.SUPER)
        self.assertTrue(u.is_staff and u.is_superuser)

    def test_createsuperuser_is_super_role(self):
        u = User.objects.create_superuser("root@wcu.ac.kr", "root@wcu.ac.kr", "x", name="관리자")
        self.assertEqual(u.role, User.Role.SUPER)
        self.assertFalse(u.must_change_password)


class CsrfFailureTest(TestCase):
    def test_stale_token_shows_korean_retry_page(self):
        client = self.client_class(enforce_csrf_checks=True)
        client.get(reverse("login"))
        res = client.post(reverse("login"), {
            "csrfmiddlewaretoken": "x" * 32,
            "username": "a@wcu.ac.kr",
            "password": "x",
        })
        self.assertEqual(res.status_code, 403)
        self.assertContains(res, "새로고침 후 다시 시도해 주세요", status_code=403)
        self.assertContains(res, f'href="{reverse("login")}"', status_code=403)
