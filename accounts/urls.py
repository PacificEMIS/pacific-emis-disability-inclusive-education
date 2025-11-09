from django.urls import path
from . import views

app_name = "accounts"  # optional

urlpatterns = [    
    path("accounts/login/", views.sign_in, name="login"),
    path("logout/", views.sign_out, name="logout"),
    path("staff/", views.staff_list, name="staff_list"),
]



