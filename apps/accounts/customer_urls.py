from django.urls import path

from apps.accounts import customer_views as views

app_name = "accounts_customer"

urlpatterns = [
    path("auth/request-otp", views.CustomerRequestOtpView.as_view(), name="request_otp"),
    path("auth/verify-otp", views.CustomerVerifyOtpView.as_view(), name="verify_otp"),
]
