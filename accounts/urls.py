from django.urls import path
from accounts import views

app_name = "accounts"  # optional

urlpatterns = [    
    path("login/", views.sign_in, name="login"),
    path("logout/", views.sign_out, name="logout"),
    path("staff/", views.staff_list, name="staff_list"),

    path("after-login/", views.post_login_router, name="post_login_router"),
    path("no-permissions/", views.no_permissions, name="no_permissions"),
]



