"""Adversarial tests for the run_sql guard.

The read-only role is the real guarantee -- these tests do not assume otherwise.
The guard exists so the model gets a correctable explanation instead of an
opaque permission error, and as a second layer if the role is ever misconfigured
(which the Neon console did once already: see the README).
"""

from __future__ import annotations

import pytest

from backend.app.sql_guard import enforce_limit, sanitise, validate

WRITES = [
    "INSERT INTO bdsa_sales (state) VALUES ('x')",
    "UPDATE bdsa_sales SET state = 'x'",
    "DELETE FROM bdsa_sales",
    "TRUNCATE bdsa_sales",
    "DROP TABLE bdsa_sales",
    "CREATE TABLE evil (i int)",
    "ALTER TABLE bdsa_sales ADD COLUMN x int",
    "GRANT ALL ON bdsa_sales TO PUBLIC",
    "REFRESH MATERIALIZED VIEW mv_brand_monthly",
]


@pytest.mark.parametrize("q", WRITES)
def test_writes_and_ddl_are_rejected(q):
    assert validate(q).ok is False


def test_a_plain_select_is_accepted():
    assert validate("SELECT count(*) FROM bdsa_sales").ok is True


def test_a_cte_is_accepted():
    q = "WITH x AS (SELECT 1 AS a) SELECT a FROM x"
    assert validate(q).ok is True


def test_a_trailing_semicolon_is_fine():
    assert validate("SELECT 1;").ok is True


# ---------------------------------------------------------------------------
# Statement stacking
# ---------------------------------------------------------------------------

def test_stacked_statements_are_rejected():
    r = validate("SELECT 1; DROP TABLE bdsa_sales")
    assert r.ok is False
    assert "Multiple statements" in r.reason


def test_stacking_hidden_behind_a_line_comment_is_rejected():
    """`--` hides the rest of ITS line, not the next line."""
    r = validate("SELECT 1 -- harmless\n; DROP TABLE bdsa_sales")
    assert r.ok is False


def test_stacking_hidden_in_a_block_comment_does_not_smuggle_a_keyword():
    """A keyword genuinely inside a comment is inert and must not false-positive."""
    assert validate("SELECT 1 /* DROP TABLE bdsa_sales */").ok is True


def test_nested_block_comments_are_handled():
    """Postgres nests block comments; a naive scanner ends the comment early
    and then sees the trailing DELETE as live SQL."""
    assert validate("SELECT 1 /* outer /* inner */ still comment */").ok is True
    assert validate("SELECT 1 /* a /* b */ c */ ; DELETE FROM bdsa_sales").ok is False


# ---------------------------------------------------------------------------
# Literals must not trigger false positives
# ---------------------------------------------------------------------------

def test_a_keyword_inside_a_string_literal_is_allowed():
    """A brand really could be called 'Update' -- rejecting that would be a bug."""
    q = "SELECT * FROM mv_brand_monthly WHERE brand = 'Delete Me' AND state = 'Ohio'"
    assert validate(q).ok is True


def test_an_escaped_quote_does_not_end_the_string_early():
    q = "SELECT * FROM mv_brand_monthly WHERE brand = 'O''Briens Drop Shop'"
    assert validate(q).ok is True


def test_dollar_quoted_strings_are_handled():
    assert validate("SELECT $$ DROP TABLE bdsa_sales $$ AS t").ok is True


def test_a_quoted_identifier_named_like_a_keyword_is_allowed():
    assert validate('SELECT "drop" FROM mv_brand_monthly').ok is True


def test_sanitise_blanks_literals_and_comments():
    out = sanitise("SELECT 'abc' /* note */ -- tail\nFROM t")
    assert "abc" not in out
    assert "note" not in out
    assert "tail" not in out
    assert "SELECT" in out and "FROM t" in out


# ---------------------------------------------------------------------------
# Things that look like reads but are not
# ---------------------------------------------------------------------------

def test_select_into_is_rejected_because_it_creates_a_table():
    r = validate("SELECT * INTO evil FROM bdsa_sales")
    assert r.ok is False
    assert "INTO" in r.reason


def test_explain_analyze_is_rejected_because_it_executes():
    assert validate("EXPLAIN ANALYZE SELECT 1").ok is False
    assert validate("EXPLAIN SELECT 1").ok is False


def test_set_is_rejected_so_the_timeout_cannot_be_raised():
    r = validate("SET statement_timeout = 0")
    assert r.ok is False


def test_a_cte_that_writes_is_rejected():
    """Postgres allows data-modifying CTEs -- WITH x AS (DELETE ...) is a write
    that begins with the word WITH."""
    q = "WITH gone AS (DELETE FROM bdsa_sales RETURNING *) SELECT count(*) FROM gone"
    assert validate(q).ok is False


def test_filesystem_and_sleep_functions_are_rejected():
    assert validate("SELECT pg_read_file('/etc/passwd')").ok is False
    assert validate("SELECT pg_sleep(60)").ok is False


def test_empty_and_oversized_queries_are_rejected():
    assert validate("").ok is False
    assert validate("   ").ok is False
    assert validate("SELECT " + "1," * 20000 + "1").ok is False


# ---------------------------------------------------------------------------
# Row limit
# ---------------------------------------------------------------------------

def test_limit_is_wrapped_not_appended():
    out = enforce_limit("SELECT * FROM t", 5000)
    assert out.startswith("SELECT * FROM (")
    assert out.rstrip().endswith("LIMIT 5000")


def test_wrapping_overrides_a_larger_limit_the_query_already_has():
    """Appending could not do this -- the inner LIMIT would win."""
    out = enforce_limit("SELECT * FROM t LIMIT 999999", 5000)
    assert out.rstrip().endswith("LIMIT 5000")
    assert "999999" in out  # inner limit preserved, outer one binds


def test_wrapping_handles_order_by_and_union():
    for q in [
        "SELECT a FROM t ORDER BY a DESC",
        "SELECT a FROM t UNION SELECT b FROM u",
        "WITH x AS (SELECT 1 a) SELECT a FROM x",
    ]:
        out = enforce_limit(q, 10)
        assert out.rstrip().endswith("LIMIT 10")
        assert q.strip() in out
