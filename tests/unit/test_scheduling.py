"""Tests for the dependency-free cron evaluation used by leaf scheduling."""

from __future__ import annotations

from datetime import datetime

import pytest

from bq_entity_resolution.scheduling import CronError, cron_matches, is_cron_due

# 2026-06-21 is a Sunday; 2026-06-22 a Monday.
SUNDAY = datetime(2026, 6, 21, 3, 0)
MONDAY = datetime(2026, 6, 22, 3, 0)


class TestCronMatches:
    def test_wildcards_match_everything(self):
        assert cron_matches("* * * * *", datetime(2026, 1, 1, 0, 0))

    def test_weekly_sunday_3am(self):
        assert cron_matches("0 3 * * 0", SUNDAY)
        assert not cron_matches("0 3 * * 0", MONDAY)
        assert not cron_matches("0 3 * * 0", datetime(2026, 6, 21, 4, 0))

    def test_sunday_as_7(self):
        assert cron_matches("0 3 * * 7", SUNDAY)

    def test_step(self):
        assert cron_matches("*/15 * * * *", datetime(2026, 6, 20, 12, 30))
        assert not cron_matches("*/15 * * * *", datetime(2026, 6, 20, 12, 31))

    def test_range(self):
        assert cron_matches("0 0 1-5 * *", datetime(2026, 6, 3, 0, 0))
        assert not cron_matches("0 0 1-5 * *", datetime(2026, 6, 6, 0, 0))

    def test_list(self):
        assert cron_matches("0 0 1,15 * *", datetime(2026, 6, 15, 0, 0))
        assert not cron_matches("0 0 1,15 * *", datetime(2026, 6, 14, 0, 0))

    def test_stepped_range(self):
        assert cron_matches("0 0-23/6 * * *", datetime(2026, 6, 20, 12, 0))
        assert not cron_matches("0 0-23/6 * * *", datetime(2026, 6, 20, 13, 0))

    def test_vixie_dom_or_dow_when_both_restricted(self):
        # Both day-of-month and day-of-week restricted → match if EITHER hits.
        expr = "0 0 13 * 5"  # 13th OR Friday
        assert cron_matches(expr, datetime(2026, 6, 13, 0, 0))  # the 13th (Sat)
        assert cron_matches(expr, datetime(2026, 6, 12, 0, 0))  # a Friday
        assert not cron_matches(expr, datetime(2026, 6, 11, 0, 0))  # neither

    @pytest.mark.parametrize("bad", ["* * * *", "* * * * * *", "bad", ""])
    def test_bad_field_count_raises(self, bad):
        with pytest.raises(CronError):
            cron_matches(bad, SUNDAY)

    @pytest.mark.parametrize("bad", ["99 * * * *", "* 25 * * *", "0 0 0 * *"])
    def test_out_of_bounds_raises(self, bad):
        with pytest.raises(CronError):
            cron_matches(bad, SUNDAY)


class TestIsCronDue:
    def test_none_expr_or_now_not_due(self):
        assert is_cron_due(None, now=SUNDAY, last_run=None) is False
        assert is_cron_due("0 3 * * 0", now=None, last_run=None) is False

    def test_first_run_is_due(self):
        # No last_run → any firing in the bounded look-back counts.
        assert is_cron_due("0 3 * * 0", now=datetime(2026, 6, 21, 4, 0), last_run=None)

    def test_not_due_when_serviced_after_last_firing(self):
        assert not is_cron_due(
            "0 3 * * 0",
            now=datetime(2026, 6, 21, 4, 0),
            last_run=datetime(2026, 6, 21, 3, 0),
        )

    def test_due_when_firing_since_last_run(self):
        # Last ran a week ago; a Sunday 3am firing has occurred since.
        assert is_cron_due(
            "0 3 * * 0",
            now=datetime(2026, 6, 21, 4, 0),
            last_run=datetime(2026, 6, 14, 4, 0),
        )
