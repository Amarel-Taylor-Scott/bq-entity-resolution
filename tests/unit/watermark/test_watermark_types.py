"""Tests for watermark manager serialization/deserialization with DATE/NUMERIC types."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from bq_entity_resolution.exceptions import WatermarkError
from bq_entity_resolution.watermark.manager import _deserialize, _serialize, _type_name

# ---------------------------------------------------------------------------
# _deserialize
# ---------------------------------------------------------------------------

class TestDeserialize:
    """Tests for _deserialize: stored string -> Python value."""

    def test_timestamp_returns_datetime(self):
        result = _deserialize("2024-06-15T10:30:00+00:00", "TIMESTAMP")
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15

    def test_date_returns_date(self):
        result = _deserialize("2024-06-15", "DATE")
        assert isinstance(result, date)
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15

    def test_int64_returns_int(self):
        result = _deserialize("42", "INT64")
        assert isinstance(result, int)
        assert result == 42

    def test_float64_returns_float(self):
        result = _deserialize("3.14", "FLOAT64")
        assert isinstance(result, float)
        assert abs(result - 3.14) < 1e-6

    def test_numeric_returns_decimal(self):
        result = _deserialize("123456.789012345", "NUMERIC")
        assert isinstance(result, Decimal)
        assert result == Decimal("123456.789012345")

    def test_bignumeric_returns_decimal(self):
        result = _deserialize("99999999999999999999.12345", "BIGNUMERIC")
        assert isinstance(result, Decimal)
        assert result == Decimal("99999999999999999999.12345")

    def test_string_returns_string(self):
        result = _deserialize("hello_world", "STRING")
        assert isinstance(result, str)
        assert result == "hello_world"

    def test_unknown_type_raises_watermark_error(self):
        with pytest.raises(WatermarkError, match="Unsupported watermark type"):
            _deserialize("value", "UNKNOWN_TYPE")

    def test_unknown_type_includes_type_name(self):
        with pytest.raises(WatermarkError, match="BYTES"):
            _deserialize("0x00", "BYTES")

    def test_numeric_preserves_precision(self):
        """NUMERIC must preserve exact decimal precision."""
        value = "12345678901234567890.123456789"
        result = _deserialize(value, "NUMERIC")
        assert str(result) == value

    def test_date_iso_format(self):
        """DATE accepts ISO 8601 date format."""
        result = _deserialize("2025-01-01", "DATE")
        assert result == date(2025, 1, 1)

    def test_int64_negative(self):
        result = _deserialize("-100", "INT64")
        assert result == -100

    def test_float64_negative(self):
        result = _deserialize("-2.5", "FLOAT64")
        assert result == -2.5


# ---------------------------------------------------------------------------
# _serialize
# ---------------------------------------------------------------------------

class TestSerialize:
    """Tests for _serialize: Python value -> string for storage."""

    def test_datetime_returns_iso_string(self):
        dt = datetime(2024, 6, 15, 10, 30, 0, tzinfo=UTC)
        result = _serialize(dt)
        assert isinstance(result, str)
        assert "2024-06-15" in result
        assert "10:30:00" in result

    def test_date_returns_iso_string(self):
        d = date(2024, 6, 15)
        result = _serialize(d)
        assert result == "2024-06-15"

    def test_decimal_returns_string(self):
        d = Decimal("123456.789")
        result = _serialize(d)
        assert result == "123456.789"
        assert isinstance(result, str)

    def test_int_returns_string(self):
        result = _serialize(42)
        assert result == "42"

    def test_float_returns_string(self):
        result = _serialize(3.14)
        assert result == "3.14"

    def test_string_returns_itself(self):
        result = _serialize("hello")
        assert result == "hello"

    def test_decimal_preserves_precision(self):
        d = Decimal("99999999999999999999.123456789012345678")
        result = _serialize(d)
        assert result == "99999999999999999999.123456789012345678"

    def test_datetime_roundtrip(self):
        """Serialize then deserialize should produce equivalent value."""
        dt = datetime(2024, 3, 15, 8, 0, 0, tzinfo=UTC)
        serialized = _serialize(dt)
        deserialized = _deserialize(serialized, "TIMESTAMP")
        assert deserialized.year == dt.year
        assert deserialized.month == dt.month
        assert deserialized.day == dt.day

    def test_date_roundtrip(self):
        d = date(2024, 12, 25)
        serialized = _serialize(d)
        deserialized = _deserialize(serialized, "DATE")
        assert deserialized == d

    def test_decimal_roundtrip(self):
        d = Decimal("123.456")
        serialized = _serialize(d)
        deserialized = _deserialize(serialized, "NUMERIC")
        assert deserialized == d


# ---------------------------------------------------------------------------
# _type_name
# ---------------------------------------------------------------------------

class TestTypeName:
    """Tests for _type_name: Python value -> BQ type string."""

    def test_datetime_returns_timestamp(self):
        assert _type_name(datetime.now(UTC)) == "TIMESTAMP"

    def test_date_returns_date(self):
        assert _type_name(date.today()) == "DATE"

    def test_decimal_returns_numeric(self):
        assert _type_name(Decimal("1.23")) == "NUMERIC"

    def test_int_returns_int64(self):
        assert _type_name(42) == "INT64"

    def test_float_returns_float64(self):
        assert _type_name(3.14) == "FLOAT64"

    def test_string_returns_string(self):
        assert _type_name("hello") == "STRING"

    def test_none_returns_string(self):
        """None falls through to string (default)."""
        assert _type_name(None) == "STRING"

    def test_date_not_confused_with_datetime(self):
        """date is checked before datetime in isinstance chain.

        datetime is a subclass of date, so order matters.
        _type_name checks datetime first, then date.
        """
        d = date(2024, 1, 1)
        assert _type_name(d) == "DATE"
        dt = datetime(2024, 1, 1, tzinfo=UTC)
        assert _type_name(dt) == "TIMESTAMP"

    def test_zero_int(self):
        assert _type_name(0) == "INT64"

    def test_zero_float(self):
        assert _type_name(0.0) == "FLOAT64"

    def test_zero_decimal(self):
        assert _type_name(Decimal("0")) == "NUMERIC"

    def test_empty_string(self):
        assert _type_name("") == "STRING"
