from django.urls import path

from apps.accounts import agent_views as views

urlpatterns = [
    path("auth/login", views.AgentLoginView.as_view()),
    path("auth/verify-otp", views.AgentVerifyOtpView.as_view()),
    path("agents", views.AgentListView.as_view()),
    path("groups", views.GroupListView.as_view()),
    path("customers/<uuid:customer_id>", views.CustomerDetailView.as_view()),
]
