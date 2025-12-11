"""
URL configuration for core app.

Handles URLs for core person-related models: SystemUser, SchoolStaff, and Students.
"""
from django.urls import path
from core import views

app_name = "core"

urlpatterns = [
    # Dashboard
    path("", views.dashboard, name="dashboard"),

    # School Staff
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/<int:pk>/", views.staff_detail, name="staff_detail"),
    path(
        "staff/<int:staff_id>/assignment/<int:pk>/edit/",
        views.staff_assignment_edit,
        name="staff_assignment_edit",
    ),
    path(
        "staff/<int:staff_id>/assignment/<int:pk>/delete/",
        views.staff_assignment_delete,
        name="staff_assignment_delete",
    ),

    # System Users
    path("system-users/", views.system_user_list, name="system_user_list"),
    path("system-users/<int:pk>/", views.system_user_detail, name="system_user_detail"),

    # Students
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

    # Pending Users (role assignment)
    path("pending-users/", views.pending_users_list, name="pending_users_list"),
    path(
        "pending-users/<int:user_id>/assign-school-staff/",
        views.assign_school_staff,
        name="assign_school_staff",
    ),
    path(
        "pending-users/<int:user_id>/assign-system-user/",
        views.assign_system_user,
        name="assign_system_user",
    ),
    path(
        "pending-users/<int:user_id>/delete/",
        views.delete_pending_user,
        name="delete_pending_user",
    ),
]
