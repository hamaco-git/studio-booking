from django.contrib import admin

from .models import Course, CourseProfessor, Semester, Studio, StudioStaff


class StudioStaffInline(admin.TabularInline):
    model = StudioStaff
    extra = 0


@admin.register(Studio)
class StudioAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "location", "color", "is_active")
    inlines = [StudioStaffInline]


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "is_current")


class CourseProfessorInline(admin.TabularInline):
    model = CourseProfessor
    extra = 1
    autocomplete_fields = ["professor"]


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "semester", "studio", "is_active")
    list_filter = ("semester", "studio", "is_active")
    search_fields = ("name", "code")
    inlines = [CourseProfessorInline]
