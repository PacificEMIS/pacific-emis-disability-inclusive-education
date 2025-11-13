from django.urls import path
from . import views

app_name = "inclusive_ed"  # optional

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("students/", views.student_list, name="student_list"),
    path("students/new/", views.student_new, name="student_new"),
    path("students/<int:pk>/", views.student_detail, name="student_detail")
]
