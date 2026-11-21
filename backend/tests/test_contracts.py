from datetime import date, datetime, timezone
from unittest import TestCase

from pydantic import ValidationError

from backend.app.contracts import (
    ActorSummary,
    AppendMessageRequest,
    AppendMessageResponse,
    ConversationSummary,
    CreateConversationRequest,
    DemoLoginRequest,
    DemoLoginResponse,
    ErrorResponse,
    Message,
    OrderSummary,
)


class ContractModelTests(TestCase):
    def test_demo_login_response_matches_frozen_shape(self) -> None:
        response = DemoLoginResponse(
            session_id="demo-session-customer_001",
            actor=ActorSummary(
                actor_id="customer_001",
                display_name="Demo Customer",
                role="customer",
                customer_id="customer_001",
                permissions=["orders:read:self"],
            ),
        )

        self.assertEqual(
            response.model_dump(mode="json"),
            {
                "session_id": "demo-session-customer_001",
                "actor": {
                    "actor_id": "customer_001",
                    "display_name": "Demo Customer",
                    "role": "customer",
                    "customer_id": "customer_001",
                    "permissions": ["orders:read:self"],
                },
            },
        )

    def test_order_summary_serializes_iso_date(self) -> None:
        order = OrderSummary(
            order_id="order_1001",
            status="delayed",
            payment_status="paid",
            shipment_status="delayed",
            estimated_delivery_date=date(2026, 11, 8),
        )

        self.assertEqual(order.model_dump(mode="json")["estimated_delivery_date"], "2026-11-08")

    def test_invalid_demo_actor_request_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            DemoLoginRequest(demo_actor_id="")

    def test_order_status_cannot_expand_without_contract_change(self) -> None:
        with self.assertRaises(ValidationError):
            OrderSummary(
                order_id="order_1001",
                status="refunded",
                payment_status="paid",
                shipment_status="delivered",
                estimated_delivery_date=None,
            )

    def test_widget_conversation_contract_has_no_client_authorship(self) -> None:
        conversation = ConversationSummary(
            conversation_id="conv_1001",
            channel="widget",
            state="AI_ACTIVE",
            order_id="order_1001",
            messages=[],
        )
        message_request = AppendMessageRequest(content="Where is my order?")
        message = Message(
            message_id="msg_1001",
            author_type="customer",
            content=message_request.content,
            created_at=datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc),
        )
        response = AppendMessageResponse(
            conversation_id=conversation.conversation_id,
            state=conversation.state,
            message=message,
            assistant_reply=None,
            evidence=[],
            handoff_reason=None,
        )

        self.assertEqual(response.model_dump(mode="json")["message"]["author_type"], "customer")

    def test_widget_conversation_request_rejects_non_widget_channels(self) -> None:
        with self.assertRaises(ValidationError):
            CreateConversationRequest(channel="email", order_id=None)

    def test_error_envelope_is_explicit(self) -> None:
        error = ErrorResponse(
            error={
                "code": "unauthenticated",
                "message": "Authentication is required.",
                "details": {},
            }
        )

        self.assertEqual(error.model_dump(mode="json")["error"]["code"], "unauthenticated")
