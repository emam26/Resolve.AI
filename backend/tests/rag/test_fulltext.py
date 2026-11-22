from sqlalchemy.dialects import postgresql

from backend.app.rag.fulltext import (
    FULL_TEXT_INDEX_NAME,
    build_full_text_policy_query,
)


def test_full_text_query_uses_native_search_and_access_filters() -> None:
    statement = build_full_text_policy_query("shipment delayed")
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled).lower()

    assert "to_tsvector" in sql
    assert "websearch_to_tsquery" in sql
    assert "ts_rank_cd" in sql
    assert "@@" in sql
    assert "policy_embeddings.status =" in sql
    assert "policy_embeddings.visibility =" in sql
    assert "order by" in sql
    assert "limit" in sql
    assert FULL_TEXT_INDEX_NAME == "ix_policy_embeddings_policy_text_fts"
