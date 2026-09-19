from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.support import services
from apps.support.serializers import (
    CsatReviewSerializer,
    CsatSubmitSerializer,
    FaqDetailSerializer,
    FaqListItemSerializer,
)


class KbArticleListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        query = request.query_params.get("q", "")
        articles = services.search_articles(query)
        # Public endpoint, so this is also the cheap defence against an
        # unbounded scan of every published article on a blank `q`.
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(articles, request, view=self)
        return paginator.get_paginated_response(FaqListItemSerializer(page, many=True).data)


class KbArticlePopularView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        articles = services.popular_articles()
        return Response(FaqListItemSerializer(articles, many=True).data)


class KbArticleDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, article_id):
        article = services.get_article(article_id)
        return Response(FaqDetailSerializer(article).data)


class CsatReviewView(APIView):
    """PRD §13.5 — public, unauthenticated by design: the review id itself
    is the entire access control (unguessable UUID PK), the same way a real
    emailed CSAT link works with no login."""

    permission_classes = [AllowAny]

    def get(self, request, review_id):
        review = services.get_review_or_404(review_id)
        return Response(CsatReviewSerializer(review).data)

    def post(self, request, review_id):
        payload = CsatSubmitSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        review = services.submit_review(review_id, payload.validated_data["score"], payload.validated_data["comment"])
        return Response(CsatReviewSerializer(review).data)
