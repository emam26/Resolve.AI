"""Namespaced, read-only commerce domain tables for the M11A dataset.

The application deliberately imports only the ecommerce records that its
customer-investigation workflows need.  These tables retain stable publisher
source IDs while exposing ResolveAI-specific public identifiers, so they never
collide with the hand-written ``order_1001`` development fixture.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.engine import Connection, Engine


commerce_metadata = MetaData()

commerce_imports = Table(
    "commerce_imports",
    commerce_metadata,
    Column("import_key", String(160), primary_key=True),
    Column("source_name", String(160), nullable=False),
    Column("source_archive_sha256", String(64), nullable=False),
    Column("transformation_manifest_sha256", String(64), nullable=False),
    Column("selection_max_order_id", Integer, nullable=False),
    Column("scenario_clock", DateTime, nullable=False),
    Column("row_counts_json", Text, nullable=False),
    Column("completed_at", DateTime, nullable=False),
)

commerce_brands = Table(
    "commerce_brands",
    commerce_metadata,
    Column("source_brand_id", Integer, primary_key=True),
    Column("name", String(160), nullable=False),
)

commerce_categories = Table(
    "commerce_categories",
    commerce_metadata,
    Column("source_category_id", Integer, primary_key=True),
    Column("name", String(120), nullable=False),
)

commerce_order_statuses = Table(
    "commerce_order_statuses",
    commerce_metadata,
    Column("source_order_status_id", Integer, primary_key=True),
    Column("status_name", String(32), nullable=False, unique=True),
    Column("description", String(160), nullable=False),
)

commerce_payment_methods = Table(
    "commerce_payment_methods",
    commerce_metadata,
    Column("source_payment_method_id", Integer, primary_key=True),
    Column("name", String(64), nullable=False, unique=True),
)

commerce_shipping_methods = Table(
    "commerce_shipping_methods",
    commerce_metadata,
    Column("source_shipping_method_id", Integer, primary_key=True),
    Column("name", String(64), nullable=False, unique=True),
    Column("carrier", String(64), nullable=False),
    Column("base_cost", Numeric(14, 2), nullable=False),
    Column("estimated_days", Integer, nullable=False),
)

commerce_return_reasons = Table(
    "commerce_return_reasons",
    commerce_metadata,
    Column("source_return_reason_id", Integer, primary_key=True),
    Column("reason_text", String(255), nullable=False, unique=True),
)

commerce_customers = Table(
    "commerce_customers",
    commerce_metadata,
    Column("source_user_id", Integer, primary_key=True),
    Column("public_customer_id", String(64), nullable=False, unique=True),
    Column("email", String(160), nullable=False, unique=True),
    Column("display_name", String(160), nullable=False),
    Column("created_at", DateTime, nullable=False),
)

commerce_addresses = Table(
    "commerce_addresses",
    commerce_metadata,
    Column("source_address_id", Integer, primary_key=True),
    # The publisher permits a selected order to reference an address owned by
    # a user outside the selected order cohort.  Retain that immutable source
    # owner ID as provenance, without widening ResolveAI's customer dataset or
    # treating it as a login-enabled domain relationship.
    Column("source_user_id", Integer, nullable=False, index=True),
    Column("street_address", String(160), nullable=False),
    Column("extended_address", String(80), nullable=True),
    Column("city", String(80), nullable=False),
    Column("state_province", String(32), nullable=False),
    Column("postal_code", String(32), nullable=False),
    Column("country_code", String(16), nullable=False),
    Column("is_default_billing", Boolean, nullable=False),
    Column("is_default_shipping", Boolean, nullable=False),
)

commerce_products = Table(
    "commerce_products",
    commerce_metadata,
    Column("source_product_id", Integer, primary_key=True),
    Column(
        "source_brand_id",
        Integer,
        ForeignKey("commerce_brands.source_brand_id"),
        nullable=False,
    ),
    Column(
        "source_category_id",
        Integer,
        ForeignKey("commerce_categories.source_category_id"),
        nullable=False,
    ),
    Column("name", String(160), nullable=False),
    Column("sku", String(64), nullable=False, unique=True),
    Column("price", Numeric(14, 2), nullable=False),
    Column("is_active", Boolean, nullable=False),
)

commerce_orders = Table(
    "commerce_orders",
    commerce_metadata,
    Column("source_order_id", Integer, primary_key=True),
    Column("public_order_id", String(64), nullable=False, unique=True, index=True),
    Column(
        "source_user_id",
        Integer,
        ForeignKey("commerce_customers.source_user_id"),
        nullable=False,
        index=True,
    ),
    Column(
        "source_billing_address_id",
        Integer,
        ForeignKey("commerce_addresses.source_address_id"),
        nullable=False,
    ),
    Column(
        "source_shipping_address_id",
        Integer,
        ForeignKey("commerce_addresses.source_address_id"),
        nullable=False,
    ),
    Column(
        "source_order_status_id",
        Integer,
        ForeignKey("commerce_order_statuses.source_order_status_id"),
        nullable=False,
    ),
    Column(
        "source_shipping_method_id",
        Integer,
        ForeignKey("commerce_shipping_methods.source_shipping_method_id"),
        nullable=False,
    ),
    Column("source_coupon_id", Integer, nullable=True),
    Column("created_at", DateTime, nullable=False),
    Column("subtotal", Numeric(14, 2), nullable=False),
    Column("discount_amount", Numeric(14, 2), nullable=False),
    Column("tax_amount", Numeric(14, 2), nullable=False),
    Column("shipping_cost", Numeric(14, 2), nullable=False),
    Column("total", Numeric(14, 2), nullable=False),
)

commerce_order_items = Table(
    "commerce_order_items",
    commerce_metadata,
    Column("source_order_item_id", Integer, primary_key=True),
    Column(
        "source_order_id",
        Integer,
        ForeignKey("commerce_orders.source_order_id"),
        nullable=False,
        index=True,
    ),
    Column(
        "source_product_id",
        Integer,
        ForeignKey("commerce_products.source_product_id"),
        nullable=False,
    ),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Numeric(14, 2), nullable=False),
    Column("discount_amount", Numeric(14, 2), nullable=False),
    Column("tax_amount", Numeric(14, 2), nullable=False),
)

commerce_payments = Table(
    "commerce_payments",
    commerce_metadata,
    Column("source_payment_id", Integer, primary_key=True),
    Column(
        "source_order_id",
        Integer,
        ForeignKey("commerce_orders.source_order_id"),
        nullable=False,
        unique=True,
    ),
    Column(
        "source_payment_method_id",
        Integer,
        ForeignKey("commerce_payment_methods.source_payment_method_id"),
        nullable=False,
    ),
    Column("amount", Numeric(14, 2), nullable=False),
    Column("status", String(32), nullable=False),
    Column("processed_at", DateTime, nullable=False),
    Column("transaction_reference", String(80), nullable=False, unique=True),
)

commerce_shipments = Table(
    "commerce_shipments",
    commerce_metadata,
    Column("source_shipment_id", Integer, primary_key=True),
    Column(
        "source_order_id",
        Integer,
        ForeignKey("commerce_orders.source_order_id"),
        nullable=False,
        unique=True,
    ),
    Column("tracking_number", String(80), nullable=False, unique=True),
    Column("shipped_at", DateTime, nullable=False),
    Column("promised_delivery_at", DateTime, nullable=False),
    Column("delivered_at", DateTime, nullable=False),
)

commerce_returns = Table(
    "commerce_returns",
    commerce_metadata,
    Column("source_return_id", Integer, primary_key=True),
    Column(
        "source_order_item_id",
        Integer,
        ForeignKey("commerce_order_items.source_order_item_id"),
        nullable=False,
        unique=True,
    ),
    Column(
        "source_return_reason_id",
        Integer,
        ForeignKey("commerce_return_reasons.source_return_reason_id"),
        nullable=False,
    ),
    Column("status", String(32), nullable=False),
    Column("requested_at", DateTime, nullable=False),
    Column("processed_at", DateTime, nullable=False),
    Column("quantity", Integer, nullable=False),
)

commerce_source_support_tickets = Table(
    "commerce_source_support_tickets",
    commerce_metadata,
    Column("source_ticket_id", Integer, primary_key=True),
    Column(
        "source_user_id",
        Integer,
        ForeignKey("commerce_customers.source_user_id"),
        nullable=False,
        index=True,
    ),
    Column("subject", String(160), nullable=False),
    Column("priority", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("provenance", String(64), nullable=False),
)

commerce_source_support_messages = Table(
    "commerce_source_support_messages",
    commerce_metadata,
    Column("source_message_id", Integer, primary_key=True),
    Column(
        "source_ticket_id",
        Integer,
        ForeignKey("commerce_source_support_tickets.source_ticket_id"),
        nullable=False,
        index=True,
    ),
    Column("sender_type", String(32), nullable=False),
    Column("message", Text, nullable=False),
    Column("sent_at", DateTime, nullable=False),
    Column("provenance", String(64), nullable=False),
)

commerce_demo_identities = Table(
    "commerce_demo_identities",
    commerce_metadata,
    Column("actor_id", String(128), primary_key=True),
    Column(
        "source_user_id",
        Integer,
        ForeignKey("commerce_customers.source_user_id"),
        nullable=False,
        unique=True,
    ),
)

commerce_support_cases = Table(
    "commerce_support_cases",
    commerce_metadata,
    Column("case_id", String(128), primary_key=True),
    Column(
        "source_user_id",
        Integer,
        ForeignKey("commerce_customers.source_user_id"),
        nullable=False,
        index=True,
    ),
    Column(
        "source_order_id",
        Integer,
        ForeignKey("commerce_orders.source_order_id"),
        nullable=True,
        index=True,
    ),
    Column("scenario_type", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("permitted_outcome", String(96), nullable=False),
    Column("opened_at", DateTime, nullable=False),
    Column("closed_at", DateTime, nullable=True),
    Column("provenance", String(64), nullable=False),
)

commerce_support_case_messages = Table(
    "commerce_support_case_messages",
    commerce_metadata,
    Column("case_message_id", String(128), primary_key=True),
    Column(
        "case_id",
        String(128),
        ForeignKey("commerce_support_cases.case_id"),
        nullable=False,
        index=True,
    ),
    Column("sequence_number", Integer, nullable=False),
    Column("author_type", String(32), nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("provenance", String(64), nullable=False),
    UniqueConstraint("case_id", "sequence_number", name="uq_commerce_case_message_order"),
)

commerce_shipment_events = Table(
    "commerce_shipment_events",
    commerce_metadata,
    Column("event_id", String(128), primary_key=True),
    Column(
        "source_shipment_id",
        Integer,
        ForeignKey("commerce_shipments.source_shipment_id"),
        nullable=False,
        index=True,
    ),
    Column("event_type", String(64), nullable=False),
    Column("detail", Text, nullable=False),
    Column("occurred_at", DateTime, nullable=False),
    Column("provenance", String(64), nullable=False),
)

commerce_refund_scenarios = Table(
    "commerce_refund_scenarios",
    commerce_metadata,
    Column("refund_scenario_id", String(128), primary_key=True),
    Column(
        "case_id",
        String(128),
        ForeignKey("commerce_support_cases.case_id"),
        nullable=False,
        unique=True,
    ),
    Column(
        "source_order_id",
        Integer,
        ForeignKey("commerce_orders.source_order_id"),
        nullable=False,
        index=True,
    ),
    Column("amount_cents", Integer, nullable=False),
    Column("state", String(64), nullable=False),
    Column("idempotency_key", String(160), nullable=False, unique=True),
    Column("provenance", String(64), nullable=False),
)


def create_commerce_schema(bind: Engine | Connection) -> None:
    """Create the owned commerce tables for focused local/integration checks."""

    commerce_metadata.create_all(bind)


def drop_commerce_schema(bind: Engine | Connection) -> None:
    """Drop only the named M11A tables in dependency-safe reverse order."""

    commerce_metadata.drop_all(bind)


__all__ = [
    "commerce_addresses",
    "commerce_brands",
    "commerce_categories",
    "commerce_customers",
    "commerce_demo_identities",
    "commerce_imports",
    "commerce_metadata",
    "commerce_order_items",
    "commerce_order_statuses",
    "commerce_orders",
    "commerce_payment_methods",
    "commerce_payments",
    "commerce_products",
    "commerce_refund_scenarios",
    "commerce_return_reasons",
    "commerce_returns",
    "commerce_shipment_events",
    "commerce_shipments",
    "commerce_shipping_methods",
    "commerce_source_support_messages",
    "commerce_source_support_tickets",
    "commerce_support_case_messages",
    "commerce_support_cases",
    "create_commerce_schema",
    "drop_commerce_schema",
]
