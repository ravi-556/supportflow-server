from django.urls import path

from apps.tickets import agent_views as views

urlpatterns = [
    path("tickets", views.TicketListView.as_view()),
    path("tickets/<uuid:ticket_id>", views.TicketDetailView.as_view()),
    path("tickets/<uuid:ticket_id>/messages", views.TicketMessageListView.as_view()),
    path("tickets/<uuid:ticket_id>/activities", views.TicketActivityListView.as_view()),
]
