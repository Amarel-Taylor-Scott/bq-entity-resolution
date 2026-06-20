# Function Catalog

Complete reference for all feature functions and comparison methods in bq-entity-resolution.

**Feature functions** transform raw columns into cleaned, normalized, or derived values during the feature engineering stage. They run once per record.

**Comparison methods** evaluate similarity between two candidate records during the matching stage. They run once per candidate pair, so cost matters at scale.

---

## Table of Contents

- [Feature Functions](#feature-functions)
  - [Name Features](#name-features) (19 functions)
  - [Address Features](#address-features) (4 functions)
  - [Contact Features](#contact-features) (6 functions)
  - [Date and Identity Features](#date-and-identity-features) (7 functions)
  - [Geo Features](#geo-features) (3 functions)
  - [Blocking Key Features](#blocking-key-features) (6 functions)
  - [Utility Features](#utility-features) (12 functions)
  - [Phonetic Features](#phonetic-features) (1 function)
  - [Zip Features](#zip-features) (2 functions)
  - [Industry Features](#industry-features) (16 functions)
- [Comparison Methods](#comparison-methods)
  - [String Comparisons](#string-comparisons) (17 methods)
  - [Numeric Comparisons](#numeric-comparisons) (4 methods)
  - [Date Comparisons](#date-comparisons) (6 methods)
  - [Geo Comparisons](#geo-comparisons) (2 methods)
  - [Null and Hard-Negative Comparisons](#null-and-hard-negative-comparisons) (3 methods)
  - [Composite and Vector Comparisons](#composite-and-vector-comparisons) (9 methods)
- [Cost Tiers](#cost-tiers)
- [Adding Custom Functions](#adding-custom-functions)

---

## Feature Functions

Feature functions are referenced in YAML config under `feature_engineering`. Each takes one or more input columns and optional parameters, and produces a BigQuery SQL expression.

### YAML Pattern

```yaml
feature_engineering:
  name_features:
    features:
      - name: first_name_clean        # Output column name
        function: name_clean           # Function from this catalog
        input: first_name              # Single input column
      - name: full_name_fp
        function: farm_fingerprint_concat
        inputs: [first_name, last_name]  # Multiple input columns
      - name: first_3
        function: first_n_chars
        input: first_name
        params:                        # Optional parameters
          length: 3
```

---

### Name Features

Functions for cleaning, parsing, and normalizing person and business names.

Source: `src/bq_entity_resolution/features/name_features.py`

| Function | Inputs | Params | Output Type | Description |
|----------|--------|--------|-------------|-------------|
| `name_clean` | 1 | -- | STRING | Uppercase, remove non-alpha (keep spaces/hyphens), collapse whitespace. Standard name cleaning. |
| `name_clean_strict` | 1 | -- | STRING | Uppercase, remove everything except letters, collapse whitespace. Stricter than `name_clean` (removes hyphens). |
| `first_letter` | 1 | -- | STRING (1 char) | Extract first character of the string. |
| `first_n_chars` | 1 | `length` (default: 3) | STRING | Extract first N characters. |
| `extract_salutation` | 1 | -- | STRING or NULL | Extract salutation (MR, MRS, MS, DR, PROF, REV, HON) from name string. Returns NULL if none found. |
| `strip_salutation` | 1 | -- | STRING | Remove salutation prefix from name string. |
| `extract_suffix` | 1 | -- | STRING or NULL | Extract name suffix (JR, SR, II, III, IV, ESQ, PHD, MD). Returns NULL if none found. |
| `strip_suffix` | 1 | -- | STRING | Remove name suffix from the end of the string. |
| `word_count` | 1 | -- | INT64 | Count number of words in a string. |
| `first_word` | 1 | -- | STRING | Extract first word (splits on spaces). |
| `last_word` | 1 | -- | STRING | Extract last word (splits on spaces). |
| `initials` | 1 | -- | STRING | Extract initials from each word. "John Adam Smith" becomes "JAS". |
| `strip_business_suffix` | 1 | -- | STRING | Remove common business suffixes: LLC, INC, CORP, LTD, LP, LLP, PLLC, CO, GROUP, HOLDINGS, etc. |
| `nickname_canonical` | 1 | -- | STRING | Map common English nicknames to canonical form. "BOB" becomes "ROBERT", "BILL" becomes "WILLIAM". 60+ mappings built-in. |
| `nickname_match_key` | 1 | -- | INT64 | FARM_FINGERPRINT of the canonical name form. BOB, BOBBY, ROBERT all hash to the same INT64 value. Ideal blocking key for nickname-aware matching. |
| `is_compound_name` | 1 | -- | INT64 (0/1) | Detect compound names containing multiple people. Matches conjunctions (and/&/+), title pairs (Mr. and Mrs.), family patterns (The X Family), slash separators (John/Jane). |
| `compound_pattern` | 1 | -- | STRING or NULL | Classify compound pattern type. Returns one of: `title_pair`, `conjunction`, `family`, `slash`, or NULL. |
| `extract_compound_first` | 1 | -- | STRING or NULL | Extract first individual name from a compound record. "Jane and Joe Smith" returns "JANE". |
| `extract_compound_second` | 1 | -- | STRING or NULL | Extract second individual name from a compound record. "Jane and Joe Smith" returns "JOE". |

**When to use name features:**

- `name_clean` -- Default first step for any person name column. Use before comparisons or as input to other name features.
- `name_clean_strict` -- When hyphens in names cause false matches (e.g., "Anne-Marie" should match "Anne Marie").
- `strip_salutation` + `strip_suffix` -- When records mix salutations/suffixes inconsistently ("Dr. John Smith Jr." vs "John Smith").
- `nickname_canonical` -- When comparing first names where nicknames are common (person dedup, insurance claims).
- `nickname_match_key` -- As a blocking key to group Bob/Robert/Bobby together for candidate generation.
- `strip_business_suffix` -- When matching business/company names with inconsistent legal suffixes.
- `is_compound_name` -- When source data contains household-level records that need detection before matching.

**Example: Name cleaning pipeline**

```yaml
feature_engineering:
  name_features:
    features:
      - name: first_name_clean
        function: name_clean
        input: first_name
      - name: first_name_canonical
        function: nickname_canonical
        input: first_name_clean
      - name: last_name_clean
        function: name_clean
        input: last_name
      - name: last_name_no_suffix
        function: strip_suffix
        input: last_name_clean
```

---

### Address Features

Functions for standardizing and parsing street addresses per USPS Publication 28 conventions.

Source: `src/bq_entity_resolution/features/address_features.py`

| Function | Inputs | Params | Output Type | Description |
|----------|--------|--------|-------------|-------------|
| `address_standardize` | 1 | -- | STRING | Full address standardization: uppercase, abbreviate 40+ street types (STREET to ST, AVENUE to AVE, etc.), directions (NORTH to N), unit designators (APARTMENT to APT), collapse whitespace. |
| `extract_street_number` | 1 | -- | STRING | Extract leading street number from address. "123 Main St" returns "123". |
| `extract_street_name` | 1 | -- | STRING | Extract street name portion after number, before suffix. |
| `extract_unit_number` | 1 | -- | STRING or NULL | Extract apartment/suite/unit number. Handles APT, SUITE, STE, UNIT, #, NO. |

**When to use address features:**

- `address_standardize` -- Always use as the first step for any address column. This is the most compute-expensive feature function (40+ nested REGEXP_REPLACE calls), so always store as a pre-computed feature column.
- `extract_street_number` -- Cheap blocking key (1-5 character string). Combine with zip for effective address blocking.
- `extract_unit_number` -- When matching needs to distinguish units within the same building.

**Performance warning:** `address_standardize` is expensive. For blocking, always wrap in `farm_fingerprint`:

```yaml
feature_engineering:
  address_features:
    features:
      - name: address_std
        function: address_standardize
        input: address
  blocking_keys:
    - name: bk_address
      function: farm_fingerprint
      inputs: [address_std]
```

---

### Contact Features

Functions for normalizing phone numbers and email addresses.

Source: `src/bq_entity_resolution/features/contact_features.py`

| Function | Inputs | Params | Output Type | Description |
|----------|--------|--------|-------------|-------------|
| `phone_standardize` | 1 | -- | STRING | Normalize phone: strip non-digits, remove leading country codes (US "1", UK/EU "0"), take last 10 digits for consistent comparison. |
| `phone_area_code` | 1 | -- | STRING (3 chars) | Extract area code (first 3 digits of normalized 10-digit phone). |
| `phone_last_four` | 1 | -- | STRING (4 chars) | Extract last 4 digits (subscriber number). |
| `email_domain` | 1 | -- | STRING | Extract email domain (after @), lowercased. |
| `email_local_part` | 1 | -- | STRING | Extract email local part (before @), lowercased. |
| `email_domain_type` | 1 | -- | STRING | Classify email domain as "FREE" (gmail, yahoo, hotmail, outlook, aol, icloud, etc.), "BUSINESS", or NULL. |

**When to use contact features:**

- `phone_standardize` -- Always use before any phone comparison. Handles format variations like "(555) 123-4567", "1-555-123-4567", "+1 555.123.4567".
- `phone_area_code` -- Blocking key for geographic phone grouping.
- `email_domain` -- Blocking key when matching employees of the same company.
- `email_domain_type` -- Weighting: free email matches (gmail vs gmail) are less meaningful than business email matches.

**Example: Contact feature pipeline**

```yaml
feature_engineering:
  contact_features:
    features:
      - name: phone_clean
        function: phone_standardize
        input: phone_number
      - name: email_lower
        function: lower_trim
        input: email
      - name: email_dom
        function: email_domain
        input: email
      - name: email_type
        function: email_domain_type
        input: email
  blocking_keys:
    - name: bk_phone
      function: farm_fingerprint
      inputs: [phone_clean]
    - name: bk_email_domain
      function: farm_fingerprint
      inputs: [email_dom]
```

---

### Date and Identity Features

Functions for dates (DOB, policy dates) and identity documents (SSN).

Source: `src/bq_entity_resolution/features/date_identity_features.py`

| Function | Inputs | Params | Output Type | Description |
|----------|--------|--------|-------------|-------------|
| `year_of_date` | 1 | -- | INT64 | Extract year from a date/timestamp column. |
| `date_to_string` | 1 | `fmt` (default: `%Y%m%d`) | STRING | Format a date as a string using BigQuery FORMAT_DATE. |
| `dob_year` | 1 | -- | INT64 | Extract year of birth from a DATE column. Same as `year_of_date` but semantically specific. |
| `age_from_dob` | 1 | -- | INT64 | Compute current age in years from a DATE column using CURRENT_DATE(). |
| `dob_mmdd` | 1 | -- | STRING (4 chars) | Extract month+day from a DATE column as "MMDD" string. Useful for blocking (people with same birthday month+day). |
| `ssn_last_four` | 1 | -- | STRING (4 chars) | Extract last 4 digits of an SSN (strips dashes/spaces first). |
| `ssn_clean` | 1 | -- | STRING (9 chars) | Strip non-digit characters from SSN. "123-45-6789" becomes "123456789". |

**When to use date/identity features:**

- `dob_year` -- Blocking key for person matching. INT64 output, ideal for equi-join blocking.
- `dob_mmdd` -- Secondary blocking key. Combined with name prefix, creates tight blocks.
- `age_from_dob` -- When comparing people who should be approximately the same age. Pair with `age_difference` comparison.
- `ssn_last_four` -- Blocking key for partial SSN matching when full SSN comparison is too restrictive (data quality issues).
- `ssn_clean` -- Feature preparation before exact or partial SSN comparison.

---

### Geo Features

Functions for geographic coordinate processing and spatial blocking.

Source: `src/bq_entity_resolution/features/geo_features.py`

| Function | Inputs | Params | Output Type | Description |
|----------|--------|--------|-------------|-------------|
| `geo_hash` | 2: [lat, lon] | `precision` (default: 6) | STRING | Geohash from latitude and longitude using BigQuery ST_GEOHASH. Precision 6 gives ~1.2km cells. |
| `lat_lon_bucket` | 2: [lat, lon] | `grid_size_km` (default: 10) | STRING | Grid cell blocking key. Divides globe into cells of approximately `grid_size_km`. Returns "lat_lon" bucket string. |
| `haversine_distance` | 4: [lat1, lon1, lat2, lon2] | -- | FLOAT64 | Distance in kilometers between two lat/lon points using BigQuery ST_DISTANCE. |

**When to use geo features:**

- `geo_hash` -- Primary geo blocking key. Precision 4 = ~40km cells, 5 = ~5km, 6 = ~1.2km, 7 = ~150m.
- `lat_lon_bucket` -- Alternative to geohash with explicit km control. Better when you need a specific radius.
- `haversine_distance` -- Pre-computed distance feature. Usually it is better to use the `geo_within_km` or `geo_distance_score` comparison methods directly.

**Example: Geo blocking**

```yaml
feature_engineering:
  geo_features:
    features:
      - name: geo6
        function: geo_hash
        inputs: [latitude, longitude]
        params:
          precision: 6
  blocking_keys:
    - name: bk_geo
      function: farm_fingerprint
      inputs: [geo6]
```

---

### Blocking Key Features

Functions that produce INT64 fingerprints optimized for equi-join blocking. These are the fastest possible blocking keys in BigQuery.

Source: `src/bq_entity_resolution/features/blocking_keys.py`

| Function | Inputs | Params | Output Type | Description |
|----------|--------|--------|-------------|-------------|
| `farm_fingerprint` | 1 | -- | INT64 | FARM_FINGERPRINT hash of a single column. Deterministic, ~1 in 2^63 collision probability. The fastest blocking key type. |
| `farm_fingerprint_concat` | 2+ | -- | INT64 | FARM_FINGERPRINT of concatenated columns (separated by `\|\|`). Combines multiple columns into one INT64 key, enabling a single equi-join instead of multiple ANDs. |
| `identity` | 1 | -- | same as input | Pass through column unchanged. Use when the column is already in a suitable type (e.g., INT64 primary key). |
| `sorted_name_tokens` | 1 | -- | STRING | Sort words alphabetically to handle transpositions. "Smith John" and "John Smith" both become "JOHN SMITH". |
| `sorted_name_fingerprint` | 1 | -- | INT64 | FARM_FINGERPRINT of sorted name tokens. Transposition-resistant blocking: "Smith John" and "John Smith" produce the same INT64. |
| `name_fingerprint` | 1 | -- | INT64 | FARM_FINGERPRINT of alpha-only uppercased characters. Strips all non-alpha characters then hashes. Catches whitespace and punctuation variations. |

**When to use blocking key features:**

- `farm_fingerprint` -- Wrap any STRING column to get INT64 blocking. 3-5x faster than STRING equi-joins.
- `farm_fingerprint_concat` -- Composite blocking key. `fp(last_name || dob)` is faster than `l.last_name = r.last_name AND l.dob = r.dob`.
- `sorted_name_fingerprint` -- Name matching where first/last name transposition is common.
- `name_fingerprint` -- Name matching where punctuation and spacing vary ("O'Brien" vs "OBrien" vs "O Brien").

**Example: Blocking key configuration**

```yaml
feature_engineering:
  blocking_keys:
    - name: bk_name
      function: name_fingerprint
      inputs: [last_name_clean]
    - name: bk_name_dob
      function: farm_fingerprint_concat
      inputs: [last_name_clean, dob]
    - name: bk_email
      function: farm_fingerprint
      inputs: [email_clean]
    - name: bk_name_sorted
      function: sorted_name_fingerprint
      inputs: [full_name_clean]
```

---

### Utility Features

General-purpose text manipulation, null handling, and phonetic functions.

Source: `src/bq_entity_resolution/features/utility_features.py`

| Function | Inputs | Params | Output Type | Description |
|----------|--------|--------|-------------|-------------|
| `upper_trim` | 1 | -- | STRING | Uppercase and trim whitespace. Simplest normalization. |
| `lower_trim` | 1 | -- | STRING | Lowercase and trim whitespace. |
| `left` | 1 | `length` (default: 5) | STRING | Extract leftmost N characters. |
| `right` | 1 | `length` (default: 4) | STRING | Extract rightmost N characters. |
| `coalesce` | 2+ | -- | varies | COALESCE multiple columns. Returns first non-null value. |
| `concat` | 2+ | `separator` (default: `" "`) | STRING | Concatenate columns with separator. NULLs become empty strings. |
| `nullif_empty` | 1 | -- | STRING or NULL | Convert empty strings to NULL. Use to normalize blank-vs-null inconsistencies. |
| `is_not_null` | 1 | -- | INT64 (0/1) | Returns 1 if column is not null, 0 otherwise. Use for match flags and filtering. |
| `char_length` | 1 | -- | INT64 | String length. Cheap to compute and compare. |
| `soundex` | 1 | -- | STRING (4 chars) | Soundex phonetic encoding. For blocking, wrap in FARM_FINGERPRINT for INT64. |
| `remove_diacritics` | 1 | -- | STRING | Remove diacritical marks and accents. Converts characters with accents to ASCII equivalents (e to E, n to N, u to U, etc.). |
| `normalize_whitespace` | 1 | -- | STRING | Collapse multiple whitespace characters to single space and trim. |

**When to use utility features:**

- `upper_trim` / `lower_trim` -- Minimum normalization for any text column.
- `coalesce` -- When multiple columns may contain the same data (e.g., `home_phone`, `mobile_phone`).
- `nullif_empty` -- Data cleanup when source systems use empty strings instead of NULL.
- `soundex` -- Phonetic blocking for names. Wrap in `farm_fingerprint` for INT64 key.
- `remove_diacritics` -- International name matching where "Muller" should match "Mueller" or "Muller".
- `normalize_whitespace` -- Free-text fields with inconsistent spacing.

---

### Phonetic Features

UDF-based phonetic encoding functions.

Source: `src/bq_entity_resolution/features/phonetic_features.py`

| Function | Inputs | Params | Output Type | Description |
|----------|--------|--------|-------------|-------------|
| `metaphone` | 1 | `udf_dataset` | STRING | Compute Metaphone phonetic code via a BigQuery JS UDF. Requires deploying a `metaphone(STRING) -> STRING` UDF to the specified dataset. |

**When to use phonetic features:**

- `metaphone` -- When Soundex is too coarse for your name matching needs. Metaphone produces more discriminating codes. Requires a JS UDF deployment step.

**Note:** For most use cases, the built-in `soundex` function (no UDF required) is sufficient. Use `metaphone` only when you need finer phonetic discrimination.

---

### Zip Features

Functions for postal/zip code normalization.

Source: `src/bq_entity_resolution/features/zip_features.py`

| Function | Inputs | Params | Output Type | Description |
|----------|--------|--------|-------------|-------------|
| `zip5` | 1 | -- | STRING (5 chars) | Extract first 5 digits of a zip/postal code. Strips non-digit characters first. |
| `zip3` | 1 | -- | STRING (3 chars) | Extract first 3 digits of a zip code (SCF/Sectional Center Facility area). Coarser geographic grouping. |

**When to use zip features:**

- `zip5` -- Standard zip code normalization. Use for exact zip matching or as a blocking key.
- `zip3` -- Broader geographic blocking. Groups records by the first 3 digits, which covers a larger geographic area than zip5. Good for blocking when addresses may have zip code errors.

**Example:**

```yaml
feature_engineering:
  zip_features:
    features:
      - name: zip_clean
        function: zip5
        input: zip_code
      - name: zip_prefix
        function: zip3
        input: zip_code
  blocking_keys:
    - name: bk_zip3
      function: farm_fingerprint
      inputs: [zip_prefix]
```

---

### Industry Features

Specialized normalization and validation for identifiers in insurance, banking, healthcare, and general business domains.

Source: `src/bq_entity_resolution/features/industry_features.py`

#### Insurance / Automotive

| Function | Inputs | Params | Output Type | Description |
|----------|--------|--------|-------------|-------------|
| `vin_normalize` | 1 | -- | STRING (17 chars) | Normalize Vehicle Identification Number. Removes non-alphanumeric chars, uppercases, corrects OCR errors (O to 0, I to 1, Q to 0 per VIN spec). |
| `vin_last_six` | 1 | -- | STRING (6 chars) | Extract last 6 characters of VIN (serial number portion). Unique within a manufacturer/year/plant combination. Useful for blocking. |
| `policy_number_clean` | 1 | -- | STRING | Clean insurance policy number. Strips whitespace, dashes, leading zeros, uppercases. "POL-123-456" becomes "POL123456". |

#### Banking / Financial

| Function | Inputs | Params | Output Type | Description |
|----------|--------|--------|-------------|-------------|
| `iban_normalize` | 1 | -- | STRING | Normalize International Bank Account Number. Removes spaces and dashes, uppercases. Standard IBAN is 15-34 chars. |
| `routing_number_clean` | 1 | -- | STRING (9 digits) | Clean US bank routing number (ABA RTN). Strips non-digits. |
| `account_number_clean` | 1 | -- | STRING | Clean bank account number. Strips spaces, dashes, leading zeros. |
| `amount_bucket` | 1 | `bucket_size` (default: 100) | INT64 | Bucket a monetary amount into fixed ranges for blocking. $150.50 with bucket_size=100 becomes 100. |

#### Healthcare

| Function | Inputs | Params | Output Type | Description |
|----------|--------|--------|-------------|-------------|
| `npi_validate` | 1 | -- | STRING (10 digits) or NULL | Validate and clean National Provider Identifier. Strips non-digits, returns NULL if not exactly 10 digits. |
| `dea_number_clean` | 1 | -- | STRING | Clean DEA registration number. Uppercases and strips whitespace/dashes. Standard format: 2 letters + 7 digits. |
| `mrn_clean` | 1 | -- | STRING | Clean Medical Record Number. Strips non-alphanumeric chars and leading zeros. |
| `icd_code_normalize` | 1 | -- | STRING | Normalize ICD-10 diagnosis code. Removes dots, uppercases. "M54.5" becomes "M545". |

#### General Business

| Function | Inputs | Params | Output Type | Description |
|----------|--------|--------|-------------|-------------|
| `ein_format` | 1 | -- | STRING (9 digits) | Clean Employer Identification Number. Strips dashes and non-digits. |
| `duns_clean` | 1 | -- | STRING (9 digits) or NULL | Clean D-U-N-S number. Strips dashes/spaces, returns NULL if not exactly 9 digits. |
| `ticker_normalize` | 1 | -- | STRING | Normalize stock ticker symbol. Uppercases, strips whitespace/dots. "brk.b" becomes "BRKB". |
| `cusip_clean` | 1 | -- | STRING (9 chars) | Clean CUSIP security identifier. Strips spaces, uppercases. |
| `license_number_clean` | 1 | -- | STRING | Clean driver's license or professional license number. Strips non-alphanumeric chars, uppercases. |

**When to use industry features:**

- **Insurance:** `vin_normalize` + `vin_last_six` for auto claims matching. `policy_number_clean` for cross-system policy dedup.
- **Banking:** `iban_normalize` for international KYC. `amount_bucket` for blocking on approximate transaction amounts.
- **Healthcare:** `npi_validate` for provider matching. `mrn_clean` for patient dedup across facilities. `icd_code_normalize` for claims matching.
- **Business:** `ein_format` for corporate entity resolution. `duns_clean` for B2B matching.

**Example: Insurance pipeline**

```yaml
feature_engineering:
  industry_features:
    features:
      - name: vin_clean
        function: vin_normalize
        input: vin
      - name: vin_serial
        function: vin_last_six
        input: vin
      - name: policy_clean
        function: policy_number_clean
        input: policy_number
  blocking_keys:
    - name: bk_vin_serial
      function: farm_fingerprint
      inputs: [vin_serial]
    - name: bk_policy
      function: farm_fingerprint
      inputs: [policy_clean]
```

---

## Comparison Methods

Comparison methods are referenced in YAML config under `matching_tiers[].comparisons`. Each evaluates a pair of candidate records and returns either a boolean (match/no-match) or a continuous score (0.0 to 1.0).

### YAML Pattern

```yaml
matching_tiers:
  - name: exact
    comparisons:
      - left: email_clean            # Left column (from featured table)
        right: email_clean           # Right column (from featured table)
        method: exact                # Method from this catalog
        weight: 5.0                  # Score contribution when match is TRUE
      - left: first_name_clean
        right: first_name_clean
        method: levenshtein
        weight: 3.0
        params:                      # Method-specific parameters
          max_distance: 2
    threshold:
      min_score: 8.0
```

### Boolean vs Score Methods

- **Boolean methods** (e.g., `exact`, `levenshtein`, `jaro_winkler`) return TRUE/FALSE. When TRUE, the comparison contributes its `weight` to the total score.
- **Score methods** (e.g., `levenshtein_score`, `cosine_similarity_score`) return a continuous value (0.0 to 1.0). The score is multiplied by `weight` to get the contribution. Use these for probabilistic matching pipelines.

---

### String Comparisons

Source: `src/bq_entity_resolution/matching/comparisons/string_comparisons.py`

#### Exact Matching

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `exact` | -- | 1 | boolean | Exact equality, both non-null. The cheapest comparison. On INT64 columns (fingerprints), this is a single 8-byte comparison. |
| `exact_case_insensitive` | -- | 2 | boolean | Case-insensitive exact equality. Applies UPPER() to both sides before comparing. |
| `exact_or_null` | -- | 1 | boolean | Match if equal OR if either value is null. Permissive -- use when missing data should not penalize. |

**When to use:**

- `exact` -- First choice for any deterministic match. For STRING columns, consider comparing pre-computed FARM_FINGERPRINT values instead (same semantics, 3-5x faster).
- `exact_case_insensitive` -- When source data has inconsistent casing and you have not pre-cleaned with `upper_trim` or `name_clean`.
- `exact_or_null` -- When a column is frequently null and you do not want null-vs-null to break an otherwise good match.

#### Edit Distance

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `levenshtein` | `max_distance` (default: 2) | 10 | boolean | Edit distance within threshold using BigQuery EDIT_DISTANCE. TRUE when distance <= max_distance. |
| `levenshtein_normalized` | `threshold` (default: 0.8) | 12 | boolean | Normalized edit distance similarity >= threshold. Computed as 1 - (distance / max_length). |
| `levenshtein_score` | -- | 12 | score (0.0-1.0) | Normalized edit distance similarity as a continuous score. |

**When to use:**

- `levenshtein` -- Typo tolerance for short strings (names, IDs). `max_distance: 1` catches single-character typos; `max_distance: 2` catches transpositions and double typos.
- `levenshtein_normalized` -- Better than raw Levenshtein for comparing strings of different lengths. A distance of 2 on a 5-character name is worse than distance 2 on a 20-character address.
- `levenshtein_score` -- Probabilistic pipelines where you want the similarity to contribute proportionally to the match score.

**Performance tip:** Place `length_mismatch` (cost: 2) before `levenshtein` (cost: 10) as a hard negative. If string lengths differ by more than `max_distance`, edit distance is guaranteed to exceed the threshold.

#### Jaro-Winkler

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `jaro_winkler` | `threshold` (default: 0.85), `udf_dataset` | 20 | boolean | Jaro-Winkler similarity >= threshold. Requires BigQuery JS UDF. Gives extra weight to matching prefixes. |
| `jaro_winkler_score` | `udf_dataset` | 20 | score (0.0-1.0) | Jaro-Winkler similarity as a continuous score. |

**When to use:**

- `jaro_winkler` -- Gold standard for name matching. Better than Levenshtein for short names because it weights prefix matches. "MARTHA" vs "MARHTA" scores higher than with edit distance.
- `jaro_winkler_score` -- Probabilistic pipelines for name similarity.

**Performance warning:** Requires a JS UDF, making it 20-50x slower than native functions. Use only in later tiers (fuzzy matching), never in tier 1. Consider `levenshtein_normalized` (cost: 12) as a native alternative.

#### Phonetic Matching

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `soundex_match` | -- | 3 | boolean | Soundex codes match. Catches phonetic equivalents ("Smith"/"Smyth", "Meyer"/"Myer"). |
| `metaphone_match` | `udf_dataset` | 15 | boolean | Metaphone codes match. Finer phonetic discrimination than Soundex. Requires JS UDF. |
| `double_metaphone_match` | `udf_dataset` | 15 | boolean | Double Metaphone: primary or alternate codes overlap. Handles names with multiple valid pronunciations. Requires two JS UDFs. |

**When to use:**

- `soundex_match` -- First choice for phonetic comparison. Native BigQuery function, no UDF needed. Good for common name spelling variations.
- `metaphone_match` -- When Soundex is too coarse (too many false positives). Metaphone produces more specific codes.
- `double_metaphone_match` -- When names have multiple valid pronunciations (e.g., European names in English contexts).

**Optimization tip:** If you already compute `soundex` as a feature column, use `exact` on that column (cost: 1) instead of `soundex_match` (cost: 3) which recomputes per pair.

#### String Containment

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `contains` | -- | 5 | boolean | Left value contains right value, or vice versa. Bidirectional substring check. |
| `starts_with` | -- | 5 | boolean | Left value starts with right value. Prefix matching. |
| `abbreviation_match` | -- | 5 | boolean | Either value is a prefix of the other. "J" matches "JAMES", "ROBT" matches "ROBERT". |

**When to use:**

- `contains` -- When one record may have a longer form of a name or identifier.
- `starts_with` -- When values share a common prefix but may have different suffixes.
- `abbreviation_match` -- First name matching where some records use abbreviations or initials. Common in insurance data where "J" represents "JAMES".

#### Token-Based Matching

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `token_set_match` | `min_overlap` (default: 0.5) | 30 | boolean | Token overlap ratio (Jaccard similarity of word tokens) >= threshold. Handles word transpositions. |
| `token_set_score` | -- | 30 | score (0.0-1.0) | Token overlap ratio as a continuous score. |
| `initials_match` | -- | 15 | boolean | Initials of two names match. "J.S." matches "John Smith" when both produce "JS". |

**When to use:**

- `token_set_match` -- Multi-word name matching where word order varies. "John Michael Smith" matches "Smith, John Michael". For simple first/last transpositions, `sorted_name_fingerprint` + `exact` is 30x cheaper.
- `initials_match` -- When some records have full names and others have only initials.

---

### Numeric Comparisons

Source: `src/bq_entity_resolution/matching/comparisons/numeric_comparisons.py`

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `numeric_within` | `tolerance` (default: 0) | 1 | boolean | Absolute difference within tolerance. `ABS(left - right) <= tolerance`. |
| `numeric_ratio` | `min_ratio` (default: 0.9) | 2 | boolean | Ratio of smaller to larger >= min_ratio. `MIN(a,b)/MAX(a,b) >= 0.9`. |
| `numeric_ratio_score` | -- | 2 | score (0.0-1.0) | Numeric ratio as continuous score. Returns smaller/larger, or 0 if null/zero. |
| `numeric_percent_diff` | `tolerance` (default: 5.0) | 2 | boolean | Percentage difference within tolerance. E.g., tolerance=5.0 means values within 5% of each other. |

**When to use:**

- `numeric_within` -- Dollar amounts, ages, counts where absolute difference matters. Premium within $50, age within 2 years.
- `numeric_ratio` -- Financial amounts where proportional closeness matters regardless of magnitude. $1000 vs $1050 and $100 vs $105 are both within 5%.
- `numeric_ratio_score` -- Probabilistic scoring where proportional similarity contributes continuously.
- `numeric_percent_diff` -- Similar to `numeric_ratio` but expressed as percentage tolerance, which is more intuitive for business users.

**Example:**

```yaml
comparisons:
  - left: premium_amount
    right: premium_amount
    method: numeric_within
    weight: 2.0
    params:
      tolerance: 50
  - left: claim_amount
    right: claim_amount
    method: numeric_ratio
    weight: 3.0
    params:
      min_ratio: 0.95
```

---

### Date Comparisons

Source: `src/bq_entity_resolution/matching/comparisons/date_comparisons.py`

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `date_within_days` | `days` (default: 0) | 1 | boolean | Date values within N days. Uses DATE_DIFF. |
| `date_within_months` | `months` (default: 0) | 1 | boolean | Date values within N months. |
| `date_within_years` | `years` (default: 0) | 1 | boolean | Date values within N years. |
| `age_difference` | `max_diff` (default: 2) | 2 | boolean | Ages derived from DOB columns differ by at most N years. More robust than exact DOB matching when DOB has entry errors. |
| `date_overlap` | `left_end`, `right_end` | 2 | boolean | Two date ranges intersect. Checks: left_start <= right_end AND left_end >= right_start. |
| `date_overlap_score` | `left_end`, `right_end` | 3 | score (0.0-1.0) | Temporal overlap ratio. Returns overlap_days / min_period_days. Score of 1.0 means one period is entirely contained within the other. |

**When to use:**

- `date_within_days` -- DOB matching with day-level tolerance (typos, data entry lag).
- `date_within_months` -- Approximate date matching at month granularity (policy inception dates).
- `date_within_years` -- Coarse temporal matching (decade-level grouping).
- `age_difference` -- Person matching where DOB may have errors but age should be approximately the same.
- `date_overlap` -- Insurance policy period overlap, employment date overlap, coverage intersection.
- `date_overlap_score` -- Probabilistic scoring based on degree of temporal overlap.

**Example: Date range overlap**

```yaml
comparisons:
  - left: policy_start_date
    right: policy_start_date
    method: date_overlap
    weight: 4.0
    params:
      left_end: policy_end_date
      right_end: policy_end_date
```

---

### Geo Comparisons

Source: `src/bq_entity_resolution/matching/comparisons/geo_comparisons.py`

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `geo_within_km` | `max_km` (default: 10.0), `left_lon`, `right_lon` | 25 | boolean | Two lat/lon points are within max_km kilometers. Uses BigQuery ST_DISTANCE for geodesic accuracy. |
| `geo_distance_score` | `max_km` (default: 50.0), `left_lon`, `right_lon` | 25 | score (0.0-1.0) | Proximity score based on distance. Score = 1 - (distance_km / max_km), clamped to [0, 1]. |

**When to use:**

- `geo_within_km` -- Boolean proximity check. "Are these two locations within 10 km?"
- `geo_distance_score` -- Continuous scoring where closer locations contribute higher scores.

**Important:** Always use `geo_hash` or `lat_lon_bucket` blocking to pre-filter candidates before running geo comparisons. ST_DISTANCE involves trigonometric calculations and is expensive at scale.

**Example:**

```yaml
comparisons:
  - left: latitude
    right: latitude
    method: geo_within_km
    weight: 2.0
    params:
      max_km: 5.0
      left_lon: longitude
      right_lon: longitude
```

---

### Null and Hard-Negative Comparisons

Utility comparisons for null handling and pair disqualification.

Source: `src/bq_entity_resolution/matching/comparisons/null_comparisons.py`

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `different` | -- | 1 | boolean | Returns TRUE when values differ (both non-null). Use with negative weight to penalize mismatches. |
| `null_either` | -- | 1 | boolean | Returns TRUE when either value is null. Use to detect missing data. |
| `length_mismatch` | `max_diff` (default: 5) | 2 | boolean | Returns TRUE when string lengths differ by more than threshold. Use as a cheap pre-filter before expensive comparisons. |

**When to use:**

- `different` -- Hard negative with negative weight. If SSN values are different, penalize the pair. This is the primary mechanism for disqualifying clearly non-matching pairs.
- `null_either` -- Data quality tracking. Can also be used with small negative weight to penalize incomplete records.
- `length_mismatch` -- Pre-filter for expensive comparisons. If name lengths differ by 5+ characters, edit distance is likely to exceed any reasonable threshold. Place this comparison before `levenshtein` or `jaro_winkler` in the comparison list.

**Example: Hard negatives**

```yaml
comparisons:
  - left: ssn_clean
    right: ssn_clean
    method: different
    weight: -10.0          # Strong penalty for SSN mismatch
  - left: first_name_clean
    right: first_name_clean
    method: length_mismatch
    weight: -2.0
    params:
      max_diff: 5
```

---

### Composite and Vector Comparisons

Embedding/vector similarity and pattern-based comparisons.

Source: `src/bq_entity_resolution/matching/comparisons/composite_comparisons.py`

#### Cosine Similarity

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `cosine_similarity` | `min_similarity` (default: 0.85) | 50 | boolean | Cosine similarity >= threshold using ML.DISTANCE. Best for text embeddings where direction matters, not magnitude. |
| `cosine_similarity_score` | -- | 50 | score (0.0-1.0) | Cosine similarity as continuous score (1 - cosine_distance). |

#### Euclidean Distance

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `euclidean_distance` | `max_distance` (default: 1.0) | 50 | boolean | Euclidean (L2) distance <= threshold. Sensitive to magnitude and scale. |
| `euclidean_distance_score` | `max_distance` (default: 10.0) | 50 | score (0.0-1.0) | Euclidean distance as similarity score. Returns 1 - (distance / max_distance), clamped to [0, 1]. |

#### Manhattan Distance

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `manhattan_distance` | `max_distance` (default: 1.0) | 45 | boolean | Manhattan (L1) distance <= threshold. More robust than Euclidean when individual dimensions have different scales. |
| `manhattan_distance_score` | `max_distance` (default: 10.0) | 45 | score (0.0-1.0) | Manhattan distance as similarity score. Returns 1 - (distance / max_distance), clamped to [0, 1]. |

#### Character N-Gram

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `jaccard_ngram` | `n` (default: 2), `min_similarity` (default: 0.5) | 15 | boolean | Character n-gram Jaccard similarity >= threshold. Splits strings into n-grams, computes intersection/union. |
| `jaccard_ngram_score` | `n` (default: 2) | 15 | score (0.0-1.0) | Character n-gram Jaccard similarity as continuous score. |

#### Regex

| Method | Params | Cost | Returns | Description |
|--------|--------|------|---------|-------------|
| `regex_match` | `pattern` (default: `.*`) | 5 | boolean | Both values match a given regex pattern. Validates that both sides conform to an expected format. |

**When to use:**

- `cosine_similarity` -- Text embeddings from BQML or external models. Standard choice for semantic matching of names, addresses, or free text.
- `euclidean_distance` -- Coordinate-based or spatial embeddings where magnitude matters. Normalize inputs first.
- `manhattan_distance` -- When individual embedding dimensions have different scales and you do not want outlier dimensions to dominate.
- `jaccard_ngram` -- Typo-tolerant matching where character patterns matter more than positions. Good for addresses and company names. N=2 (bigrams) is the standard default; N=3 (trigrams) is more specific.
- `regex_match` -- Validate that both records have a properly formatted identifier before comparing. Useful for VINs, policy numbers, SSNs.

**Performance warning:** Vector similarity methods (cosine, euclidean, manhattan) are the most expensive comparisons. Use LSH bucket blocking to pre-filter candidates to under 1M pairs before running these.

---

## Cost Tiers

All comparison methods have a relative cost score. Lower cost means faster execution per candidate pair. At scale, cost differences are amplified by the number of candidate pairs.

| Tier | Cost | Methods | Notes |
|------|------|---------|-------|
| 1 -- Trivial | 1-2 | `exact`, `exact_or_null`, `different`, `null_either`, `numeric_within`, `date_within_days`, `date_within_months`, `date_within_years`, `exact_case_insensitive`, `numeric_ratio`, `numeric_ratio_score`, `numeric_percent_diff`, `age_difference`, `length_mismatch`, `date_overlap` | Fixed-width arithmetic. INT64/DATE comparisons. |
| 2 -- Simple String | 3-5 | `soundex_match`, `date_overlap_score`, `starts_with`, `contains`, `abbreviation_match`, `regex_match` | O(n) string operations. |
| 3 -- Edit Distance | 10-15 | `levenshtein`, `levenshtein_normalized`, `levenshtein_score`, `initials_match`, `metaphone_match`, `double_metaphone_match`, `jaccard_ngram`, `jaccard_ngram_score` | O(n*m) or correlated subqueries. |
| 4 -- JS UDF | 20 | `jaro_winkler`, `jaro_winkler_score` | V8 JS engine serialization overhead. |
| 5 -- Complex | 25-50 | `geo_within_km`, `geo_distance_score`, `token_set_match`, `token_set_score`, `manhattan_distance`, `manhattan_distance_score`, `cosine_similarity`, `cosine_similarity_score`, `euclidean_distance`, `euclidean_distance_score` | Geodesic math, ML.DISTANCE, correlated subqueries. |

**Optimization strategy:** Order comparisons cheapest-first in your YAML config. BigQuery evaluates CASE WHEN chains left-to-right and can short-circuit when cheap comparisons already determine the outcome.

---

## Adding Custom Functions

Both feature functions and comparison methods use the `@register` decorator pattern. You can add your own functions in two ways.

### Custom Feature Function

```python
from typing import Any
from bq_entity_resolution.features.registry import register

@register("my_custom_feature")
def my_custom_feature(inputs: list[str], **_: Any) -> str:
    """Custom feature: uppercase and remove digits."""
    col = inputs[0]
    return f"REGEXP_REPLACE(UPPER({col}), r'[0-9]', '')"
```

Then use in YAML:

```yaml
feature_engineering:
  custom_features:
    features:
      - name: cleaned_value
        function: my_custom_feature
        input: raw_column
```

### Custom Comparison Method

```python
from typing import Any
from bq_entity_resolution.matching.comparisons import register

@register("my_similarity")
def my_similarity(left: str, right: str, threshold: float = 0.9, **_: Any) -> str:
    """Custom comparison: check if values are similar."""
    return (
        f"(my_dataset.my_udf(l.{left}, r.{right}) >= {threshold} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )
```

Then use in YAML:

```yaml
matching_tiers:
  - name: custom_tier
    comparisons:
      - left: cleaned_value
        right: cleaned_value
        method: my_similarity
        weight: 3.0
        params:
          threshold: 0.85
```

### Key Conventions

1. **Feature functions** receive `inputs: list[str]` (column names) and `**_: Any` (optional params from YAML `params:` block). They return a BigQuery SQL expression string.

2. **Comparison functions** receive `left: str` and `right: str` (column names) and `**_: Any` (optional params). They return a BigQuery SQL expression using `l.` and `r.` table aliases. Always include null checks.

3. **Always use `**_: Any`** as the last parameter for forward compatibility. The registry may pass additional keyword arguments in future versions.

4. **Null safety:** Feature functions should handle NULLs gracefully (use CASE WHEN or COALESCE). Comparison functions should return FALSE when inputs are null (unless the comparison is specifically null-aware like `exact_or_null`).

5. **Plugin entry points:** External packages can auto-register functions via `pyproject.toml`:

```toml
[project.entry-points."bq_er.features"]
my_pkg = "my_pkg.features"

[project.entry-points."bq_er.comparisons"]
my_pkg = "my_pkg.comparisons"
```

The module is imported automatically, triggering `@register` decorators.

---

## Quick Reference: Function Count Summary

| Category | Count |
|----------|-------|
| **Feature Functions** | |
| Name | 19 |
| Address | 4 |
| Contact | 6 |
| Date/Identity | 7 |
| Geo | 3 |
| Blocking Keys | 6 |
| Utility | 12 |
| Phonetic | 1 |
| Zip | 2 |
| Industry | 16 |
| **Total Feature Functions** | **76** |
| | |
| **Comparison Methods** | |
| String | 17 |
| Numeric | 4 |
| Date | 6 |
| Geo | 2 |
| Null/Hard-Negative | 3 |
| Composite/Vector | 9 |
| **Total Comparison Methods** | **41** |
| | |
| **Grand Total** | **117** |
