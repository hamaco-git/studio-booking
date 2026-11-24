from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse_lazy


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.must_change_password = False
        self.request.user.save(update_fields=["must_change_password"])
        messages.success(self.request, "비밀번호를 변경했습니다.")
        return response


@login_required
def home(request):
    """역할별 첫 화면: 담당자·관리자·교수설계자는 현황 달력, 교수는 촬영 예약."""
    if request.user.must_change_password:
        return redirect("password_change")
    if request.user.is_studio_staff or request.user.is_super_admin or request.user.is_designer:
        return redirect("booking:calendar")
    return redirect("booking:book")


def csrf_failure(request, reason=""):
    """보안 토큰(CSRF) 검증 실패 시 영어 오류 화면 대신 한국어 안내를 보여 준다.
    다른 탭에서 로그인·로그아웃해 토큰이 바뀐 뒤 오래된 화면에서 제출하면 주로 발생한다."""
    return render(request, "403_csrf.html", {"retry_url": request.path}, status=403)
