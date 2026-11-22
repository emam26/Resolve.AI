"""Small deterministic synthetic policy corpus for offline retrieval checks."""

from typing import Tuple

from .models import PolicyRecord


POLICY_CORPUS: Tuple[PolicyRecord, ...] = (
    PolicyRecord(
        document_id="shipping-policy",
        document_version="v1",
        section="Shipping estimates",
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "Shipping estimates are shown at checkout and begin after carrier "
            "acceptance. Delivery dates are estimates, not guarantees."
        ),
        answer_text=(
            "Shipping estimates begin after carrier acceptance, and delivery "
            "dates are estimates rather than guarantees."
        ),
    ),
    PolicyRecord(
        document_id="delivery-policy",
        document_version="v2",
        section="Delayed shipments",
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "If a shipment is delayed, customers may contact support for an "
            "updated estimate."
        ),
        answer_text="If a shipment is delayed, contact support for an updated estimate.",
    ),
    PolicyRecord(
        document_id="delivery-policy",
        document_version="v1",
        section="Delayed shipments",
        release_id="release_2026_09_15",
        status="unpublished",
        visibility="public",
        text=(
            "If a shipment is delayed, customers should wait three business "
            "days before contacting support."
        ),
    ),
    PolicyRecord(
        document_id="missing-package-policy",
        document_version="v1",
        section="Missing packages",
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "If tracking shows delivered but a package is missing, contact "
            "support so a delivery investigation can be opened."
        ),
        answer_text=(
            "If tracking shows delivered but your package is missing, contact "
            "support so a delivery investigation can be opened."
        ),
    ),
    PolicyRecord(
        document_id="product-damage-policy",
        document_version="v1",
        section="Damaged items",
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "For a damaged item, keep the item and packaging and contact "
            "support with photos for review."
        ),
        answer_text=(
            "For a damaged item, keep the item and packaging and contact "
            "support with photos for review."
        ),
    ),
    PolicyRecord(
        document_id="fulfillment-policy",
        document_version="v1",
        section="Wrong items",
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "If the received item is wrong, keep it and contact support with "
            "the order details."
        ),
        answer_text=(
            "If you receive a wrong item, keep it and contact support with "
            "your order details."
        ),
    ),
    PolicyRecord(
        document_id="fulfillment-policy",
        document_version="v1",
        section="Partial order deliveries",
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "Orders may arrive in partial deliveries. Check each tracking "
            "entry and contact support if an expected item is missing."
        ),
        answer_text=(
            "Orders may arrive in partial deliveries. Check each tracking "
            "entry and contact support if an expected item is missing."
        ),
    ),
    PolicyRecord(
        document_id="order-cancellation-policy",
        document_version="v1",
        section="Order cancellations",
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "A cancellation request can be reviewed only before an order "
            "enters carrier fulfillment. Contact support promptly; "
            "cancellation is not guaranteed."
        ),
        answer_text=(
            "Cancellation requests can be reviewed only before carrier "
            "fulfillment, and cancellation is not guaranteed."
        ),
    ),
    PolicyRecord(
        document_id="refund-review-policy",
        document_version="v1",
        section="Refund review",
        release_id="release_2026_11_01",
        status="published",
        visibility="internal",
        text=(
            "Refund requests require support-agent review and refund-approver "
            "authorization before an external payment action."
        ),
        answer_text=(
            "Refund requests require support-agent review and refund-approver "
            "authorization before an external payment action."
        ),
    ),
    PolicyRecord(
        document_id="returns-policy",
        document_version="v1",
        section="Return window",
        release_id="release_2026_10_10",
        status="published",
        visibility="public",
        text="Unused items may be returned within 30 days of delivery.",
        answer_text="Unused items may be returned within 30 days of delivery.",
    ),
    PolicyRecord(
        document_id="refund-processing-policy",
        document_version="v1",
        section="Return credit processing",
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "After an eligible return is received and reviewed, return credit "
            "processing begins. Support can confirm the current processing "
            "status; bank posting times may vary."
        ),
        answer_text=(
            "After an eligible return is received and reviewed, return credit "
            "processing begins. Support can confirm its status; posting times "
            "may vary."
        ),
    ),
    PolicyRecord(
        document_id="human-support-policy",
        document_version="v1",
        section="Human support escalation",
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "Contact human support when order details, tracking, or policy "
            "evidence are insufficient to resolve a request safely."
        ),
        answer_text=(
            "Contact human support when the available order details, tracking, "
            "or policy evidence are insufficient to resolve a request safely."
        ),
    ),
)


def get_policy_corpus() -> Tuple[PolicyRecord, ...]:
    """Return the fixed corpus without exposing mutable global state."""

    return POLICY_CORPUS
