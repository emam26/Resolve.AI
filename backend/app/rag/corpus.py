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
        document_version="v2",
        section="Late delivery follow-up",
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "A delivery investigation may be opened when carrier movement stops "
            "for three business days or the estimated date passes. Compensation "
            "is not guaranteed."
        ),
        answer_text=(
            "Support may open a delivery investigation after three business days "
            "without carrier movement or after the estimated date passes; "
            "compensation is not guaranteed."
        ),
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
            "support within seven calendar days of the delivery scan so a "
            "delivery investigation can be opened. Check secure locations and "
            "household members first; a missing package does not create an "
            "automatic compensation decision."
        ),
        answer_text=(
            "If tracking shows delivered but your package is missing, contact "
            "support within seven days for a delivery investigation after checking "
            "secure locations and household members; a missing delivery does not "
            "guarantee compensation."
        ),
    ),
    PolicyRecord(
        document_id="missing-package-policy",
        document_version="v1",
        section="Delivered but not received",
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "When tracking says delivered but the customer cannot locate the "
            "package, support records the report and coordinates a carrier "
            "trace. The customer should report the problem within seven days "
            "and should not discard packaging or delivery evidence."
        ),
        answer_text=(
            "If tracking says delivered but you cannot locate the package, "
            "contact support within seven days for a carrier trace and retain "
            "packaging and delivery evidence."
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
            "support within 14 calendar days with photos for review. Do not "
            "discard the item or packaging before support gives instructions."
        ),
        answer_text=(
            "For a damaged item, keep the item and packaging and contact "
            "support within 14 days with photos for review; do not discard the "
            "item or packaging before support gives instructions."
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
            "the order details within 14 calendar days. Support may offer a "
            "replacement or an authorized return; do not ship it back without "
            "instructions."
        ),
        answer_text=(
            "If you receive a wrong item, keep it and contact support with "
            "your order details within 14 days. Support may offer a replacement "
            "or authorized return; do not ship it back without instructions."
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
            "Orders may arrive in separate deliveries. Check each tracking "
            "entry and contact support if an expected item is missing. Each "
            "delivery is assessed against the original order lines; a partial "
            "delivery is not by itself a credit approval."
        ),
        answer_text=(
            "Orders may arrive in separate deliveries. Check each tracking entry "
            "and contact support if an expected item is missing; each delivery "
            "is assessed against the order lines, and partial delivery alone is "
            "not credit approval."
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
            "cancellation is not guaranteed and cannot be promised after the "
            "carrier has accepted the order."
        ),
        answer_text=(
            "Cancellation requests can be reviewed only before carrier "
            "fulfillment; contact support promptly, but cancellation is not "
            "guaranteed and cannot be promised after carrier acceptance."
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
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "A return request must be submitted within 30 calendar days after "
            "delivery. Items must be unused, with tags and original packaging "
            "when applicable. Personalized, perishable, or visibly used items "
            "may be excluded; support must confirm eligibility before the item "
            "is sent."
        ),
        answer_text=(
            "Submit a return request within 30 days of delivery. The item must "
            "be unused and meet the applicable packaging and exception rules; "
            "support must confirm eligibility before it is sent back."
        ),
    ),
    PolicyRecord(
        document_id="returns-policy",
        document_version="v0",
        section="Legacy return window",
        release_id="release_2026_08_01",
        status="unpublished",
        visibility="public",
        text="The legacy return window was 14 days and is no longer applicable.",
    ),
    PolicyRecord(
        document_id="refund-eligibility-policy",
        document_version="v1",
        section="Refund eligibility",
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "A refund or credit request may be considered for an eligible return, a "
            "verified damaged item, or a confirmed fulfillment error. Support "
            "must verify the order and evidence first; eligibility is not a "
            "guarantee of payment and the request may be declined."
        ),
        answer_text=(
            "A refund or credit may be considered for an eligible return, verified damage, "
            "or a confirmed fulfillment error after support verifies the order "
            "and evidence; eligibility is not guaranteed."
        ),
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
            "status; bank posting times may vary. A processing update is not a "
            "promise that an ineligible request will be paid."
        ),
        answer_text=(
            "After an eligible return is received and reviewed, return credit "
            "processing begins. Support can confirm its status; posting times "
            "may vary, and a processing update is not a promise that an "
            "ineligible request will be paid."
        ),
    ),
    PolicyRecord(
        document_id="warranty-policy",
        document_version="v1",
        section="Product warranty coverage",
        release_id="release_2026_11_01",
        status="published",
        visibility="public",
        text=(
            "Eligible products include a 12-month limited warranty for defects "
            "that appear during normal intended use. Accidental damage, normal "
            "wear, misuse, and unauthorized modification are excluded. Contact "
            "support with the order and product details for a warranty review; "
            "warranty claims for accidental damage are excluded; the remedy may "
            "be repair, replacement, or another approved option."
        ),
        answer_text=(
            "Eligible products have a 12-month limited warranty for defects in "
            "normal use. Accidental damage, normal wear, misuse, and unauthorized "
            "modification are excluded; contact support for a warranty review, "
            "which may result in repair, replacement, or another approved remedy."
        ),
    ),
    PolicyRecord(
        document_id="warranty-policy",
        document_version="v1",
        section="Warranty exception matrix",
        release_id="release_2026_11_01",
        status="published",
        visibility="internal",
        text=(
            "Staff must verify product coverage, order ownership, and the "
            "exclusion matrix before approving a warranty remedy. This internal "
            "decision aid is not customer evidence."
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
