"""Tests for comparison function registry."""

from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS


def test_exact():
    result = COMPARISON_FUNCTIONS["exact"]("col_a", "col_b")
    assert "l.col_a = r.col_b" in result
    assert "IS NOT NULL" in result


def test_exact_case_insensitive():
    result = COMPARISON_FUNCTIONS["exact_case_insensitive"]("col_a", "col_b")
    assert "UPPER" in result


def test_levenshtein():
    result = COMPARISON_FUNCTIONS["levenshtein"]("name_a", "name_b", max_distance=3)
    assert "EDIT_DISTANCE" in result
    assert "3" in result


def test_levenshtein_normalized():
    result = COMPARISON_FUNCTIONS["levenshtein_normalized"]("a", "b", threshold=0.9)
    assert "EDIT_DISTANCE" in result
    assert "SAFE_DIVIDE" in result
    assert "0.9" in result


def test_cosine_similarity():
    result = COMPARISON_FUNCTIONS["cosine_similarity"]("emb_a", "emb_b", min_similarity=0.85)
    assert "ML.DISTANCE" in result
    assert "COSINE" in result


def test_different():
    result = COMPARISON_FUNCTIONS["different"]("col_a", "col_b")
    assert "!=" in result
    assert "IS NOT NULL" in result


def test_soundex_match():
    result = COMPARISON_FUNCTIONS["soundex_match"]("name_a", "name_b")
    assert "SOUNDEX" in result


def test_token_set_match():
    result = COMPARISON_FUNCTIONS["token_set_match"]("name_a", "name_b", min_overlap=0.5)
    assert "SPLIT" in result
    assert "UNNEST" in result
    assert "0.5" in result


def test_abbreviation_match():
    result = COMPARISON_FUNCTIONS["abbreviation_match"]("name_a", "name_b")
    assert "STARTS_WITH" in result


def test_jaro_winkler_with_dataset():
    result = COMPARISON_FUNCTIONS["jaro_winkler"](
        "name_a", "name_b", threshold=0.9, udf_dataset="proj.er_udfs"
    )
    assert "proj.er_udfs" in result
    assert "jaro_winkler" in result
    assert "0.9" in result


def test_all_comparison_functions():
    """Ensure core comparison functions are registered."""
    expected = {
        "exact", "exact_case_insensitive", "levenshtein",
        "levenshtein_normalized", "jaro_winkler", "cosine_similarity",
        "different", "soundex_match", "contains", "starts_with",
        # New ER best practice comparisons
        "token_set_match", "token_set_score",
        "initials_match", "abbreviation_match",
        # Geo-spatial comparisons
        "geo_within_km", "geo_distance_score",
        # Phonetic comparisons
        "metaphone_match", "double_metaphone_match",
    }
    assert expected.issubset(set(COMPARISON_FUNCTIONS.keys()))
