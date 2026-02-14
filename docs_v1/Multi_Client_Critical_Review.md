# Critical Review: Multi-Client Generalization of Healthcare Categorization CLI

**Reviewer**: Architecture Review
**Date**: 2026-02-14
**Scope**: Generalization of `categorization-cli` engine from CCHMC-only to multi-client
**Verdict**: **CONDITIONAL GO** (see Section 10)

---

## Executive Summary

The current engine (`src/categorize.py`, 614 lines) is a well-built, single-client tool. It achieves 99.7% Auto-Accept on CCHMC because CCHMC's data is exceptionally well-structured: 326 discrete SC codes cover 90.6% of 596,796 rows in Tier 1 alone. The remaining 9.4% is handled by 476 hand-written rules across Tiers 2-7.

UCH is the acid test for generalization, and it breaks every assumption the engine makes:

- **No SC codes**. The column "Category" contains exactly one value: "Facilities". Tier 1 is useless.
- **No Line Memo, Line of Service, or Cost Center**. Tiers 3, 4, and 5 are useless.
- **Only 11 columns vs. CCHMC's 46**. The engine requires all 6 column mappings; UCH can provide 2 (Supplier, amount).
- **Amount column has whitespace-padded name**: `'  Spend Amount  '` (two leading, two trailing spaces) and currency-formatted strings `"$5,567.76 "`.

The "skip unused tiers" approach will technically work but will produce poor classification quality (~40-60% Auto-Accept at best) because the engine has no mechanism to use UCH's actual discriminating columns: `Subcategory` (24 unique values that map cleanly to taxonomy), `Capex/Opex`, `SpendBand`, or `Location`.

The core issue is not "how to skip tiers" but "the 7-tier waterfall is the wrong abstraction for clients without SC codes."

---

## 1. Architectural Concerns

### 1.1 The Waterfall is CCHMC-Shaped

**Severity**: Critical

The 7-tier waterfall was designed around CCHMC's data richness. Five of seven tiers require SC codes as a prerequisite:

| Tier | SC Code Dependency | UCH Usable? |
|------|-------------------|-------------|
| Tier 1: SC Code Mapping | Direct SC lookup | No (no SC codes) |
| Tier 2: Supplier Refinement | `sc_code.isin(rule['sc_codes'])` | No (no SC codes) |
| Tier 3: Keyword Rules | Matches `supplier + line_memo` | Partially (no line_memo, matches supplier only) |
| Tier 4: Context Refinement | `sc_code.isin(rule['sc_codes'])` + LoS | No (no SC codes, no LoS) |
| Tier 5: Cost Center Refinement | `sc_code.isin(rule['sc_codes'])` + CC | No (no SC codes, no CC) |
| Tier 6: Ambiguous Fallback | Maps ambiguous SC codes | No (no SC codes) |
| Tier 7: Supplier Override | Checks `cat_l1` from prior tiers | Partially (depends on prior tiers producing results) |

UCH has exactly **one reliable classification signal**: Supplier name. And one excellent signal the engine cannot use: Subcategory (24 clean, taxonomy-aligned labels).

Code reference: `categorize.py` lines 277-380 -- every tier except 3 and 7 filters on `sc_code`.

**Recommendation**: The waterfall needs to be reframed as a **pluggable pipeline** where each tier is an optional step configured per client. The current design hardcodes the 7-tier sequence in `main()` as inline code blocks -- there is no tier abstraction, no tier interface, no way to add/remove/reorder tiers without editing the engine.

**Decision required**: Is the team willing to refactor `main()` from a monolithic function to a pipeline of composable tier functions? This is the difference between a multi-client architecture and a multi-client hack.

### 1.2 No Tier Abstraction Exists

**Severity**: Critical

Each tier is an inline code block in `main()` (lines 277-421). There is no `Tier` class, no `classify_tier_1()` function, no registration mechanism. Adding a new tier type (e.g., "Subcategory Mapping" for UCH) requires editing the monolithic `main()` function.

For UCH, you need at minimum a new tier that does:
```
Subcategory value -> taxonomy key lookup (deterministic, like Tier 1 but on a different column)
```

This is conceptually identical to Tier 1 but operating on a different column. The engine has no mechanism to parameterize which column feeds the lookup.

Code reference: `categorize.py` lines 277-284 -- Tier 1 is hardcoded to use `sc_code` (derived from `cols['spend_category']` via regex extraction).

**Recommendation**: Extract each tier into a function with a common signature: `(df, unclassified_mask, config, resources) -> (taxonomy_key, method, confidence, classified_mask)`. Register tiers in config:
```yaml
pipeline:
  - tier: category_code_mapping
    column: spend_category
    pattern: '((?:DNU\s+)?SC\d+)'
  - tier: supplier_refinement
  - tier: keyword_rules
  - tier: subcategory_mapping    # NEW: for UCH
    column: Subcategory
    mapping_file: subcategory_mapping.yaml
```

**Decision required**: Accept the refactoring cost now, or accumulate tech debt with each new client.

### 1.3 Client #3 Will Break It Again

**Severity**: High

Consider these realistic client scenarios:

- **Client with SAP Material Groups**: Numeric codes (e.g., `47110000`), no regex extraction needed, direct string match. The `sc_code_pattern` regex extraction step (line 262) will fail or extract garbage.
- **Client with free-text descriptions only**: No codes, no subcategories, just a "Description" column. No existing tier handles this. You need NLP/embedding-based classification or exhaustive keyword rules.
- **Client with multiple category systems**: Both a department code and a commodity code. The engine can only map one `spend_category` column.

Each of these requires a different pipeline composition. The "skip unused tiers" approach means the engine degrades to supplier-only matching for every non-CCHMC-shaped client.

**Recommendation**: Design the tier system to be additive. New tier types should be implementable as plugins without modifying core engine code.

---

## 2. Data Model Gaps

### 2.1 UCH "Category" is Not Analogous to CCHMC SC Codes

**Severity**: Critical

The task description frames UCH's "Category" as a potential Tier 1 input. The data proves this is meaningless:

```
Category value_counts():
  Facilities    3092  (100%)
```

Every single row has `Category = "Facilities"`. This column has zero discriminative power. Mapping it in Tier 1 would assign all 3,092 rows to the same taxonomy key.

CCHMC's SC codes have 326 unique values, each mapping to a specific taxonomy path. UCH's "Category" has 1 value.

**However**, UCH's `Subcategory` column has 24 unique values that map almost perfectly to Healthcare Taxonomy v2.9 paths under `Facilities >`:

| UCH Subcategory | Probable Taxonomy Key |
|----------------|----------------------|
| Electrical Services | Facilities > Facilities Services > Building Maintenance > Electrical Services |
| HVAC Installation & Maintenance | Facilities > Facilities Services > Building Maintenance > HVAC Installation & Maintenance |
| Plumbing Maintenance | Facilities > Facilities Services > Building Maintenance > Plumbing Maintenance |
| Janitorial Services | Facilities > Cleaning > Cleaning Services > Janitorial Services |

This is the UCH equivalent of Tier 1 -- but the engine has no concept of "Subcategory mapping." The `sc_code_mapping` loader (`load_sc_mapping`, line 81) expects a YAML file keyed by SC code strings with a specific schema. UCH would need a YAML file keyed by subcategory strings.

Code reference: `categorize.py` lines 81-94 -- `load_sc_mapping()` iterates `data.get('mappings', {}).items()` and stores by SC code key. This function is reusable for any string-keyed lookup, but it's called `load_sc_mapping` and the config key is `paths.sc_mapping`.

**Recommendation**: Rename the concept from "SC Code Mapping" to "Category Code Mapping" or "Primary Category Mapping." Accept any string key, not just SC code format. For UCH, the mapping YAML would be:
```yaml
mappings:
  "Electrical Services":
    name: Electrical Services
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance > Electrical Services"
    confidence: 0.95
  "HVAC Installation & Maintenance":
    name: HVAC
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance > HVAC Installation & Maintenance"
    confidence: 0.95
```

And the config would point `columns.spend_category` at `Subcategory` instead of `Category`, with `sc_code_pattern` set to `(.+)` (identity -- no extraction needed).

**Decision required**: Is this reframing acceptable, or does the team want a separate "subcategory mapping" tier?

### 2.2 The Amount Column Has Whitespace in Its Name

**Severity**: Medium

UCH's amount column is literally `'  Spend Amount  '` (two leading spaces, two trailing spaces). The current engine does no column name trimming. If a config specifies `amount: "Spend Amount"`, the column lookup will fail because `"Spend Amount" != "  Spend Amount  "`.

Code reference: `categorize.py` lines 237-251 -- column validation does exact string matching: `v not in df.columns`.

The engine currently does `pd.read_csv(paths['input'], low_memory=False)` (line 230) with no column stripping.

**Recommendation**: Add `df.columns = df.columns.str.strip()` after `pd.read_csv()`. This is a one-line fix that prevents a class of onboarding friction.

**Decision required**: None -- just do it.

### 2.3 Amount Parsing Will Fail

**Severity**: High

UCH's amount values are currency-formatted strings: `"$5,567.76 "`. The engine does `results_df[amount_col].sum()` (line 534) and `results_df[amount_col].mean()` (line 535) which will fail on string columns.

CCHMC's `Invoice Line Amount` column is numeric (pandas reads it as float64). UCH's `  Spend Amount  ` is a string because of the `$` and `,` characters.

The engine has no amount parsing/cleaning step. It assumes the amount column is already numeric.

Code reference: `categorize.py` lines 534-535 -- `results_df[amount_col].sum()` and `.mean()` with no type checking or conversion.

**Recommendation**: Add an amount cleaning step after CSV load:
```python
amount_series = df[cols['amount']]
if amount_series.dtype == object:
    amount_series = amount_series.str.replace(r'[\$,\s()]', '', regex=True).astype(float)
    df[cols['amount']] = amount_series
```

Handle parentheses for negatives: `"(5,567.76)"` -> `-5567.76`. UCH has no negatives today (confirmed: all 3,092 amounts are positive, range $1.59 to $534,700.00), but this is a time bomb for future clients.

**Decision required**: Define the amount cleaning contract. What formats does the engine support? Just `$1,234.56`? Also `(1,234.56)` for negatives? European format `1.234,56`?

### 2.4 UCH Has Useful Columns the Engine Cannot Leverage

**Severity**: High

UCH provides columns the engine ignores because they don't map to any of the 6 required column slots:

| Column | Values | Classification Utility |
|--------|--------|----------------------|
| `Capex/Opex` | Always "OPEX" for this dataset | Could distinguish capital purchases from operating expenses (useful for future UCH data with mixed types) |
| `SpendBand` | 9 bands from "0 - 1K" to "500K - 1M" | Could weight confidence or flag high-value items for manual review |
| `SuppliersFlag` | Always "No" | Unclear purpose, but likely indicates strategic vs. non-strategic suppliers |
| `Location` | Always "Cincinnati" | Multi-location clients would need location-based rules |
| `Category Type` | Always "In Scope" | Would filter out-of-scope rows pre-classification |

The engine's config schema has exactly 6 column slots (`spend_category`, `supplier`, `line_memo`, `line_of_service`, `cost_center`, `amount`). There is no mechanism to declare additional classification-relevant columns or use them in rules.

Code reference: `categorize.py` lines 51-54 -- `required_columns` is a fixed list. The `passthrough` mechanism (line 442-444) carries extra columns into output but does not use them for classification.

**Recommendation**: Add an `extra_classification_columns` config section that declares additional columns available for rule matching. Rules could reference arbitrary columns:
```yaml
supplier_rules:
  - columns_match:
      spend_category: ["Facilities"]
      capex_opex: ["CAPEX"]
    supplier_pattern: "..."
    taxonomy_key: "..."
```

This is a significant design expansion. Defer to v2 unless a concrete client need justifies it now.

---

## 3. Classification Quality Concerns

### 3.1 UCH Will Not Achieve 99% Auto-Accept

**Severity**: High

CCHMC's 99.7% AA rate is built on:
- 326 SC code mappings covering 90.6% of rows in Tier 1
- 237 supplier refinement rules covering 6.0% in Tier 2
- 220 keyword rules covering 1.1% in Tier 3
- Total: 783 rules for 596,796 rows

UCH has:
- 0 SC codes (Tier 1 useless)
- 180 unique suppliers
- 24 subcategories (not usable by current engine)
- 3,092 rows

If Subcategory mapping is implemented (Section 2.1), UCH could achieve **near-100% classification in a single tier** because every row has a non-null Subcategory value and there are only 24 unique values. The mapping effort would take under 30 minutes.

If Subcategory mapping is NOT implemented, UCH falls back to supplier-only classification. With 180 unique suppliers, writing supplier rules for the top 20 (covering ~60% of rows per the data) is feasible but covers only 60% of transactions. The remaining 40% across 160 suppliers would require either exhaustive rule-writing or falling through to "Unclassified."

**Realistic projection without Subcategory mapping**: 50-70% Auto-Accept.
**Realistic projection with Subcategory mapping**: 95-100% Auto-Accept.

The difference is a design decision, not a rule-writing problem.

**Recommendation**: Implement Subcategory mapping (Section 2.1). Without it, UCH's classification quality makes the tool unsuitable for client delivery.

### 3.2 Keyword Rules Without Line Memo Are Low-Precision

**Severity**: Medium

Keyword rules (Tier 3) match against `combined_text = supplier + ' ' + line_memo` (line 271). For UCH, `line_memo` does not exist, so `combined_text` is just the supplier name.

CCHMC's keyword rules were designed to match phrases like "fire alarm" or "hvac" in line memo descriptions. On supplier-name-only text, these patterns will:
- **False positive**: A supplier named "FIRE & SAFETY SOLUTIONS" would match the `fire alarm|fire protection` rule, even if the transaction is for safety training, not fire alarm equipment.
- **Miss entirely**: Most supplier names don't contain the descriptive keywords the rules target.

The keyword rules file has 220 rules (confirmed by reading `keyword_rules.yaml`). Most patterns like `hvac|air condition|heating|cooling` are description-oriented, not supplier-name-oriented.

Code reference: `categorize.py` line 271 -- `combined_text = supplier + ' ' + line_memo`. If `line_memo` is all empty strings (which it will be for UCH since the column won't exist), `combined_text` degrades to supplier name only.

**Recommendation**: For clients without line_memo, warn in console output that Tier 3 keyword rules will have degraded precision. Consider a config flag `keyword_rules_enabled: false` to skip Tier 3 entirely for these clients rather than producing low-confidence matches.

### 3.3 Amazon Web Services is 12.4% of UCH Rows

**Severity**: Medium

`AMAZON WEB SERVICES INC` has 383 rows out of 3,092 (12.4%). In a Facilities-scoped dataset, AWS transactions are almost certainly cloud hosting or IT infrastructure -- not facilities maintenance. This is a data scoping issue, not a classification issue, but the engine needs to handle it correctly.

A single supplier rule for AWS -> `IT & Telecoms > Cloud Services` would correctly classify 12.4% of UCH's data. But this highlights a broader problem: UCH's data is pre-filtered to "Facilities" category, yet contains IT-related transactions. The engine needs to handle cross-category suppliers without relying on SC codes to disambiguate.

In CCHMC's engine, AWS under `SC0250` would be caught by Tier 2 supplier refinement. In UCH, there is no SC code to scope the rule.

**Recommendation**: For UCH, supplier rules need to work WITHOUT sc_codes scoping. The current `supplier_rules` schema requires `sc_codes` as a mandatory field. A client without SC codes cannot use Tier 2 at all.

---

## 4. Config Complexity

### 4.1 All 6 Columns Are Required, But UCH Has Only 2

**Severity**: Critical

The config validation (lines 51-54) requires all 6 column mappings:
```python
required_columns = ['spend_category', 'supplier', 'line_memo', 'line_of_service', 'cost_center', 'amount']
```

UCH's CSV has 11 columns. Of the 6 required mappings:
- `spend_category`: Could map to `Subcategory` (not `Category` -- `Category` is useless)
- `supplier`: Maps to `Supplier`
- `line_memo`: **Does not exist**
- `line_of_service`: **Does not exist**
- `cost_center`: **Does not exist**
- `amount`: Maps to `  Spend Amount  ` (with whitespace)

The engine crashes if any of these are missing from the CSV (line 248-251):
```python
missing_csv_cols = [
    f"'{v}' (from columns.{k})"
    for k, v in required_csv_cols.items()
    if v not in df.columns
]
if missing_csv_cols:
    raise ConfigError(f"Columns not found in input CSV: {', '.join(missing_csv_cols)}")
```

**Workaround (ugly)**: UCH could set `line_memo: "Supplier"`, `line_of_service: "Category"`, `cost_center: "Category"` -- mapping missing columns to existing ones. The engine would technically run, but Tier 4 (LoS refinement) and Tier 5 (CC refinement) would match on nonsensical data.

**Recommendation**: Make `line_memo`, `line_of_service`, and `cost_center` optional in config. If omitted, the engine:
1. Skips the column existence check for that field
2. Fills the internal series with empty strings
3. Skips tiers that require the missing column
4. Logs a warning: `"Column mapping 'line_memo' not configured -- Tier 3 keyword rules will match on supplier name only"`

This requires changing `required_columns` to distinguish between truly-required (`spend_category`, `supplier`, `amount`) and optional-but-useful (`line_memo`, `line_of_service`, `cost_center`).

Code changes needed:
- `load_config()` lines 51-54: Split required vs. optional columns
- `main()` lines 261-271: Guard optional column access
- `main()` lines 328-370: Skip Tier 4/5 if LoS/CC columns not configured
- Output builder lines 446-451: Omit missing columns from output

**Decision required**: Agree on which columns are truly required vs. optional.

### 4.2 `paths.sc_mapping` and `paths.refinement_rules` Are Required But May Be Empty

**Severity**: High

Config validation (lines 46-49) requires `sc_mapping` and `refinement_rules` paths. For UCH with Subcategory mapping, the `sc_mapping` file would contain subcategory-to-taxonomy mappings (reusing the same format). But `refinement_rules` has 4 hardcoded sections (`supplier_rules`, `context_rules`, `cost_center_rules`, `supplier_override_rules`), all of which require SC codes except `supplier_override_rules`.

If UCH provides an empty refinement_rules file, the engine handles it (lines 147-180 -- empty lists are fine). But the test suite (test_rules.py line 262-273) will fail:
```python
def test_rule_counts(self, refinement):
    assert len(refinement["supplier_rules"]) >= 230
    assert len(refinement["context_rules"]) >= 8
    assert len(refinement["cost_center_rules"]) >= 10
    assert len(refinement["supplier_override_rules"]) >= 11
```

These are CCHMC-specific minimums. Running tests with `--client-dir clients/uch` will fail immediately.

**Recommendation**: Remove `test_rule_counts` from the shared test suite. If minimum rule counts are important for a specific client, put them in a client-specific test file:
```
tests/
  test_rules.py           # Shared: structural, regex, taxonomy validation
  clients/
    cchmc/
      test_cchmc_rules.py  # CCHMC-specific: known mappings, rule counts
    uch/
      test_uch_rules.py    # UCH-specific: subcategory coverage, supplier rules
```

### 4.3 `classification.sc_code_pattern` is Required But Meaningless for UCH

**Severity**: High

Config validation (lines 56-59) requires `sc_code_pattern`:
```python
required_class = ['sc_code_pattern', 'confidence_high', 'confidence_medium']
```

UCH has no SC codes. The pattern would need to be set to something like `(.+)` to match the entire Subcategory value as-is. This is semantically wrong -- the field is named `sc_code_pattern` and the engine uses it for regex extraction (line 262):
```python
sc_extracted = spend_cat_str.str.extract(f'({sc_pattern})', expand=False)
```

For UCH with `Subcategory` mapped to `spend_category` and `sc_code_pattern: '(.+)'`, the engine would extract the full subcategory text ("Electrical Services") as the "SC code." This works mechanically but is misleading -- the output column is labeled "SC Code" (line 448) and the summary refers to "Unique SC Codes."

**Recommendation**: Rename the concept. The config key should be `category_extraction_pattern` or just `category_pattern`. The output column should be `Category Code` (not `SC Code`). The internal variable should be `category_code` (not `sc_code`).

Make `classification.sc_code_pattern` optional. If omitted, use the raw `spend_category` column value without regex extraction.

### 4.4 No Config Validation for Semantic Coherence

**Severity**: Medium

The engine validates structural requirements (sections exist, files exist, columns exist) but does not validate whether the config will produce meaningful results. A config with:
- `spend_category` pointing to a constant column
- No keyword rules
- No supplier rules
- No refinement rules

...will run without errors and classify 100% of rows into a single taxonomy key. The operator gets no warning that their config is degenerate.

**Recommendation**: Add a post-load diagnostic step that warns about:
- `spend_category` column with < 5 unique values (likely a constant or near-constant)
- All rule files are empty (engine will produce only Tier 1 results)
- `sc_code_pattern` regex matches < 50% of `spend_category` values (pattern may be wrong)
- No passthrough columns configured (output will be minimal)

---

## 5. Test Infrastructure Gaps

### 5.1 TestSCCodeValidity Assumes SC Codes Exist

**Severity**: High

`TestSCCodeValidity` (lines 133-154) validates that SC codes in refinement rules exist in the SC code mapping. For UCH, where the "SC mapping" file contains subcategory strings (not SC codes), these tests will check that rule `sc_codes` fields reference subcategory strings. This is semantically correct if UCH's refinement rules are written to use subcategory values as `sc_codes`.

But this creates a confusing contract: the `sc_codes` field in refinement rules isn't actually limited to SC codes -- it's "whatever keys are in the mapping file." The test name and assertion messages will be misleading.

**Recommendation**: Rename `valid_sc_codes` fixture to `valid_category_codes`. Update assertion messages to say "category code" instead of "SC code."

### 5.2 TestSupplierClassification is CCHMC-Only

**Severity**: High

`TestSupplierClassification.KNOWN_MAPPINGS` (lines 190-198) hardcodes 7 CCHMC-specific assertions:
```python
KNOWN_MAPPINGS = [
    ("SC0250", "epic systems", "IT & Telecoms > Software > Application Software"),
    ("SC0250", "kpmg", "Professional Services > Financial Services > ..."),
    ...
]
```

Running with `--client-dir clients/uch` will fail on all 7 because UCH has no SC0250 code and different suppliers.

This test class needs to be client-specific. The conftest `--client-dir` mechanism supports this, but the test file has CCHMC data hardcoded.

**Recommendation**: Move `KNOWN_MAPPINGS` to a per-client fixture file:
```yaml
# clients/cchmc/data/reference/test_assertions.yaml
known_mappings:
  - category_code: SC0250
    supplier: "epic systems"
    expected_taxonomy: "IT & Telecoms > Software > Application Software"
```

The conftest loads this file based on `--client-dir`. Tests skip gracefully if no assertion file exists for the client.

### 5.3 No Cross-Client Regression Test

**Severity**: High

When the engine is modified for UCH support, there is no automated way to verify CCHMC results are unchanged. The verification is manual: run CCHMC pipeline, check 594,807 AA / 1,989 QR.

A single engine change that benefits UCH could silently break CCHMC's classification. The review tier assignment logic (lines 424-429) is particularly fragile -- changing confidence thresholds or method-based overrides affects all clients.

**Recommendation**: Create a golden-output test for CCHMC:
```python
def test_cchmc_regression():
    """Engine changes must not alter CCHMC classification counts."""
    config = load_config("clients/cchmc/config.yaml")
    # Run classification (without Excel output for speed)
    results = classify(config)
    assert results['method_counts']['sc_code_mapping'] == 540491
    assert results['tier_counts']['Auto-Accept'] == 594807
    assert results['tier_counts']['Quick Review'] == 1989
```

This requires refactoring `main()` to return results before writing Excel, which is also needed for testability in general.

### 5.4 `test_rule_counts` is a Ticking Time Bomb

**Severity**: Medium

Lines 261-273 assert minimum rule counts:
```python
assert len(refinement["supplier_rules"]) >= 230
```

Every new client with fewer rules will fail this test. Every rule addition to CCHMC that brings the count past the asserted minimum will never be caught if rules are later removed (the assertion only checks `>=`, not `==`).

**Recommendation**: Delete this test from the shared suite. If rule count tracking matters, make it a per-client assertion with exact expected counts in the client's test config.

---

## 6. Operational Concerns

### 6.1 Client Onboarding Effort Estimation is Wrong

**Severity**: High

The PRD states "Estimated onboarding time per client: 2-4 hours (excluding rule tuning iterations)." This estimate is based on CCHMC, which had:
- Well-structured SC codes (just map them)
- Rich data columns (rules can be precise)
- Existing Workday category naming conventions

For UCH:
- Subcategory mapping: 24 values, ~30 minutes (if the engine supports it)
- Supplier rules for 180 unique suppliers: 4-8 hours (research each supplier's business domain)
- Amount parsing: requires engine code change
- Column whitespace handling: requires engine code change

The engine code changes alone (optional columns, amount parsing, Subcategory mapping tier) are 4-8 hours of development work that must happen BEFORE any UCH onboarding can begin.

**Recommendation**: Separate "engine development per client type" from "client onboarding time." The first client of a new data shape requires engine work. Subsequent clients with the same shape require only config + rules.

### 6.2 No Quality Prediction Before Rule-Writing

**Severity**: Medium

There is no way to estimate classification quality before investing in rule-writing. The operator starts writing rules blind and iterates.

For CCHMC, this was acceptable because Tier 1 covers 90.6% immediately. For UCH, the operator has no idea whether 50 supplier rules or 150 supplier rules are needed to reach the 95% AA target.

**Recommendation**: Add a `--dry-run` or `--profile` mode that:
1. Loads the CSV
2. Reports column cardinality (unique values per column)
3. Shows coverage projection per tier based on current rules
4. Estimates rows that will reach each review tier
5. Suggests which columns/suppliers to target for rule-writing

### 6.3 Taxonomy Versioning is Not Addressed

**Severity**: Medium

Healthcare Taxonomy v2.9 is a shared file at `shared/reference/Healthcare Taxonomy v2.9.xlsx`. When v3.0 arrives:
- All clients' `taxonomy_key` values in all YAML files may need updating
- The taxonomy file path is in every client's config
- There is no migration tool or validation that existing keys still resolve

**Recommendation**: Version-lock the taxonomy in each client config and build a taxonomy migration script:
```yaml
classification:
  taxonomy_version: "2.9"   # Explicit version tracking
```

### 6.4 No Incremental Processing

**Severity**: Low (for now)

The engine processes the full CSV on every run. For CCHMC at 596K rows, this takes ~3 minutes including Excel output. For UCH at 3K rows, it's trivial. But clients sending monthly data extracts will re-classify previously-classified rows.

**Recommendation**: Defer to v2. Note in the design doc that incremental processing is a future requirement.

---

## 7. Hidden Assumptions

### 7.1 Assumptions That Break for Non-CCHMC Clients

| Assumption | Code Location | CCHMC | UCH | Impact |
|-----------|---------------|-------|-----|--------|
| `spend_category` column contains extractable codes | line 262 | SC0250 | "Facilities" (constant) | Tier 1 maps all rows identically |
| `line_memo` column exists and contains descriptive text | line 268 | Rich descriptions | Column does not exist | Tier 3 degrades to supplier-only matching |
| `line_of_service` column exists | line 269 | Always populated | Column does not exist | Tier 4 completely broken |
| `cost_center` column exists | line 270 | Always populated | Column does not exist | Tier 5 completely broken |
| Amount column is numeric | lines 534-535 | float64 | String "$5,567.76" | `.sum()` / `.mean()` will fail or produce wrong results |
| All 6 column mappings can be satisfied | lines 51-54 | 46 columns available | Only 11 columns, 3 mappings missing | Config validation crash |
| Refinement rules use SC codes as scoping | lines 290-370 | All rules scoped by SC code | No SC codes to scope by | Tiers 2, 4, 5 produce 0 matches |
| Column names have no leading/trailing whitespace | lines 237-251 | Clean column names | `'  Spend Amount  '` has whitespace | Column lookup fails |
| CSV has no BOM issues | line 230 | BOM present but pandas handles it | BOM present, pandas handles it | Not broken, but untested assumption |
| YAML `sc_codes` values are actual SC code strings | test_rules.py lines 133-154 | SC0250 format | Subcategory strings | Tests produce confusing messages |
| `output_columns` hardcodes LoS and CC columns | lines 449-451 | Columns exist | Columns don't exist, `df.get()` returns empty Series | Works but output has empty columns with misleading headers |

### 7.2 CSV Encoding and Format Assumptions

| Assumption | Current Behavior | Risk |
|-----------|-----------------|------|
| UTF-8 encoding | `pd.read_csv(paths['input'], low_memory=False)` -- no encoding param | Will fail on Windows-1252 or Latin-1 encoded files (common in older ERP exports) |
| Comma delimiter | Default pandas delimiter | Some ERPs export tab-delimited or semicolon-delimited (especially European) |
| Standard quoting | Default pandas quoting | Some exports use `""` escaping vs `\"` |
| No duplicate column names | Not checked | Some ERP exports have duplicate headers (e.g., two "Amount" columns for different currencies) |
| First row is header | Default pandas behavior | Some exports have metadata rows before the header |

**Recommendation**: Add optional `csv_options` config section:
```yaml
csv_options:
  encoding: "utf-8-sig"    # Handles BOM automatically
  delimiter: ","
  skip_rows: 0             # Skip metadata rows before header
```

### 7.3 The Engine Assumes Single-Client-Per-Run

**Severity**: Low

The engine loads one config, processes one CSV, writes one Excel. This is correct for the current use case. But some consulting workflows involve comparing classifications across clients or running batch processing.

**Recommendation**: No action needed now. The CLI interface naturally supports scripting:
```bash
for client in cchmc uch; do
  python src/categorize.py --config clients/$client/config.yaml
done
```

---

## 8. Alternative Approaches

### 8.1 Preprocessing Normalizer (Recommended for UCH)

Instead of generalizing the engine's internals, add a **preprocessing step** that normalizes any client's CSV into CCHMC-like structure:

```
UCH CSV -> normalizer -> normalized CSV -> existing engine -> output
```

The normalizer for UCH would:
1. Rename `Subcategory` -> `Spend Category` (or create a synthetic SC code column)
2. Clean amount column: strip `$`, `,`, whitespace, convert to float
3. Create empty placeholder columns for `Line Memo`, `Line of Service`, `Cost Center`
4. Strip column name whitespace

**Pros**:
- Zero changes to the existing, working engine
- Each client's normalizer is independent
- CCHMC regression risk is zero

**Cons**:
- Data loss: UCH's `Capex/Opex`, `SpendBand`, `Location` are dropped (or passed through but unused)
- Two-step workflow (normalizer + engine) is more complex to operate
- Still doesn't solve the fundamental tier composition problem

**Verdict**: Good for UCH as a stopgap. Does not scale to client #3 or #4 with different structural needs.

### 8.2 Canonical Intermediate Format (Best Long-Term)

Define a canonical schema that all client data must conform to:

```
Phase 1: Client Adapter -> Canonical Format
Phase 2: Classification Engine -> Output
```

Canonical format:
```csv
transaction_id, supplier, category_code, description, department, cost_center, amount, [client_extra_1, ...]
```

Each client gets an adapter (Python script or config-driven transform) that maps their columns to canonical fields, cleans data types, and handles client-specific quirks.

**Pros**:
- Clean separation of concerns
- Engine operates on one schema, always
- Client-specific complexity is isolated in adapters
- Adapters are testable independently

**Cons**:
- More code to write initially
- "Canonical format" is still an assumption about what columns exist
- Some clients may have data that doesn't fit any canonical column

**Verdict**: Best architecture for 5+ clients. Overkill for 2 clients. Consider implementing when client #3 arrives.

### 8.3 ML Classifier Per Client

Train a classifier (gradient-boosted trees, not deep learning) per client using the taxonomy as labels and supplier name + available text columns as features.

**Pros**:
- No rule-writing: learns from labeled examples
- Handles free-text naturally
- Could achieve high accuracy with 500+ labeled examples per taxonomy category

**Cons**:
- Requires labeled training data (chicken-and-egg: the engine IS the labeling tool)
- Black-box: hard to explain why a transaction was classified a certain way
- Drift: model degrades as supplier mix changes
- Overkill for UCH's 3,092 rows with 24 clean subcategories

**Verdict**: Wrong approach for the current problem. The data is structured enough that rule-based classification is both simpler and more explainable. ML is appropriate when text descriptions are the primary classification signal and there are thousands of unique descriptions.

### 8.4 Hybrid: Rules + Embedding Fallback

Keep the rule-based waterfall but add an embedding-based fallback tier for rows that no rule matches:

```
Tiers 1-7 (rules) -> Tier 8: Embedding similarity to taxonomy descriptions -> Output
```

**Pros**:
- Rules handle the deterministic cases (high confidence)
- Embeddings handle the long tail (lower confidence, flagged for review)
- No training data needed (uses taxonomy description embeddings)

**Cons**:
- Adds a dependency on an embedding model (sentence-transformers or OpenAI API)
- Breaks the "no network access required" NFR (unless using local model)
- Adds latency (~30s for 600K rows with local embeddings)

**Verdict**: Interesting for v2. Not needed for UCH (Subcategory mapping solves the problem). Worth exploring for clients with free-text-only data.

---

## 9. Recommendations Summary

| # | Concern | Severity | Recommendation | Decision Required |
|---|---------|----------|---------------|-------------------|
| 1 | Waterfall is CCHMC-shaped | Critical | Refactor to pluggable pipeline or accept UCH as a special case | Architecture: pluggable vs. monolithic |
| 2 | No tier abstraction | Critical | Extract tiers into functions with common interface | Refactor scope and timeline |
| 3 | UCH Category is useless, Subcategory is gold | Critical | Map `spend_category` to `Subcategory`, use `(.+)` as pattern | Confirm Subcategory mapping approach |
| 4 | All 6 columns required | Critical | Make `line_memo`, `line_of_service`, `cost_center` optional | Which columns are truly required |
| 5 | Amount parsing fails on currency strings | High | Add amount cleaning step, define supported formats | Amount format contract |
| 6 | Column name whitespace | Medium | Add `df.columns = df.columns.str.strip()` | None -- just do it |
| 7 | Test suite is CCHMC-specific | High | Split shared vs. client-specific tests | Test organization structure |
| 8 | No cross-client regression | High | Add golden-output test for CCHMC | Refactor `main()` for testability |
| 9 | `test_rule_counts` will fail for UCH | High | Delete from shared suite, move to client-specific | None -- just do it |
| 10 | Known-mapping assertions hardcoded | High | Move to per-client fixture files | Test fixture format |
| 11 | `sc_code_pattern` required but meaningless for UCH | High | Make optional, rename to `category_pattern` | Naming convention |
| 12 | No config coherence validation | Medium | Add post-load diagnostics and warnings | Warning threshold values |
| 13 | Supplier rules require `sc_codes` | High | Make `sc_codes` optional in supplier rules | Rule schema change |
| 14 | `paths.keyword_rules` and `paths.refinement_rules` required | Medium | Make optional with empty defaults | Config schema change |
| 15 | No quality prediction tool | Medium | Add `--dry-run` profiling mode | Defer vs. implement now |
| 16 | CSV encoding/format assumptions | Medium | Add `csv_options` config section | Defer vs. implement now |
| 17 | Taxonomy versioning | Medium | Add version tracking and migration tooling | Defer to v2 |
| 18 | UCH onboarding estimate is wrong | High | Separate engine dev time from onboarding time | Project planning |

---

## 10. Verdict: CONDITIONAL GO

The multi-client generalization is viable, but the team should NOT proceed with a naive "make columns optional and skip unused tiers" approach. That produces a technically-running-but-useless engine for UCH.

### Conditions for GO

1. **Implement Subcategory/Category-Code mapping as a first-class concept** (Items 3, 11). UCH's classification quality depends entirely on this. Without it, the tool is not deliverable for UCH.

2. **Make line_memo, line_of_service, cost_center optional** (Item 4). This is the minimum viable change to avoid crashing on UCH's CSV.

3. **Add amount column cleaning** (Item 5). UCH amounts are strings. The engine will produce incorrect financial totals or crash.

4. **Strip column name whitespace** (Item 6). One line of code, prevents a class of onboarding errors.

5. **Split test suite into shared and client-specific** (Items 7, 9, 10). Running the existing test suite against UCH will produce 10+ failures that are all false negatives.

### Recommended Sequencing

**Phase 1 (must-do before UCH onboarding, ~2 days)**:
- Make columns optional (line_memo, line_of_service, cost_center)
- Add column name stripping
- Add amount parsing/cleaning
- Make `sc_code_pattern` optional (default: use raw column value)
- Split test suite
- Add CCHMC regression test

**Phase 2 (should-do, ~1-2 days)**:
- Rename SC-code-specific concepts to generic "category code" naming
- Make `sc_codes` optional in supplier rules
- Add config coherence warnings
- Add `--dry-run` profiling mode

**Phase 3 (recommended for client #3, ~3-5 days)**:
- Extract tiers into pluggable pipeline
- Implement canonical intermediate format
- Add CSV options config section
- Add taxonomy version tracking

### What NOT to Do

- Do NOT attempt a full architectural refactor before UCH delivery. The Phase 1 changes are sufficient to make UCH work with acceptable quality.
- Do NOT build an ML classifier. The data does not warrant it.
- Do NOT add an embedding fallback. UCH has structured subcategories -- embeddings solve a problem UCH doesn't have.
- Do NOT write 180 supplier rules for UCH before implementing Subcategory mapping. That's manual labor that a 24-row mapping table eliminates.
