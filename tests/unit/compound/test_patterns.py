"""Tests for compound record pattern constants."""

from __future__ import annotations

from bq_entity_resolution.compound.patterns import (
    CONJUNCTION_RE,
    CONJUNCTIONS,
    FAMILY_RE,
    FAMILY_SUFFIXES,
    SLASH_RE,
    TITLE_PAIR_RE,
    TITLE_PREFIXES,
)


class TestPatternConstants:
    def test_conjunctions_is_tuple(self):
        assert isinstance(CONJUNCTIONS, tuple)
        assert "AND" in CONJUNCTIONS
        assert "&" in CONJUNCTIONS
        assert "+" in CONJUNCTIONS

    def test_title_prefixes_is_tuple(self):
        assert isinstance(TITLE_PREFIXES, tuple)
        assert "MR" in TITLE_PREFIXES
        assert "MRS" in TITLE_PREFIXES
        assert "DR" in TITLE_PREFIXES

    def test_family_suffixes_is_tuple(self):
        assert isinstance(FAMILY_SUFFIXES, tuple)
        assert "FAMILY" in FAMILY_SUFFIXES
        assert "HOUSEHOLD" in FAMILY_SUFFIXES

    def test_regex_fragments_are_strings(self):
        assert isinstance(CONJUNCTION_RE, str)
        assert isinstance(TITLE_PAIR_RE, str)
        assert isinstance(FAMILY_RE, str)
        assert isinstance(SLASH_RE, str)

    def test_regex_fragments_are_nonempty(self):
        for frag in [CONJUNCTION_RE, TITLE_PAIR_RE, FAMILY_RE, SLASH_RE]:
            assert len(frag) > 0
