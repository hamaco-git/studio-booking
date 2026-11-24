from django.urls import path

from . import views

app_name = "manage"

urlpatterns = [
    path("semesters/", views.semesters, name="semesters"),
    path("semesters/<int:pk>/current/", views.semester_current, name="semester_current"),
    path("courses/", views.courses, name="courses"),
    path("courses/new/", views.course_edit, name="course_new"),
    path("courses/<int:pk>/", views.course_edit, name="course_edit"),
    path("courses/import/", views.courses_import, name="courses_import"),
    path("courses/import/template.csv", views.courses_import_template, name="courses_import_template"),
    path("courses/export.csv", views.courses_export, name="courses_export"),
    path("users/", views.users, name="users"),
    path("users/new/", views.user_edit, name="user_new"),
    path("users/<int:pk>/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/reset-password/", views.user_reset_password, name="user_reset_password"),
    path("users/import/", views.users_import, name="users_import"),
    path("users/import/template.csv", views.users_import_template, name="users_import_template"),
    path("users/import/result.csv", views.users_import_result, name="users_import_result"),
    path("logs/", views.logs, name="logs"),
]
