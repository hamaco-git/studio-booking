from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """임시(초기) 비밀번호로 로그인한 계정은 비밀번호를 바꾸기 전까지 다른 화면으로 가지 못하게 한다."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.must_change_password:
            allowed = (reverse("password_change"), reverse("logout"))
            static = request.path.startswith("/static/")
            if request.path not in allowed and not static:
                return redirect("password_change")
        return self.get_response(request)
