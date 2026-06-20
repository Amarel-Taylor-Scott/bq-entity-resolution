"""BQ function shims: macro and UDF registration for DuckDB.

Registers DuckDB macros and Python UDFs that approximate BigQuery-specific
functions so that SQL generated for the BQ dialect can run locally.
"""

from __future__ import annotations

import logging

import duckdb

logger = logging.getLogger(__name__)


def register_bq_shims(conn: duckdb.DuckDBPyConnection) -> bool:
    """Register all BQ-compatible shims on a DuckDB connection.

    Returns True if the spatial extension loaded successfully.
    """
    _register_macros(conn)
    _register_phonetic_udfs(conn)
    has_spatial = _register_geo_shims(conn)
    return has_spatial


def _register_macros(conn: duckdb.DuckDBPyConnection) -> None:
    """Register DuckDB macros that approximate BQ-specific functions."""
    shims = [
        # FARM_FINGERPRINT -> deterministic hash
        "CREATE OR REPLACE MACRO FARM_FINGERPRINT(x) AS hash(CAST(x AS VARCHAR))",
        # SAFE_DIVIDE -> NULL-safe division
        "CREATE OR REPLACE MACRO SAFE_DIVIDE(a, b) AS "
        "CASE WHEN b = 0 OR b IS NULL THEN NULL ELSE CAST(a AS DOUBLE) / CAST(b AS DOUBLE) END",
        # FORMAT_DATE -> strftime
        "CREATE OR REPLACE MACRO FORMAT_DATE(fmt, d) AS strftime(d, fmt)",
        # EDIT_DISTANCE -> native levenshtein
        "CREATE OR REPLACE MACRO EDIT_DISTANCE(a, b) AS "
        "levenshtein(CAST(a AS VARCHAR), CAST(b AS VARCHAR))",
        # jaro_winkler UDF -> native jaro_winkler_similarity
        "CREATE OR REPLACE MACRO jaro_winkler(a, b) AS "
        "jaro_winkler_similarity(CAST(a AS VARCHAR), CAST(b AS VARCHAR))",
        # COUNTIF -> COUNT with CASE WHEN (DuckDB doesn't have COUNTIF)
        "CREATE OR REPLACE MACRO COUNTIF(cond) AS SUM(CASE WHEN cond THEN 1 ELSE 0 END)",
    ]
    for shim in shims:
        try:
            conn.execute(shim)
        except Exception as e:
            logger.debug("Failed to register shim: %s (%s)", shim[:80], e)


def _register_phonetic_udfs(conn: duckdb.DuckDBPyConnection) -> None:
    """Register Python UDFs for SOUNDEX and double_metaphone."""
    # Real SOUNDEX implementation
    def _soundex(s: str) -> str | None:
        if not s or not s.strip():
            return None
        s = s.strip().upper()
        # Keep first letter
        first = ""
        for ch in s:
            if ch.isalpha():
                first = ch
                break
        if not first:
            return None
        coding = {
            "B": "1", "F": "1", "P": "1", "V": "1",
            "C": "2", "G": "2", "J": "2", "K": "2", "Q": "2",
            "S": "2", "X": "2", "Z": "2",
            "D": "3", "T": "3",
            "L": "4",
            "M": "5", "N": "5",
            "R": "6",
        }
        result = first
        prev_code = coding.get(first, "0")
        started = False
        for ch in s:
            if not started:
                if ch == first:
                    started = True
                continue
            code = coding.get(ch, "0")
            if code != "0" and code != prev_code:
                result += code
            prev_code = code if code != "0" else prev_code
            if len(result) == 4:
                break
        return result.ljust(4, "0")

    try:
        conn.create_function(
            "SOUNDEX", _soundex,
            ["VARCHAR"],  # type: ignore[list-item]
            "VARCHAR",  # type: ignore[arg-type]
            null_handling="special",  # type: ignore[arg-type]
        )
    except Exception as e:
        logger.debug("Failed to register SOUNDEX UDF: %s", e)

    # metaphone -- delegates to SOUNDEX unless metaphone library available
    try:
        from metaphone import doublemetaphone  # type: ignore[import-untyped]

        def _metaphone(s: str) -> str | None:
            if not s or not s.strip():
                return None
            result = doublemetaphone(s.strip())
            primary: str | None = result[0] if result[0] else result[1]
            return primary

        def _dm_primary(s: str) -> str | None:
            if not s or not s.strip():
                return None
            return doublemetaphone(s.strip())[0] or None

        def _dm_alternate(s: str) -> str | None:
            if not s or not s.strip():
                return None
            return doublemetaphone(s.strip())[1] or None

        conn.create_function(
            "metaphone", _metaphone,
            ["VARCHAR"],  # type: ignore[list-item]
            "VARCHAR",  # type: ignore[arg-type]
            null_handling="special",  # type: ignore[arg-type]
        )
        conn.create_function(
            "double_metaphone_primary", _dm_primary,
            ["VARCHAR"],  # type: ignore[list-item]
            "VARCHAR",  # type: ignore[arg-type]
            null_handling="special",  # type: ignore[arg-type]
        )
        conn.create_function(
            "double_metaphone_alternate", _dm_alternate,
            ["VARCHAR"],  # type: ignore[list-item]
            "VARCHAR",  # type: ignore[arg-type]
            null_handling="special",  # type: ignore[arg-type]
        )
    except ImportError:
        logger.debug("metaphone library not available; using SOUNDEX fallback")
        try:
            conn.execute(
                "CREATE OR REPLACE MACRO metaphone(x) AS SOUNDEX(x)"
            )
        except Exception as e:
            logger.debug("Failed to register metaphone fallback: %s", e)
    except Exception as e:
        logger.debug("Failed to register metaphone UDFs: %s", e)


def _register_geo_shims(conn: duckdb.DuckDBPyConnection) -> bool:
    """Try to load DuckDB spatial extension for BQ geo function compatibility.

    Returns True if the spatial extension loaded successfully.
    """
    try:
        conn.execute("INSTALL spatial")
        conn.execute("LOAD spatial")
        # ST_GEOGPOINT(lon, lat) -> ST_Point(lon, lat)
        conn.execute(
            "CREATE OR REPLACE MACRO ST_GEOGPOINT(lon, lat) AS "
            "ST_Point(CAST(lon AS DOUBLE), CAST(lat AS DOUBLE))"
        )
        logger.debug("Spatial extension loaded -- geo functions available")
        return True
    except duckdb.IOException:
        logger.debug("Spatial extension not installed -- geo functions disabled")
        return False
    except Exception as e:
        logger.warning(
            "Spatial extension failed to load: %s -- geo functions disabled", e
        )
        return False
