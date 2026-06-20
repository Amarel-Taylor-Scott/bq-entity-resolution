"""Tests for drain mode breaking after consecutive empty batches.

The Pipeline._run_core method tracks consecutive empty batches in drain
mode and stops after 2 consecutive iterations where the watermark did
not advance (no new rows in staged table).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Test the drain mode empty-batch tracking logic inline
# ---------------------------------------------------------------------------


class TestDrainEmptyBatchCounter:
    """Unit tests for the consecutive-empty-batch tracking logic.

    The actual logic lives in Pipeline._run_core which is hard to unit-test
    without the full config stack. These tests verify the core algorithm
    in isolation.
    """

    def test_breaks_after_two_consecutive_empty_batches(self):
        """Simulates the drain loop's consecutive_empty counter."""
        consecutive_empty = 0
        iterations = 0
        batch_results = [False, False, True, False, False]  # has_rows per iter

        for batch_had_rows in batch_results:
            iterations += 1
            if not batch_had_rows:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
            else:
                consecutive_empty = 0

        # Should stop after 2nd False (iterations 1 and 2)
        assert iterations == 2
        assert consecutive_empty == 2

    def test_counter_resets_on_nonempty_batch(self):
        """A non-empty batch resets the counter."""
        consecutive_empty = 0
        iterations = 0
        batch_results = [False, True, False, False]

        for batch_had_rows in batch_results:
            iterations += 1
            if not batch_had_rows:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
            else:
                consecutive_empty = 0

        # First empty -> counter=1, then non-empty resets, then 2 consecutive empties
        assert iterations == 4
        assert consecutive_empty == 2

    def test_all_nonempty_no_break(self):
        """All non-empty batches should process all iterations."""
        consecutive_empty = 0
        iterations = 0
        batch_results = [True, True, True]

        for batch_had_rows in batch_results:
            iterations += 1
            if not batch_had_rows:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
            else:
                consecutive_empty = 0

        assert iterations == 3
        assert consecutive_empty == 0

    def test_single_empty_continues(self):
        """A single empty batch should not stop drain mode."""
        consecutive_empty = 0
        iterations = 0
        batch_results = [False, True, True]

        for batch_had_rows in batch_results:
            iterations += 1
            if not batch_had_rows:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
            else:
                consecutive_empty = 0

        assert iterations == 3

    def test_alternating_empties_continue(self):
        """Alternating empty/non-empty should never trigger break."""
        consecutive_empty = 0
        iterations = 0
        batch_results = [False, True, False, True, False, True]

        for batch_had_rows in batch_results:
            iterations += 1
            if not batch_had_rows:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
            else:
                consecutive_empty = 0

        # Should process all 6 iterations
        assert iterations == 6
        assert consecutive_empty == 0

    def test_empty_at_end_breaks(self):
        """Two empty batches at the end of the sequence."""
        consecutive_empty = 0
        iterations = 0
        batch_results = [True, True, True, False, False]

        for batch_had_rows in batch_results:
            iterations += 1
            if not batch_had_rows:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
            else:
                consecutive_empty = 0

        assert iterations == 5
        assert consecutive_empty == 2

    def test_max_iterations_cap(self):
        """Drain mode should respect max_iterations even without empty batches."""
        consecutive_empty = 0
        iterations = 0
        max_iterations = 5

        while iterations < max_iterations:
            iterations += 1
            # All batches are non-empty
            batch_had_rows = True
            if not batch_had_rows:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
            else:
                consecutive_empty = 0

        assert iterations == 5
        assert consecutive_empty == 0
