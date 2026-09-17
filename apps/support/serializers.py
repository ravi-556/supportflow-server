from rest_framework import serializers

from apps.support.models import Faq, Review


class FaqListItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Faq
        fields = ["id", "question", "category", "view_count"]


class FaqDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Faq
        fields = ["id", "question", "description", "category", "view_count", "published_at"]


class CsatReviewSerializer(serializers.ModelSerializer):
    ticket_no = serializers.SerializerMethodField()
    ticket_subject = serializers.SerializerMethodField()
    submitted = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ["id", "ticket_no", "ticket_subject", "score", "comment", "submitted"]

    def get_ticket_no(self, obj) -> int:
        return obj.ticket.ticket_no

    def get_ticket_subject(self, obj) -> str:
        return obj.ticket.subject

    def get_submitted(self, obj) -> bool:
        return obj.submitted_at is not None


class CsatSubmitSerializer(serializers.Serializer):
    # No ticket_id/customer_id — already fixed by which review row the URL
    # names.
    score = serializers.FloatField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True, default="")
