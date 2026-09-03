from django.urls import path

from apps.accounts import customer_views as views

urlpatterns = [
    path("auth/request-otp", views.CustomerRequestOtpView.as_view()),
    path("auth/verify-otp", views.CustomerVerifyOtpView.as_view()),
]
