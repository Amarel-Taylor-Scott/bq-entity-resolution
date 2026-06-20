"""SQL builder for UDF creation.

Replaces:
- udfs/jaro_winkler.sql.j2
"""

from __future__ import annotations

from bq_entity_resolution.sql.expression import SQLExpression


def build_jaro_winkler_udf_sql(udf_dataset: str) -> SQLExpression:
    """Build SQL to create the Jaro-Winkler similarity UDF in BigQuery."""
    sql = f"""CREATE OR REPLACE FUNCTION `{udf_dataset}.jaro_winkler`(s1 STRING, s2 STRING)
RETURNS FLOAT64
LANGUAGE js AS r\"\"\"
  if (!s1 || !s2) return 0.0;

  // Uppercase for consistency
  s1 = s1.toUpperCase();
  s2 = s2.toUpperCase();

  if (s1 === s2) return 1.0;

  var len1 = s1.length;
  var len2 = s2.length;

  // Maximum distance for matching
  var matchWindow = Math.max(Math.floor(Math.max(len1, len2) / 2) - 1, 0);

  var s1Matches = new Array(len1).fill(false);
  var s2Matches = new Array(len2).fill(false);

  var matches = 0;
  var transpositions = 0;

  // Find matches
  for (var i = 0; i < len1; i++) {{
    var start = Math.max(0, i - matchWindow);
    var end = Math.min(i + matchWindow + 1, len2);
    for (var j = start; j < end; j++) {{
      if (s2Matches[j] || s1[i] !== s2[j]) continue;
      s1Matches[i] = true;
      s2Matches[j] = true;
      matches++;
      break;
    }}
  }}

  if (matches === 0) return 0.0;

  // Count transpositions
  var k = 0;
  for (var i = 0; i < len1; i++) {{
    if (!s1Matches[i]) continue;
    while (!s2Matches[k]) k++;
    if (s1[i] !== s2[k]) transpositions++;
    k++;
  }}

  var jaro = (matches / len1 + matches / len2 + (matches - transpositions / 2) / matches) / 3;

  // Winkler modification: boost for common prefix (up to 4 chars)
  var prefix = 0;
  for (var i = 0; i < Math.min(4, Math.min(len1, len2)); i++) {{
    if (s1[i] === s2[i]) prefix++;
    else break;
  }}

  return jaro + prefix * 0.1 * (1 - jaro);
\"\"\";"""
    return SQLExpression.from_raw(sql)
