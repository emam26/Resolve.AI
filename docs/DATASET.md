# M11A synthetic commerce dataset

ResolveAI uses a reproducible subset of the publisher's synthetic E-commerce
Sample Database v2 as a local operational-data fixture. It is not a merchant
integration and it never contains production customer data.

## Source and fixed selection

- Official PostgreSQL 100K archive: <https://database-sample-website.s3.eu-north-1.amazonaws.com/datasets/ecommerce-sample-database/v2/flagship/100k/postgres.sql.gz>
- Required SHA-256: `8CE7F80D9A67C0664CCCB1A8211BB9CFA76E0192F636464E42542257B4BB408B`
- Deterministic cohort: `orders.id <= 3620`
- Expected selected order items: `10,000`
- The publisher identifies version 2 as **CC0 1.0 Public Domain**; see the
  [publisher dataset page](https://databasesample.com/datasets/ecommerce-sample-database)
  and [CC0 1.0 deed](https://creativecommons.org/publicdomain/zero/1.0/).

The archive, publisher schema, imported rows, generated operational records,
and database snapshots are staged outside this repository and are not
committed. The repository's `.gitignore` also excludes raw SQL/CSV/Parquet/
SQLite/database-dump formats, exports, snapshots, and private holdouts.
Import the archive into a disposable, read-only source database first; never
run the publisher's DDL against ResolveAI's application database.
The checksum verifies the archive presented to the operator; it cannot
cryptographically prove that an independently configured source database was
loaded from that archive. The source database is therefore a local staging
trust boundary. The importer additionally validates the selected counts,
financial relationships, chronology, and source references before writing the
application database.

## Imported application boundary

Alembic creates ResolveAI-owned, namespaced `commerce_*` tables in the existing
PostgreSQL database. The importer copies only the normalized domain records
needed by customer investigations:

| Domain | Imported records |
| --- | --- |
| Commerce | customers, addresses, brands, categories, products, orders, order items, order statuses, shipping methods |
| Transactions | payment methods, payments, returns, return reasons, shipments |
| Provenance | source support tickets and messages, preserved without invented order links |
| ResolveAI extensions | one explicit demo identity mapping, generated order-linked support cases/messages, shipment events, refund-review scenarios |

`commerce_order_<source-id>` is the public order namespace. It prevents a
collision with the pre-existing in-memory `order_1001` fixture. The importer
maps only `customer_001` to source user `3398`; importing a customer never
creates demo credentials. Imported commerce rows are read-only to application
operations. Conversations, human takeover, and refund review remain in their
existing persistence repositories.

For the verified selection, a completed import contains 3,620 orders, 10,000
order items, 2,512 customers, 400 products, 3,523 payments, 3,435 shipments,
212 returns, 4,402 addresses, 486 source tickets, and 1,630 source messages.

## Reproduce locally

Use an isolated PostgreSQL source database containing the verified publisher
archive and a separate ResolveAI PostgreSQL database with `pgvector`. The
following variables deliberately contain no credentials in this repository:

```powershell
$env:RESOLVEAI_DATASET_SOURCE_DATABASE_URL = "postgresql+psycopg://source_user:source_password@127.0.0.1:55435/ecommerce_source"
$env:RESOLVEAI_DATABASE_URL = "postgresql+psycopg://resolveai_user:resolveai_password@127.0.0.1:55436/resolveai"
$env:RESOLVEAI_COMMERCE_DATABASE_URL = $env:RESOLVEAI_DATABASE_URL
$env:RESOLVEAI_DATASET_SOURCE_ARCHIVE = "C:\path\to\postgres.sql.gz"

Push-Location backend
..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
Pop-Location
.\.venv\Scripts\python.exe -m backend.app.commerce.importer
```

The command verifies the archive checksum before reading the source database,
validates financial and relationship constraints, then replaces only
`commerce_*` data in one transaction. The import key contains the archive
checksum, fixed selection, and a stable hash of the canonical generated
cases/messages/events/refunds payload. A matching completed import key and row
counts cause a no-op; changing generated scenario output produces a new key
and replacement. If an insertion fails, the transaction rolls back.

Set `RESOLVEAI_COMMERCE_DATABASE_URL` when running the API to enable imported
orders. Without it, the existing in-memory development fixtures remain the
default.

## Company policy corpus

Customer policy answers use the separate fictional corpus in
`backend/app/rag/corpus.py`, not imported commerce records. It currently has
18 versioned sections across 12 policy documents, including published public
guidance, two unpublished superseded revisions, and two published staff-only
sections. The local MiniLM/pgvector seed is repeatable and stores policy text,
release, version, publication status, visibility, and embeddings together so
retrieval can enforce access controls before evidence reaches an answer.
The deterministic lexical retriever remains the offline baseline and the
customer workflow retains its safe handoff when evidence is insufficient.

## Generated investigation scenarios

The source tickets remain historical source data. ResolveAI adds ten clearly
provenanced scenarios, each bound to an actual imported customer and order,
covering delayed delivery, missing or delivered-not-received packages, wrong
or damaged products, partial delivery, cancellation, return, refund status,
and duplicate refund requests. Generated timestamps use the fixed scenario
clock `2026-01-03T12:00:00`; active events do not contradict the shipment state
at that clock.

Three generated refund scenarios retain the existing human-controlled states:
`PENDING_REVIEW`, `APPROVED_EXTERNAL_ACTION_REQUIRED`, or `REJECTED`. They do
not create refund transactions or call a payment provider.

## Grounded evaluation labels

`backend/app/commerce/evaluation.py` contains 80 predeclared public development
cases. Related order/customer groups remain in one split. Labels identify
authorization context, expected published policy (or required abstention),
supported facts, handoff, workflow outcome, and security constraint. The
database integration check validates referenced order ownership and that any
expected customer policy is published and public; labels are not inferred from
model output. Private holdout labels and answer keys are retained only in the
local staging workspace and are not distributed through GitHub. The public
labels are executed through the deterministic lexical answer contract to catch
drift in published evidence, version, visibility, or safe-abstention behavior.
