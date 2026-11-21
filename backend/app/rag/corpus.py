"""Small deterministic synthetic policy corpus for offline M2 checks."""

from typing import Tuple

from .models import PolicyRecord


POLICY_CORPUS: Tuple[PolicyRecord, ...] = (
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
)


def get_policy_corpus() -> Tuple[PolicyRecord, ...]:
    """Return the fixed corpus without exposing mutable global state."""

    return POLICY_CORPUS
