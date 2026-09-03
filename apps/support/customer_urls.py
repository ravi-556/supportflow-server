from django.urls import path

from apps.support import customer_views as views

urlpatterns = [
    path("kb/articles/popular", views.KbArticlePopularView.as_view()),
    path("kb/articles/<uuid:article_id>", views.KbArticleDetailView.as_view()),
    path("kb/articles", views.KbArticleListView.as_view()),
    path("csat/<uuid:review_id>", views.CsatReviewView.as_view()),
]
