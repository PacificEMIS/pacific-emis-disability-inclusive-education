from django.urls import path
from . import views

app_name = "inclusive_ed"  # optional

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    #path("dashboard/", views.dashboard, name="dashboard"),
    path("students/", views.student_list, name="student_list"),
    path("students/new/", views.new_student, name="new_student"),
]
