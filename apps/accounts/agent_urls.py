from django.urls import path

from apps.accounts import agent_views as views

app_name = "accounts_agent"

urlpatterns = [
    path("auth/login", views.AgentLoginView.as_view(), name="login"),
    path("auth/verify-otp", views.AgentVerifyOtpView.as_view(), name="verify_otp"),
    path("agents", views.AgentListView.as_view(), name="agent_list"),
    path("groups", views.GroupListView.as_view(), name="group_list"),
    path(
        "customers/<uuid:customer_id>",
        views.CustomerDetailView.as_view(),
        name="customer_detail",
    ),
]
