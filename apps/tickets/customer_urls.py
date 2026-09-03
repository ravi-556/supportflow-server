from django.urls import path

from apps.tickets import customer_views as views

urlpatterns = [
    path("tickets", views.CustomerTicketListView.as_view()),
    path("tickets/<uuid:ticket_id>", views.CustomerTicketDetailView.as_view()),
    path("tickets/<uuid:ticket_id>/messages", views.CustomerTicketMessageListView.as_view()),
    path("guest-tickets/otp", views.GuestTicketOtpRequestView.as_view()),
    path("guest-tickets", views.GuestTicketSubmitView.as_view()),
]
