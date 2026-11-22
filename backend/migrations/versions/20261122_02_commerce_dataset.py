"""Create the fixed M11A namespaced commerce schema.

This is intentionally explicit rather than importing application metadata:
Alembic history must not change when runtime SQLAlchemy tables are edited.
"""

from alembic import op
import sqlalchemy as sa


revision = "20261122_02"
down_revision = "20261122_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commerce_imports",
        sa.Column("import_key", sa.String(160), primary_key=True),
        sa.Column("source_name", sa.String(160), nullable=False),
        sa.Column("source_archive_sha256", sa.String(64), nullable=False),
        sa.Column("selection_max_order_id", sa.Integer(), nullable=False),
        sa.Column("scenario_clock", sa.DateTime(), nullable=False),
        sa.Column("row_counts_json", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "commerce_brands",
        sa.Column("source_brand_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
    )
    op.create_table(
        "commerce_categories",
        sa.Column("source_category_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
    )
    op.create_table(
        "commerce_order_statuses",
        sa.Column("source_order_status_id", sa.Integer(), primary_key=True),
        sa.Column("status_name", sa.String(32), nullable=False, unique=True),
        sa.Column("description", sa.String(160), nullable=False),
    )
    op.create_table(
        "commerce_payment_methods",
        sa.Column("source_payment_method_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
    )
    op.create_table(
        "commerce_shipping_methods",
        sa.Column("source_shipping_method_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("carrier", sa.String(64), nullable=False),
        sa.Column("base_cost", sa.Numeric(14, 2), nullable=False),
        sa.Column("estimated_days", sa.Integer(), nullable=False),
    )
    op.create_table(
        "commerce_return_reasons",
        sa.Column("source_return_reason_id", sa.Integer(), primary_key=True),
        sa.Column("reason_text", sa.String(255), nullable=False, unique=True),
    )
    op.create_table(
        "commerce_customers",
        sa.Column("source_user_id", sa.Integer(), primary_key=True),
        sa.Column("public_customer_id", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(160), nullable=False, unique=True),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "commerce_addresses",
        sa.Column("source_address_id", sa.Integer(), primary_key=True),
        sa.Column("source_user_id", sa.Integer(), nullable=False),
        sa.Column("street_address", sa.String(160), nullable=False),
        sa.Column("extended_address", sa.String(80)),
        sa.Column("city", sa.String(80), nullable=False),
        sa.Column("state_province", sa.String(32), nullable=False),
        sa.Column("postal_code", sa.String(32), nullable=False),
        sa.Column("country_code", sa.String(16), nullable=False),
        sa.Column("is_default_billing", sa.Boolean(), nullable=False),
        sa.Column("is_default_shipping", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "commerce_products",
        sa.Column("source_product_id", sa.Integer(), primary_key=True),
        sa.Column("source_brand_id", sa.Integer(), sa.ForeignKey("commerce_brands.source_brand_id"), nullable=False),
        sa.Column("source_category_id", sa.Integer(), sa.ForeignKey("commerce_categories.source_category_id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False, unique=True),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "commerce_orders",
        sa.Column("source_order_id", sa.Integer(), primary_key=True),
        sa.Column("public_order_id", sa.String(64), nullable=False, unique=True),
        sa.Column("source_user_id", sa.Integer(), sa.ForeignKey("commerce_customers.source_user_id"), nullable=False),
        sa.Column("source_billing_address_id", sa.Integer(), sa.ForeignKey("commerce_addresses.source_address_id"), nullable=False),
        sa.Column("source_shipping_address_id", sa.Integer(), sa.ForeignKey("commerce_addresses.source_address_id"), nullable=False),
        sa.Column("source_order_status_id", sa.Integer(), sa.ForeignKey("commerce_order_statuses.source_order_status_id"), nullable=False),
        sa.Column("source_shipping_method_id", sa.Integer(), sa.ForeignKey("commerce_shipping_methods.source_shipping_method_id"), nullable=False),
        sa.Column("source_coupon_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("shipping_cost", sa.Numeric(14, 2), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
    )
    op.create_table(
        "commerce_order_items",
        sa.Column("source_order_item_id", sa.Integer(), primary_key=True),
        sa.Column("source_order_id", sa.Integer(), sa.ForeignKey("commerce_orders.source_order_id"), nullable=False),
        sa.Column("source_product_id", sa.Integer(), sa.ForeignKey("commerce_products.source_product_id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False),
    )
    op.create_table(
        "commerce_payments",
        sa.Column("source_payment_id", sa.Integer(), primary_key=True),
        sa.Column("source_order_id", sa.Integer(), sa.ForeignKey("commerce_orders.source_order_id"), nullable=False, unique=True),
        sa.Column("source_payment_method_id", sa.Integer(), sa.ForeignKey("commerce_payment_methods.source_payment_method_id"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=False),
        sa.Column("transaction_reference", sa.String(80), nullable=False, unique=True),
    )
    op.create_table(
        "commerce_shipments",
        sa.Column("source_shipment_id", sa.Integer(), primary_key=True),
        sa.Column("source_order_id", sa.Integer(), sa.ForeignKey("commerce_orders.source_order_id"), nullable=False, unique=True),
        sa.Column("tracking_number", sa.String(80), nullable=False, unique=True),
        sa.Column("shipped_at", sa.DateTime(), nullable=False),
        sa.Column("promised_delivery_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "commerce_returns",
        sa.Column("source_return_id", sa.Integer(), primary_key=True),
        sa.Column("source_order_item_id", sa.Integer(), sa.ForeignKey("commerce_order_items.source_order_item_id"), nullable=False, unique=True),
        sa.Column("source_return_reason_id", sa.Integer(), sa.ForeignKey("commerce_return_reasons.source_return_reason_id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
    )
    op.create_table(
        "commerce_source_support_tickets",
        sa.Column("source_ticket_id", sa.Integer(), primary_key=True),
        sa.Column("source_user_id", sa.Integer(), sa.ForeignKey("commerce_customers.source_user_id"), nullable=False),
        sa.Column("subject", sa.String(160), nullable=False),
        sa.Column("priority", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("provenance", sa.String(64), nullable=False),
    )
    op.create_table(
        "commerce_source_support_messages",
        sa.Column("source_message_id", sa.Integer(), primary_key=True),
        sa.Column("source_ticket_id", sa.Integer(), sa.ForeignKey("commerce_source_support_tickets.source_ticket_id"), nullable=False),
        sa.Column("sender_type", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("provenance", sa.String(64), nullable=False),
    )
    op.create_table(
        "commerce_demo_identities",
        sa.Column("actor_id", sa.String(128), primary_key=True),
        sa.Column("source_user_id", sa.Integer(), sa.ForeignKey("commerce_customers.source_user_id"), nullable=False, unique=True),
    )
    op.create_table(
        "commerce_support_cases",
        sa.Column("case_id", sa.String(128), primary_key=True),
        sa.Column("source_user_id", sa.Integer(), sa.ForeignKey("commerce_customers.source_user_id"), nullable=False),
        sa.Column("source_order_id", sa.Integer(), sa.ForeignKey("commerce_orders.source_order_id")),
        sa.Column("scenario_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("permitted_outcome", sa.String(96), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime()),
        sa.Column("provenance", sa.String(64), nullable=False),
    )
    op.create_table(
        "commerce_support_case_messages",
        sa.Column("case_message_id", sa.String(128), primary_key=True),
        sa.Column("case_id", sa.String(128), sa.ForeignKey("commerce_support_cases.case_id"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("author_type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("provenance", sa.String(64), nullable=False),
        sa.UniqueConstraint("case_id", "sequence_number", name="uq_commerce_case_message_order"),
    )
    op.create_table(
        "commerce_shipment_events",
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("source_shipment_id", sa.Integer(), sa.ForeignKey("commerce_shipments.source_shipment_id"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("provenance", sa.String(64), nullable=False),
    )
    op.create_table(
        "commerce_refund_scenarios",
        sa.Column("refund_scenario_id", sa.String(128), primary_key=True),
        sa.Column("case_id", sa.String(128), sa.ForeignKey("commerce_support_cases.case_id"), nullable=False, unique=True),
        sa.Column("source_order_id", sa.Integer(), sa.ForeignKey("commerce_orders.source_order_id"), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.Column("provenance", sa.String(64), nullable=False),
    )
    op.create_index("ix_commerce_addresses_source_user_id", "commerce_addresses", ["source_user_id"])
    op.create_index("ix_commerce_orders_public_order_id", "commerce_orders", ["public_order_id"])
    op.create_index("ix_commerce_orders_source_user_id", "commerce_orders", ["source_user_id"])
    op.create_index("ix_commerce_order_items_source_order_id", "commerce_order_items", ["source_order_id"])
    op.create_index("ix_commerce_source_support_tickets_source_user_id", "commerce_source_support_tickets", ["source_user_id"])
    op.create_index("ix_commerce_source_support_messages_source_ticket_id", "commerce_source_support_messages", ["source_ticket_id"])
    op.create_index("ix_commerce_support_cases_source_user_id", "commerce_support_cases", ["source_user_id"])
    op.create_index("ix_commerce_support_cases_source_order_id", "commerce_support_cases", ["source_order_id"])
    op.create_index("ix_commerce_support_case_messages_case_id", "commerce_support_case_messages", ["case_id"])
    op.create_index("ix_commerce_shipment_events_source_shipment_id", "commerce_shipment_events", ["source_shipment_id"])
    op.create_index("ix_commerce_refund_scenarios_source_order_id", "commerce_refund_scenarios", ["source_order_id"])


def downgrade() -> None:
    for table_name in (
        "commerce_refund_scenarios",
        "commerce_shipment_events",
        "commerce_support_case_messages",
        "commerce_support_cases",
        "commerce_demo_identities",
        "commerce_source_support_messages",
        "commerce_source_support_tickets",
        "commerce_returns",
        "commerce_shipments",
        "commerce_payments",
        "commerce_order_items",
        "commerce_orders",
        "commerce_products",
        "commerce_addresses",
        "commerce_customers",
        "commerce_return_reasons",
        "commerce_shipping_methods",
        "commerce_payment_methods",
        "commerce_order_statuses",
        "commerce_categories",
        "commerce_brands",
        "commerce_imports",
    ):
        op.drop_table(table_name)
