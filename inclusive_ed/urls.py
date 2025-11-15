from django.urls import path
from inclusive_ed import views

app_name = "inclusive_ed"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("students/", views.student_list, name="student_list"),
    path("students/new/", views.student_new, name="student_new"),
    path("students/matches/", views.student_matches, name="student_matches"),
    path("students/<int:pk>/", views.student_detail, name="student_detail"),
    path("students/<int:pk>/edit/", views.student_edit, name="student_edit"),
    path(
        "students/<int:student_pk>/enrolments/new/",
        views.student_enrolment_add,
        name="student_enrolment_add",
    ),
    path(
        "students/<int:student_pk>/enrolments/<int:enrolment_pk>/edit/",
        views.student_enrolment_edit,
        name="student_enrolment_edit",
    ),
    path(
        "students/<int:student_pk>/enrolments/<int:enrolment_pk>/delete/",
        views.student_enrolment_delete,
        name="student_enrolment_delete",
    ),
]
