from django.urls import path
from accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.sign_in, name="login"),
    path("logout/", views.sign_out, name="logout"),
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/<int:pk>/", views.staff_detail, name="staff_detail"),
    path(
        "staff/<int:staff_id>/membership/<int:pk>/edit/",
        views.staff_membership_edit,
        name="staff_membership_edit",
    ),
    path(
        "staff/<int:staff_id>/membership/<int:pk>/delete/",
        views.staff_membership_delete,
        name="staff_membership_delete",
    ),
    path("after-login/", views.post_login_router, name="post_login_router"),
    path("no-permissions/", views.no_permissions, name="no_permissions"),
]
