from django.urls import path

from apps.tickets import customer_views as views

app_name = "tickets_customer"

urlpatterns = [
    path("tickets", views.CustomerTicketListView.as_view(), name="ticket_list"),
    path(
        "tickets/<uuid:ticket_id>",
        views.CustomerTicketDetailView.as_view(),
        name="ticket_detail",
    ),
    path(
        "tickets/<uuid:ticket_id>/messages",
        views.CustomerTicketMessageListView.as_view(),
        name="ticket_messages",
    ),
    path(
        "guest-tickets/otp",
        views.GuestTicketOtpRequestView.as_view(),
        name="guest_ticket_otp",
    ),
    path(
        "guest-tickets",
        views.GuestTicketSubmitView.as_view(),
        name="guest_ticket_submit",
    ),
]
