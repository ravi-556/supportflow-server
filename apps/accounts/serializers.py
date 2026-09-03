from rest_framework import serializers

from apps.accounts.models import Agent, Customer, Group

# --- Auth request/response shapes (not direct model reflections) ---


class AgentLoginRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()


class AgentLoginResponseSerializer(serializers.Serializer):
    agent_id = serializers.UUIDField()
    otp_required = serializers.BooleanField(default=True)
    dev_otp = serializers.CharField(allow_null=True)


class AgentOtpVerifyRequestSerializer(serializers.Serializer):
    agent_id = serializers.UUIDField()
    code = serializers.CharField()


class CustomerOtpRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class CustomerOtpRequestResponseSerializer(serializers.Serializer):
    customer_id = serializers.UUIDField()
    dev_otp = serializers.CharField(allow_null=True)


class CustomerOtpVerifyRequestSerializer(serializers.Serializer):
    customer_id = serializers.UUIDField()
    code = serializers.CharField()


class TokenResponseSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    token_type = serializers.CharField(default="bearer")
    role = serializers.CharField()


class GuestTicketOtpRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class GuestTicketOtpRequestResponseSerializer(serializers.Serializer):
    dev_otp = serializers.CharField(allow_null=True)


# --- Lookup / read serializers ---


class AgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agent
        fields = ["id", "email", "first_name", "last_name", "role"]


class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ["id", "name", "category"]


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "email", "first_name", "last_name", "company", "segment"]
