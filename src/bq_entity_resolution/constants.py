"""Shared constants for the entity resolution pipeline."""

# Match status identifiers
MATCH_STATUS_NEW = "NEW_ENTITY"
MATCH_STATUS_MATCHED = "MATCHED_TO_EXISTING"
MATCH_STATUS_REVIEWED = "MANUALLY_REVIEWED"

# Entity type classifications
ENTITY_TYPE_INDIVIDUAL = "INDIVIDUAL"
ENTITY_TYPE_COMMERCIAL = "COMMERCIAL"
ENTITY_TYPE_OTHER = "OTHER"

# Default table suffixes
TABLE_STAGED = "staged"
TABLE_FEATURED = "featured"
TABLE_EMBEDDINGS = "entity_embeddings"
TABLE_LSH_BUCKETS = "lsh_buckets"
TABLE_CANDIDATES_PREFIX = "candidates_"
TABLE_MATCHES_PREFIX = "matches_"
TABLE_ALL_MATCHED_PAIRS = "all_matched_pairs"
TABLE_CLUSTERS = "entity_clusters"
TABLE_RESOLVED = "resolved_entities"
TABLE_WATERMARKS = "pipeline_watermarks"
TABLE_METRICS = "pipeline_metrics"

# BigQuery reserved words that need backtick escaping
BQ_RESERVED_WORDS = frozenset({
    "ALL", "AND", "ANY", "ARRAY", "AS", "ASC", "ASSERT_ROWS_MODIFIED", "AT",
    "BETWEEN", "BY", "CASE", "CAST", "COLLATE", "CONTAINS", "CREATE", "CROSS",
    "CUBE", "CURRENT", "DEFAULT", "DEFINE", "DESC", "DISTINCT", "ELSE", "END",
    "ENUM", "ESCAPE", "EXCEPT", "EXCLUDE", "EXISTS", "EXTRACT", "FALSE", "FETCH",
    "FOLLOWING", "FOR", "FROM", "FULL", "GROUP", "GROUPING", "GROUPS", "HASH",
    "HAVING", "IF", "IGNORE", "IN", "INNER", "INTERSECT", "INTERVAL", "INTO",
    "IS", "JOIN", "LATERAL", "LEFT", "LIKE", "LIMIT", "LOOKUP", "MERGE", "NATURAL",
    "NEW", "NO", "NOT", "NULL", "NULLS", "OF", "ON", "OR", "ORDER", "OUTER",
    "OVER", "PARTITION", "PRECEDING", "PROTO", "RANGE", "RECURSIVE", "RESPECT",
    "RIGHT", "ROLLUP", "ROWS", "SELECT", "SET", "SOME", "STRUCT", "TABLESAMPLE",
    "THEN", "TO", "TREAT", "TRUE", "UNBOUNDED", "UNION", "UNNEST", "USING",
    "WHEN", "WHERE", "WINDOW", "WITH", "WITHIN",
})

# Default pipeline settings
DEFAULT_CANDIDATE_LIMIT = 200
DEFAULT_MAX_CHAIN_DEPTH = 20
DEFAULT_GRACE_PERIOD_HOURS = 48
DEFAULT_BATCH_SIZE = 2_000_000
