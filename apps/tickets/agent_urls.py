from django.urls import path

from apps.tickets import agent_views as views

app_name = "tickets_agent"

urlpatterns = [
    path("tickets", views.TicketListView.as_view(), name="ticket_list"),
    path(
        "tickets/<uuid:ticket_id>",
        views.TicketDetailView.as_view(),
        name="ticket_detail",
    ),
    path(
        "tickets/<uuid:ticket_id>/messages",
        views.TicketMessageListView.as_view(),
        name="ticket_messages",
    ),
    path(
        "tickets/<uuid:ticket_id>/activities",
        views.TicketActivityListView.as_view(),
        name="ticket_activities",
    ),
]
