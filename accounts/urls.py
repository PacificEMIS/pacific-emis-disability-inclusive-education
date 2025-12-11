from django.urls import path
from accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.sign_in, name="login"),
    path("logout/", views.sign_out, name="logout"),
    path("after-login/", views.post_login_router, name="post_login_router"),
    path("no-permissions/", views.no_permissions, name="no_permissions"),
]
