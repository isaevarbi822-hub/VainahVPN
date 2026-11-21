"""Disposable PostgreSQL schemas shared by integration tests."""
import os
from urllib.parse import parse_qsl, quote, urlencode, urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql


@pytest.fixture
def postgres_url():
    base = os.environ.get("VAINAH_TEST_DATABASE_URL")
    if not base:
        pytest.skip("VAINAH_TEST_DATABASE_URL is required for real PostgreSQL checks")
    schema = "test_sandbox_" + uuid4().hex
    with psycopg.connect(base, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {} ").format(sql.Identifier(schema)))
    parts = urlsplit(base)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("options", "-c search_path=" + schema))
    url = base.split("?", 1)[0] + "?" + urlencode(query, quote_via=quote)
    try:
        yield url
    finally:
        with psycopg.connect(base, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

