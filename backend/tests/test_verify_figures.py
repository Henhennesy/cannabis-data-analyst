"""The figure verifier, tested against answers the agent really produced.

The two regression cases are copied verbatim from live runs. If the verifier
cannot catch those, it is not worth having.
"""

from __future__ import annotations

import pytest

from backend.app.envelope import Coverage, ToolEnvelope
from backend.app.verify_figures import verify


def env(rows, *, row_count=None, states=("Ohio",), years=(2025, 2025)):
    return ToolEnvelope(
        rows=rows,
        row_count=row_count if row_count is not None else len(rows),
        coverage=Coverage(
            period_start=years[0], period_end=years[1], states=list(states)
        ),
    )


# ---------------------------------------------------------------------------
# The regressions
# ---------------------------------------------------------------------------

def test_catches_the_combined_year_total_the_tool_refused_to_return():
    """Live failure: the agent received Inhaleables split by year and added the
    two rows in prose -- 24,131,892,085.87 + 11,442,961,478.23 = $35.57B."""
    envelopes = [env([
        {"period_year": 2025, "dollar_sales": 24_131_892_085.87},
        {"period_year": 2026, "dollar_sales": 11_442_961_478.23},
    ], years=(2025, 2026))]

    answer = (
        "Inhaleables 2025 was $24.13B and 2026 was $11.44B. "
        "For context, the combined total is $35.57B."
    )
    result = verify(answer, envelopes)

    assert not result.ok
    flagged = [c.text for c in result.unverified]
    assert "$35.57B" in flagged
    # The two real figures must NOT be flagged, or the signal is worthless.
    assert "$24.13B" not in flagged
    assert "$11.44B" not in flagged


def test_catches_a_row_cap_reported_as_a_cardinality():
    """Live failure: 5,000 was the LIMIT, not the number of flavors."""
    envelopes = [env([{"flavor": f"f{i}", "dollar_sales": 1000.0} for i in range(5000)],
                     row_count=5000)]
    # 5,000 IS in the pool as row_count, so a bare "5,000 rows" is fine...
    assert verify("5,000 rows came back.", envelopes).ok
    # ...but a number that appears nowhere is caught.
    assert not verify("There are 8,412 distinct flavors.", envelopes).ok


# ---------------------------------------------------------------------------
# Real figures must pass
# ---------------------------------------------------------------------------

def test_a_correct_answer_passes_cleanly():
    """Verbatim from a live run: the fast-acting answer."""
    envelopes = [env([{
        "numerator": 266_382_172.26,
        "denominator": 3_867_307_583.83,
        "ratio": 0.0688812,
        "percent": 6.88812,
        "state_count": 37,
    }], states=[f"S{i}" for i in range(37)])]

    answer = (
        "**6.89% of edible dollars were fast-acting in 2025, across all 37 "
        "BDSA-covered states.**\n\n- Fast Acting edibles: $266.4M\n"
        "- Total edibles: $3.87B"
    )
    result = verify(answer, envelopes)
    assert result.ok, f"false positives: {[c.text for c in result.unverified]}"
    assert result.checked_count >= 3


def test_rounding_and_magnitude_suffixes_are_accepted():
    envelopes = [env([{"v": 3_867_307_583.83}])]
    for phrasing in ["$3.87B", "3.87 billion", "$3,867,307,583.83", "3867307583.83"]:
        assert verify(f"The total was {phrasing}.", envelopes).ok, phrasing


def test_a_share_quoted_as_a_percent_matches_a_stored_fraction():
    envelopes = [env([{"share": 0.068881}])]
    assert verify("That is 6.89% of the segment.", envelopes).ok


def test_a_materially_different_number_is_caught_despite_being_close():
    """Tolerance must not be so wide that a wrong figure slips through."""
    envelopes = [env([{"v": 3_867_307_583.83}])]
    assert not verify("The total was $4.2B.", envelopes).ok


# ---------------------------------------------------------------------------
# Noise control -- prose numbers must not drown the real findings
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prose", [
    "Here are the top 5 brands.",
    "Two things worth flagging for the deck:",
    "Three ways forward that the data supports.",
    "I checked 4 dimensions before answering.",
])
def test_bare_small_integers_in_prose_are_not_flagged(prose):
    assert verify(prose, [env([{"v": 1.0}])]).ok


def test_years_are_not_flagged_when_they_are_in_coverage():
    envelopes = [env([{"period_year": 2025, "v": 1.0}], years=(2025, 2026))]
    assert verify("In 2025 and 2026 the picture differs.", envelopes).ok


def test_a_large_bare_integer_is_still_checked():
    """No currency or percent marker, but 8,412 is plainly a data claim."""
    assert not verify("There were 8412 products.", [env([{"v": 1.0}])]).ok


def test_state_and_row_counts_are_available_to_quote():
    envelopes = [env([{"v": 1.0}], row_count=74, states=[f"S{i}" for i in range(37)])]
    assert verify("74 rows across 37 states.", envelopes).ok


def test_an_empty_answer_is_trivially_fine():
    assert verify("", [env([{"v": 1.0}])]).ok
    assert verify("No rows matched that filter.", [env([])]).ok


def test_claims_carry_positions_so_the_ui_can_highlight_them():
    envelopes = [env([{"v": 100.0}])]
    result = verify("The figure was $999,999.", envelopes)
    assert not result.ok
    claim = result.unverified[0]
    assert claim.start < claim.end
    assert "999,999" in claim.text
