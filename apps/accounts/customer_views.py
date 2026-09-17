from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services
from apps.accounts.serializers import (
    CustomerOtpRequestResponseSerializer,
    CustomerOtpRequestSerializer,
    CustomerOtpVerifyRequestSerializer,
    TokenResponseSerializer,
)
from apps.accounts.throttles import AuthRateThrottle


class CustomerRequestOtpView(APIView):
    permission_classes = [AllowAny]
    # Unthrottled, this both spams a customer's inbox and lets an attacker mint
    # unlimited fresh OTPs to sidestep the per-record OTP_MAX_ATTEMPTS cap.
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        payload = CustomerOtpRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        customer, code = services.customer_request_otp(**payload.validated_data)
        out = CustomerOtpRequestResponseSerializer({"customer_id": customer.id, "dev_otp": code})
        return Response(out.data)


class CustomerVerifyOtpView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        payload = CustomerOtpVerifyRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        token = services.customer_verify_otp(**payload.validated_data)
        out = TokenResponseSerializer({"access_token": token, "token_type": "bearer", "role": "customer"})
        return Response(out.data)


# Phase 2: customer-facing ticket views (My Tickets, submit ticket, ticket
# thread) will live here too, using apps.tickets.services + IsCustomer.
