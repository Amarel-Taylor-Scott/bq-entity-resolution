"""Tests for name feature functions."""
from __future__ import annotations

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


class TestNameClean:
    def test_returns_sql_string(self):
        result = FEATURE_FUNCTIONS["name_clean"](["first_name"])
        assert isinstance(result, str)

    def test_uppercases(self):
        result = FEATURE_FUNCTIONS["name_clean"](["first_name"])
        assert "UPPER" in result

    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["name_clean"](["full_name"])
        assert "full_name" in result

    def test_trims(self):
        result = FEATURE_FUNCTIONS["name_clean"](["first_name"])
        assert "TRIM" in result


class TestNameCleanStrict:
    def test_returns_sql_string(self):
        result = FEATURE_FUNCTIONS["name_clean_strict"](["first_name"])
        assert isinstance(result, str)

    def test_uppercases(self):
        result = FEATURE_FUNCTIONS["name_clean_strict"](["first_name"])
        assert "UPPER" in result

    def test_removes_nonalpha(self):
        result = FEATURE_FUNCTIONS["name_clean_strict"](["first_name"])
        assert "REGEXP_REPLACE" in result


class TestFirstLetter:
    def test_uses_left_1(self):
        result = FEATURE_FUNCTIONS["first_letter"](["name"])
        assert "LEFT" in result and "1" in result

    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["first_letter"](["col_x"])
        assert "col_x" in result


class TestFirstNChars:
    def test_default_length_3(self):
        result = FEATURE_FUNCTIONS["first_n_chars"](["name"])
        assert "LEFT" in result and "3" in result

    def test_custom_length(self):
        result = FEATURE_FUNCTIONS["first_n_chars"](["name"], length=5)
        assert "5" in result


class TestExtractSalutation:
    def test_returns_case_expression(self):
        result = FEATURE_FUNCTIONS["extract_salutation"](["name"])
        assert "CASE" in result

    def test_detects_common_salutations(self):
        result = FEATURE_FUNCTIONS["extract_salutation"](["name"])
        assert "MR" in result and "MRS" in result and "DR" in result


class TestStripSalutation:
    def test_returns_regexp_replace(self):
        result = FEATURE_FUNCTIONS["strip_salutation"](["name"])
        assert "REGEXP_REPLACE" in result

    def test_removes_common_salutations(self):
        result = FEATURE_FUNCTIONS["strip_salutation"](["name"])
        assert "MR" in result and "MRS" in result


class TestExtractSuffix:
    def test_extracts_name_suffixes(self):
        result = FEATURE_FUNCTIONS["extract_suffix"](["name"])
        assert "JR" in result and "SR" in result and "III" in result

    def test_uses_regexp_extract(self):
        result = FEATURE_FUNCTIONS["extract_suffix"](["name"])
        assert "REGEXP_EXTRACT" in result


class TestStripSuffix:
    def test_strips_suffixes(self):
        result = FEATURE_FUNCTIONS["strip_suffix"](["name"])
        assert "REGEXP_REPLACE" in result and "JR" in result and "SR" in result


class TestWordCount:
    def test_uses_split_and_array_length(self):
        result = FEATURE_FUNCTIONS["word_count"](["name"])
        assert "ARRAY_LENGTH" in result and "SPLIT" in result


class TestFirstWord:
    def test_uses_split_and_offset(self):
        result = FEATURE_FUNCTIONS["first_word"](["name"])
        assert "SPLIT" in result and "OFFSET" in result


class TestLastWord:
    def test_uses_array_reverse(self):
        result = FEATURE_FUNCTIONS["last_word"](["name"])
        assert "ARRAY_REVERSE" in result and "SPLIT" in result


class TestInitials:
    def test_uses_string_agg(self):
        result = FEATURE_FUNCTIONS["initials"](["name"])
        assert "STRING_AGG" in result and "LEFT" in result

    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["initials"](["full_name"])
        assert "full_name" in result


class TestStripBusinessSuffix:
    def test_strips_common_suffixes(self):
        result = FEATURE_FUNCTIONS["strip_business_suffix"](["company"])
        assert "LLC" in result and "INC" in result and "CORP" in result

    def test_uses_regexp_replace(self):
        result = FEATURE_FUNCTIONS["strip_business_suffix"](["company"])
        assert "REGEXP_REPLACE" in result


class TestNicknameCanonical:
    def test_returns_case_expression(self):
        result = FEATURE_FUNCTIONS["nickname_canonical"](["first_name"])
        assert "CASE" in result

    def test_maps_common_nicknames(self):
        result = FEATURE_FUNCTIONS["nickname_canonical"](["first_name"])
        assert "BOB" in result and "ROBERT" in result
        assert "BILL" in result and "WILLIAM" in result

    def test_falls_back_to_upper_trim(self):
        result = FEATURE_FUNCTIONS["nickname_canonical"](["first_name"])
        assert "ELSE UPPER(TRIM" in result


class TestNicknameMatchKey:
    def test_wraps_in_farm_fingerprint(self):
        result = FEATURE_FUNCTIONS["nickname_match_key"](["first_name"])
        assert "FARM_FINGERPRINT" in result

    def test_includes_nickname_logic(self):
        result = FEATURE_FUNCTIONS["nickname_match_key"](["first_name"])
        assert "CASE" in result  # Contains nickname_canonical CASE expression


class TestIsCompoundName:
    def test_returns_0_1_case(self):
        result = FEATURE_FUNCTIONS["is_compound_name"](["name"])
        assert "CASE" in result and "1" in result and "0" in result

    def test_detects_and_pattern(self):
        result = FEATURE_FUNCTIONS["is_compound_name"](["name"])
        assert "AND" in result


class TestCompoundPattern:
    def test_classifies_patterns(self):
        result = FEATURE_FUNCTIONS["compound_pattern"](["name"])
        assert "title_pair" in result and "conjunction" in result
        assert "family" in result and "slash" in result


class TestExtractCompoundFirst:
    def test_extracts_first_name(self):
        result = FEATURE_FUNCTIONS["extract_compound_first"](["name"])
        assert "CASE" in result and "REGEXP_EXTRACT" in result


class TestExtractCompoundSecond:
    def test_extracts_second_name(self):
        result = FEATURE_FUNCTIONS["extract_compound_second"](["name"])
        assert "CASE" in result and "REGEXP_EXTRACT" in result
