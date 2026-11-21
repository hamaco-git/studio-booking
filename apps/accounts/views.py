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
    """역할별 첫 화면. 예약 달력 등 실제 화면은 다음 단계에서 붙인다."""
    if request.user.must_change_password:
        return redirect("password_change")
    if request.user.is_studio_staff or request.user.is_super_admin:
        return redirect("booking:calendar")
    return render(request, "home.html")
