"""기존 데이터 채우기: 취소된 예약의 취소 일시·취소한 사람, 작업 이력의 대상 설명."""

from django.db import migrations


def backfill(apps, schema_editor):
    Reservation = apps.get_model("booking", "Reservation")
    AuditLog = apps.get_model("booking", "AuditLog")

    for r in Reservation.objects.filter(status="CANCELLED", cancelled_at__isnull=True):
        log = AuditLog.objects.filter(
            target_table="booking_reservation", target_id=r.pk, action="CANCEL",
        ).order_by("-created_at").first()
        Reservation.objects.filter(pk=r.pk).update(
            cancelled_at=log.created_at if log else r.updated_at,
            cancelled_by_id=log.user_id if log else r.updated_by_id,
        )

    reservations = {
        r.pk: r for r in Reservation.objects.select_related("studio", "professor", "course")
    }
    for log in AuditLog.objects.filter(target_table="booking_reservation", summary=""):
        r = reservations.get(log.target_id)
        if r:
            log.summary = (f"{r.studio.code} {r.date:%Y-%m-%d} {r.start_time:%H:%M}~{r.end_time:%H:%M} "
                           f"{r.professor.name} · {r.course.name}")[:200]
            log.save(update_fields=["summary"])


class Migration(migrations.Migration):
    dependencies = [("booking", "0004_attendance_and_audit")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
