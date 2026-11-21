from datetime import timedelta

from django import forms

from apps.studios.models import Studio

from .models import Reservation

DATE = forms.DateInput(attrs={"type": "date", "class": "form-control"})
TIME = forms.TimeInput(attrs={"type": "time", "class": "form-control"}, format="%H:%M")


class BlackoutForm(forms.Form):
    studio = forms.ModelChoiceField(
        Studio.objects.none(), required=False, label="스튜디오",
        empty_label="전체 스튜디오", widget=forms.Select(attrs={"class": "form-select"}),
    )
    start_date = forms.DateField(label="시작일", widget=DATE)
    end_date = forms.DateField(label="종료일", required=False, widget=DATE, help_text="하루만이면 비워 두세요.")
    all_day = forms.BooleanField(label="종일", required=False, initial=True,
                                 widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))
    start_time = forms.TimeField(label="시작 시간", required=False, widget=TIME)
    end_time = forms.TimeField(label="종료 시간", required=False, widget=TIME)
    reason = forms.CharField(label="사유", max_length=200, required=False,
                             widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "예: 장비 점검"}))

    def __init__(self, *args, user, studios, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["studio"].queryset = studios
        if not user.is_super_admin:
            # 담당자는 전체 스튜디오 불가일을 만들 수 없다.
            self.fields["studio"].required = True
            self.fields["studio"].empty_label = None

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date") or data.get("start_date")
        if start and end:
            if end < start:
                raise forms.ValidationError("종료일은 시작일보다 같거나 늦어야 합니다.")
            if end - start > timedelta(days=92):
                raise forms.ValidationError("한 번에 최대 3개월까지 등록할 수 있습니다.")
        data["end_date"] = end
        if data.get("all_day"):
            data["start_time"] = data["end_time"] = None
        else:
            st, et = data.get("start_time"), data.get("end_time")
            if not (st and et) or et <= st:
                raise forms.ValidationError("종일이 아니면 시작·종료 시간을 올바르게 입력하세요.")
        return data


class ReservationEditForm(forms.ModelForm):
    class Meta:
        model = Reservation
        fields = ["studio", "date", "start_time", "end_time", "memo"]
        widgets = {
            "studio": forms.Select(attrs={"class": "form-select"}),
            "date": DATE,
            "start_time": TIME,
            "end_time": TIME,
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, studios, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["studio"].queryset = studios
        self.fields["date"].widget.format = "%Y-%m-%d"

    def _get_validation_exclusions(self):
        # 겹침 제약(reservation_no_overlap)의 조건이 status를 참조하므로 검사에서 빼지 않는다.
        exclude = super()._get_validation_exclusions()
        exclude.discard("status")
        return exclude

    def _post_clean(self):
        super()._post_clean()
        # 바뀐 시간에 맞는 슬롯으로 다시 연결
        r = self.instance
        if not self.errors and r.studio_id and r.date and r.start_time and r.end_time:
            from .models import OpenSlot

            r.slot = OpenSlot.objects.filter(
                studio_id=r.studio_id, date=r.date, start_time__lte=r.start_time, end_time__gte=r.end_time,
            ).first()
