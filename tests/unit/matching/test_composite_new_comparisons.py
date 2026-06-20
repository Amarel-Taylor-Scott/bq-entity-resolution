"""Tests for new composite comparison functions (distance metrics, Jaccard, regex)."""

from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS

# -- Euclidean distance --

def test_euclidean_distance_registered():
    assert "euclidean_distance" in COMPARISON_FUNCTIONS


def test_euclidean_distance():
    result = COMPARISON_FUNCTIONS["euclidean_distance"]("emb_a", "emb_b")
    assert "ML.DISTANCE" in result
    assert "EUCLIDEAN" in result
    assert "l.emb_a" in result
    assert "r.emb_b" in result
    assert "IS NOT NULL" in result
    assert "1.0" in result  # default max_distance


def test_euclidean_distance_custom_max():
    result = COMPARISON_FUNCTIONS["euclidean_distance"]("emb_a", "emb_b", max_distance=2.5)
    assert "2.5" in result


def test_euclidean_distance_score_registered():
    assert "euclidean_distance_score" in COMPARISON_FUNCTIONS


def test_euclidean_distance_score():
    result = COMPARISON_FUNCTIONS["euclidean_distance_score"]("emb_a", "emb_b")
    assert "ML.DISTANCE" in result
    assert "EUCLIDEAN" in result
    assert "GREATEST(0.0" in result
    assert "CASE WHEN" in result
    assert "ELSE 0.0" in result


def test_euclidean_distance_score_custom_max():
    result = COMPARISON_FUNCTIONS["euclidean_distance_score"]("e1", "e2", max_distance=5.0)
    assert "5.0" in result


# -- Manhattan distance --

def test_manhattan_distance_registered():
    assert "manhattan_distance" in COMPARISON_FUNCTIONS


def test_manhattan_distance():
    result = COMPARISON_FUNCTIONS["manhattan_distance"]("emb_a", "emb_b")
    assert "ML.DISTANCE" in result
    assert "MANHATTAN" in result
    assert "l.emb_a" in result
    assert "r.emb_b" in result
    assert "IS NOT NULL" in result


def test_manhattan_distance_custom_max():
    result = COMPARISON_FUNCTIONS["manhattan_distance"]("e1", "e2", max_distance=3.0)
    assert "3.0" in result


def test_manhattan_distance_score_registered():
    assert "manhattan_distance_score" in COMPARISON_FUNCTIONS


def test_manhattan_distance_score():
    result = COMPARISON_FUNCTIONS["manhattan_distance_score"]("emb_a", "emb_b")
    assert "ML.DISTANCE" in result
    assert "MANHATTAN" in result
    assert "GREATEST(0.0" in result
    assert "CASE WHEN" in result
    assert "ELSE 0.0" in result


# -- Jaccard n-gram --

def test_jaccard_ngram_registered():
    assert "jaccard_ngram" in COMPARISON_FUNCTIONS


def test_jaccard_ngram():
    result = COMPARISON_FUNCTIONS["jaccard_ngram"]("name_a", "name_b")
    assert "SUBSTR" in result
    assert "GENERATE_ARRAY" in result
    assert "UNNEST" in result
    assert "l.name_a" in result
    assert "r.name_b" in result
    assert "0.5" in result  # default min_similarity


def test_jaccard_ngram_custom_n():
    result = COMPARISON_FUNCTIONS["jaccard_ngram"]("col_a", "col_b", n=3)
    assert "3" in result


def test_jaccard_ngram_custom_similarity():
    result = COMPARISON_FUNCTIONS["jaccard_ngram"]("col_a", "col_b", min_similarity=0.7)
    assert "0.7" in result


def test_jaccard_ngram_score_registered():
    assert "jaccard_ngram_score" in COMPARISON_FUNCTIONS


def test_jaccard_ngram_score():
    result = COMPARISON_FUNCTIONS["jaccard_ngram_score"]("name_a", "name_b")
    assert "SUBSTR" in result
    assert "SAFE_DIVIDE" in result
    assert "CASE WHEN" in result
    assert "ELSE 0.0" in result


def test_jaccard_ngram_score_custom_n():
    result = COMPARISON_FUNCTIONS["jaccard_ngram_score"]("a", "b", n=4)
    assert "4" in result


# -- Regex match --

def test_regex_match_registered():
    assert "regex_match" in COMPARISON_FUNCTIONS


def test_regex_match():
    result = COMPARISON_FUNCTIONS["regex_match"]("col_a", "col_b")
    assert "REGEXP_CONTAINS" in result
    assert "IS NOT NULL" in result


def test_regex_match_custom_pattern():
    result = COMPARISON_FUNCTIONS["regex_match"]("col_a", "col_b", pattern="^[A-Z]{3}")
    assert "^[A-Z]{3}" in result
    assert "REGEXP_CONTAINS" in result


# -- Existing cosine_similarity still works --

def test_cosine_similarity_still_works():
    assert "cosine_similarity" in COMPARISON_FUNCTIONS
    result = COMPARISON_FUNCTIONS["cosine_similarity"]("emb_a", "emb_b")
    assert "ML.DISTANCE" in result
    assert "COSINE" in result
