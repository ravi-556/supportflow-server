from django.urls import path

from apps.support import customer_views as views

app_name = "support_customer"

urlpatterns = [
    path(
        "kb/articles/popular",
        views.KbArticlePopularView.as_view(),
        name="kb_article_popular",
    ),
    path(
        "kb/articles/<uuid:article_id>",
        views.KbArticleDetailView.as_view(),
        name="kb_article_detail",
    ),
    path("kb/articles", views.KbArticleListView.as_view(), name="kb_article_list"),
    path("csat/<uuid:review_id>", views.CsatReviewView.as_view(), name="csat_review"),
]
