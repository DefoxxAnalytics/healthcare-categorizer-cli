# Critical Review: Multi-Client Generalization of Healthcare Categorization CLI

**Reviewer**: Architecture Review (Revision 3 -- Corrected UCH Dataset: uch-2026.xlsx)
**Date**: 2026-02-14
**Scope**: Generalization of `categorization-cli` engine from CCHMC-only to multi-client (UCH as second client)
**Engine**: `src/categorize.py`, 614 lines
**Verdict**: **STRONG GO** (see Section 9)

---

## 1. Executive Summary

The previous review was based on the wrong UCH dataset (a Facilities InScope CSV with 11 columns and 3,092 rows). The real UCH dataset is **uch-2026.xlsx** -- an Oracle Fusion ERP export with **4,649 rows and 44 columns**. This changes the entire analysis.

UCH's data is structurally much closer to CCHMC than previously thought:

- `Category Name` contains UNSPSC codes in `code-description` format (e.g., `39101612-Incandescent Lamps and Bulbs`) -- directly analogous to CCHMC's `Spend Category` with SC codes.
- `Item Description` has 4,155 unique free-text values -- directly analogous to CCHMC's `Line Memo`.
- `Cost Center Description` has 7 values -- directly maps to Tier 5.
- `Paid Amount` is already float64 -- no parsing needed.
- `Supplier` has 294 unique values -- tractable for rule authoring.

**6 of 7 tiers work.** Only Tier 4 (Line of Service context refinement) is unavailable because UCH has no `Line of Service` column. This is a moderate refactoring, not a rewrite. The key risks are in the details -- specifically, the 37.6% concentration on a single catch-all UNSPSC code and the 30.9% supplier concentration in GRAINGER.

---

## 2. What Actually Breaks

### 2.1 `required_columns` Forces `line_of_service` (Line 51)

```python
required_columns = ['spend_category', 'supplier', 'line_memo', 'line_of_service', 'cost_center', 'amount']
```

UCH has no `Line of Service` column. The engine will raise `ConfigError("Missing required column mapping: 'columns.line_of_service'")` before loading any data. This is a hard failure at config validation, not a runtime error.

**Fix**: Make `line_of_service` optional. Move it to a separate `optional_columns` list. ~5 lines changed.

### 2.2 `sc_code_pattern` Required in Classification Config (Lines 56-59)

```python
required_class = ['sc_code_pattern', 'confidence_high', 'confidence_medium']
```

This does not break -- UCH CAN use a regex pattern. But the variable name `sc_code_pattern` is misleading for UNSPSC codes. The config key works fine (`(\d+)` extracts `99000038` from `99000038-Equipment Maintenance Services`), but every developer reading the code will ask "what's an SC code?" when working on UCH.

**Impact**: Cosmetic confusion, not a functional break.

### 2.3 `pd.read_csv()` Hardcoded (Line 230)

```python
df = pd.read_csv(paths['input'], low_memory=False)
```

UCH input is `.xlsx`. This will either fail with a parse error or produce garbage. Line 235 compounds it:

```python
raise ConfigError(f"Input CSV has 0 data rows: {paths['input']}")
```

The error message says "CSV" even if the input is Excel.

**Fix**: Extension-based format detection. `pd.read_excel()` for `.xlsx`/`.xls`, `pd.read_csv()` otherwise.

### 2.4 SC-Specific Variable Names Throughout

The engine uses `sc_code`, `sc_mapping`, `sc_pattern`, `sc_extracted` (lines 262-265), `load_sc_mapping()` (line 81), `ambiguous_codes` described as "Ambiguous SC codes" (line 217). Output columns include `SC Code` (line 448), `Spend Category (Source)` (line 447), and the unmapped sheet is `Unmapped SC Codes` (line 574).

These are not functional breaks -- UNSPSC codes flow through the same variables without issue. But the naming creates a maintenance trap. A developer debugging UCH classification will see `sc_code = '99000038'` and wonder if it should be there.

**Impact**: Technical debt, not a blocker.

### 2.5 `load_refinement_rules()` Requires `sc_codes` Key (Lines 148-152)

```python
_validate_and_compile_rules(
    supplier_rules, 'supplier_rules',
    ('sc_codes', 'supplier_pattern', 'taxonomy_key', 'confidence'),
    'supplier_pattern',
)
```

The refinement rules schema uses `sc_codes` as the key name for scoping rules to specific category codes. For UCH, these would contain UNSPSC codes (`['39101612', '31160000']`) instead of SC codes. The key name is misleading but functionally fine -- the engine treats them as opaque string keys.

For context rules (lines 155-159), the required key is `line_of_service_pattern`. UCH has no Line of Service column, so any context rules in UCH's refinement file would match against an empty string and produce zero hits. Not a crash, but writing context rules for UCH would be pointless.

**Impact**: Naming confusion. The `sc_codes` key in UCH's rule files would contain UNSPSC codes, which is correct behavior but confusing naming.

### 2.6 Output Columns Hardcoded (Lines 447-448, 574)

```python
output_columns['Spend Category (Source)'] = spend_cat_str
output_columns['SC Code'] = sc_code
```

And:

```python
pd.DataFrame(unmapped_data).to_excel(writer, sheet_name='Unmapped SC Codes', index=False)
```

UCH output will have a column called `SC Code` containing UNSPSC codes like `99000038`. The `Unmapped SC Codes` sheet will list unmapped UNSPSC codes. Functionally correct; semantically wrong.

**Impact**: Confusing output for UCH stakeholders who don't know what "SC Code" means.

### 2.7 Test Suite: CCHMC-Specific Assertions

`test_rules.py` has three hard breaks for UCH:

1. **`TestSupplierClassification.KNOWN_MAPPINGS`** (lines 190-198): 7 hardcoded CCHMC assertions (`SC0250`, `SC0207`) that will all fail for UCH.
2. **`test_rule_counts`** (lines 261-273): Asserts `230+` supplier rules, `8+` context rules, `10+` cost center rules, `11+` override rules. UCH will have far fewer.
3. **`TestSCCodeValidity`** (lines 133-153): Class named `TestSCCodeValidity` with fixture `valid_sc_codes`. Works with UNSPSC codes functionally but the naming is misleading.

Running `pytest --client-dir clients/uch` will produce approximately 10-15 test failures, all false negatives from CCHMC-specific assertions.

---

## 3. What Does NOT Break

This section is critical -- it counters the narrative that multi-client support requires a major rewrite.

### 3.1 The Waterfall Architecture is Sound

The 7-tier cascade with first-match-wins is the correct architecture for healthcare procurement classification. Both Workday (CCHMC) and Oracle Fusion (UCH) expose the same fundamental classification signals: category codes, suppliers, item descriptions, cost centers. The column names differ; the semantics do not.

The engine's column aliasing (lines 185-186, `cols = config['columns']`) already abstracts physical column names from logical roles. UCH's config would set `spend_category: "Category Name"`, `line_memo: "Item Description"`, `cost_center: "Cost Center Description"`, `amount: "Paid Amount"`. No engine changes needed for this.

### 3.2 UNSPSC Codes are Structurally Analogous to SC Codes

UCH's `Category Name` format (`99000038-Equipment Maintenance Services`) is structurally identical to CCHMC's `Spend Category` format (`SC0250 - IT Professional Services`). Both are `code-description` strings where a regex extracts the numeric/alphanumeric prefix.

The `sc_code_pattern` config parameter (consumed at line 257-262) handles this:
- CCHMC: `((?:DNU\s+)?SC\d+)` extracts `SC0250`
- UCH: `(\d+)` extracts `99000038`

The extraction logic (line 262) is already parameterized:
```python
sc_extracted = spend_cat_str.str.extract(f'({sc_pattern})', expand=False)
```

No engine change needed.

### 3.3 Item Description is a Strong Line Memo Analog

UCH's `Item Description` has 4,155 unique values across 4,649 rows (89.4% uniqueness). Examples:
- `"REPAIR MAIN FREEZER"`
- `"Morton water softener salt."`
- `"FURNISH AND INSTALL REPLACEMENT VALVES - (2) 3\" TRIPLE DUTY..."`
- `"Repair PowerSoak Pot and Pan Machine"`

This is rich, descriptive text comparable to CCHMC's Line Memo. Tier 3 keyword rules will match patterns like `HVAC`, `FREEZER`, `fire suppression`, `plumbing` with the same effectiveness. The `combined_text = supplier + ' ' + line_memo` approach (line 271) produces matchable strings.

### 3.4 Cost Center Description Maps Directly

UCH has 7 cost center values: MAINTENANCE (3,143 rows), MECHANICAL SERVICES (774), GROUNDS & MOVERS (222), EMERGENCY MAINTENANCE (187), BUILDING SERVICES (181), ELECTRICAL SERVICES (84), PLANT OPERATIONS (58). These map to Tier 5 cost center rules without modification.

### 3.5 Paid Amount is Already Float64

No currency string parsing needed. No `$5,567.76` to `5567.76` conversion. The amount column is clean numeric data. Lines 534-535 (`results_df[amount_col].sum()`, `.mean()`) work unchanged.

### 3.6 Column Names are Clean

No whitespace stripping needed. UCH column names are standard Oracle Fusion export names with no leading/trailing spaces.

### 3.7 Mapping File Format Works Unchanged

The YAML mapping format (`load_sc_mapping()`, lines 81-94) stores codes as keys mapping to `{name, taxonomy_key, confidence, ambiguous}`. This works identically for UNSPSC codes:

```yaml
mappings:
  "99000038":
    name: Equipment Maintenance Services
    taxonomy_key: "Facilities > Building Maintenance > General Maintenance Services"
    confidence: 0.90
    ambiguous: false
  "39101612":
    name: Incandescent Lamps and Bulbs
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    confidence: 0.60
    ambiguous: true
```

No structural changes to the mapping schema.

---

## 4. The REAL Challenges

The obvious breaks in Section 2 are trivial to fix (CSV-to-XLSX, optional column, naming). The hard problems are below.

### 4.1 The 39101612 Problem (37.6% of All Rows)

`39101612-Incandescent Lamps and Bulbs` appears in 1,750 out of 4,649 rows. This is the single biggest threat to classification quality.

**Why this is almost certainly a catch-all code**: No hospital buys 1,750 batches of incandescent light bulbs. The transactions under this code span dozens of suppliers and wildly different item descriptions ("REPAIR MAIN FREEZER", "Morton water softener salt", "Replacement of Clean Agent Fire Suppression System"). This code was likely assigned by default in Oracle Fusion when the actual UNSPSC code was unknown or when purchase requisitions didn't specify a commodity code.

**The classification cascade problem**: If `39101612` is marked `ambiguous: true` in the mapping, these 1,750 rows skip Tier 1 and flow to Tiers 2-5. This is correct behavior -- but it means:

- **37.6% of all rows depend on Tiers 2-5 for accurate classification.** If the supplier refinement and keyword rule coverage is thin, these rows fall through to Tier 6 (ambiguous fallback) with low confidence, landing in Quick Review or Manual Review.
- **GRAINGER alone accounts for ~560 of these 1,750 rows** (30.9% of total dataset, concentrated under the catch-all). GRAINGER sells everything. A single GRAINGER supplier rule under `39101612` would misclassify most of those 560 rows.
- **The Item Description field is the primary disambiguator** for catch-all rows. "REPAIR MAIN FREEZER" needs to go to Facilities > Building Maintenance. "Morton water softener salt" needs to go to Facilities > Operating Supplies and Equipment. These are radically different taxonomy paths under the same UNSPSC code and same supplier type (MRO distributor).

**Required rule density**: To get 85%+ of the 1,750 catch-all rows classified accurately, you need:
1. Supplier refinement rules for the top 15-20 suppliers under `39101612` (~30-40 rules, because many suppliers need multiple rules for different product categories)
2. Keyword rules targeting Item Description patterns: `repair|maintenance`, `install|replacement`, `salt|chemical|cleaning`, `valve|pipe|plumbing`, `hvac|air|cooling|heating`
3. Cost center refinement rules for the non-MAINTENANCE cost centers (ELECTRICAL SERVICES, MECHANICAL SERVICES, GROUNDS & MOVERS have clear taxonomy implications)

This is 4-6 hours of rule authoring, not 30 minutes.

### 4.2 GRAINGER Concentration Risk

GRAINGER = 1,436 rows (30.9% of all transactions), $6.3M+ in spend. As a broad-line MRO distributor, GRAINGER supplies safety equipment, electrical components, HVAC parts, plumbing supplies, lighting, fasteners, janitorial supplies, and hundreds of other product categories.

**Why this is a classification challenge**: The engine's Tier 2 (supplier refinement) scopes rules by `sc_codes + supplier_pattern`. For rows where the UNSPSC code is non-ambiguous, GRAINGER rows are classified correctly by Tier 1 -- the UNSPSC code determines the category, and GRAINGER is just the vendor. The problem is GRAINGER rows under `39101612` (the catch-all), where the UNSPSC code provides no signal and the supplier name provides no signal either (GRAINGER sells everything).

For these rows, classification depends entirely on Tier 3 (keyword matching on Item Description) or Tier 5 (cost center). A blanket GRAINGER supplier rule mapping to `Facilities > Operating Supplies and Equipment` would be correct for maybe 40% of GRAINGER rows and wrong for the other 60%.

**Recommendation**: Do NOT write a single GRAINGER supplier rule. Instead:
1. Let UNSPSC codes handle GRAINGER rows with non-ambiguous codes (Tier 1).
2. Write granular keyword rules for GRAINGER rows under `39101612`, keyed on Item Description patterns.
3. Use Tier 7 (supplier override) only for post-classification corrections where GRAINGER rows were provably misclassified by Tiers 1-3.

### 4.3 UNSPSC Code Quality

118 unique UNSPSC codes. Not all are standard.

**Standard UNSPSC codes** (8-digit, recognized prefixes): `39101612` (Incandescent Lamps), `31160000` (Hardware), `46182402` (Parts), `42271701` (Medical gas cylinders), `26110000` (Batteries and generators), `53102710` (Corporate uniforms). These have well-defined meanings in the UNSPSC taxonomy and map cleanly to Healthcare Taxonomy v2.9.

**Internal/non-standard codes** (99-prefix): `99000038` (Equipment Maintenance Services), `99000059` (Infrastructure Services), `99000051` (Grounds Management Services). The `99` segment is not a valid UNSPSC segment. These are UCH's internal service category codes, likely created in Oracle Fusion when no standard UNSPSC code fit.

**Decision point**: Treat all 118 codes the same way, or assign different confidence levels?

I lean toward the same treatment. The mapping YAML already supports per-code confidence values. Set standard UNSPSC codes at 0.90 confidence (the code reliably indicates the product category) and `99xxxxxx` codes at 0.85 (the code indicates a service category, which is correct but coarser). The engine doesn't need to know the difference -- the confidence value encodes it.

The regex `(\d+)` extracts the numeric prefix from both formats. This works. But note: `(\d+)` will match the FIRST contiguous digit sequence. For `99000038-Equipment Maintenance Services`, this correctly extracts `99000038`. For any value with digits in the description (unlikely but possible, e.g., `39101612-Type 2 Lamps`), it still correctly extracts the leading code because `str.extract()` returns the first match.

### 4.4 XLSX Input Support

Adding `pd.read_excel()` seems trivial. The implications:

1. **Sheet selection**: `pd.read_excel(path, sheet_name=0)` reads the first sheet by default. UCH's file may have a single sheet, or it may have multiple sheets (Oracle Fusion exports sometimes include a metadata/summary sheet). The config should support an optional `sheet_name` parameter under `paths`.

2. **Performance**: `pd.read_excel()` is slower than `pd.read_csv()` -- typically 3-5x for the same row count. For 4,649 rows this is irrelevant (sub-second either way). For a future client with 500K+ rows in XLSX, this could matter. Not a current concern.

3. **Memory**: pandas reads the entire file into memory regardless of format. For 4,649 rows x 44 columns, memory impact is negligible (~2MB).

4. **Data types**: `pd.read_excel()` preserves Excel data types more faithfully than CSV (dates remain datetime, numbers remain numeric). This is a benefit for UCH -- `Paid Amount` stays float64, `Creation Date` stays datetime64. No type coercion surprises.

**Fix complexity**: ~10 lines of code. Detect extension, call the appropriate reader, optionally pass `sheet_name` from config.

### 4.5 Test Suite Brittleness

The test suite has three categories of CCHMC specificity:

1. **Hardcoded known mappings** (`test_rules.py` lines 190-198): 7 CCHMC-specific supplier-to-taxonomy assertions using SC codes (`SC0250`, `SC0207`). These are the most obviously client-specific tests.

2. **Rule count assertions** (`test_rules.py` lines 261-273): `230+` supplier rules, `8+` context rules, `10+` cost center rules, `11+` override rules. UCH will have ~20-40 supplier rules, 0 context rules, 3-5 cost center rules, 2-5 override rules. Every count assertion fails.

3. **SC-code-specific fixture names** (`TestSCCodeValidity`, `valid_sc_codes`): The fixture name says "SC Code" but the validation logic works with any string codes. Naming issue, not a functional issue.

Running `pytest --client-dir clients/uch` against the current test suite will produce ~15 test failures. All are false negatives -- they test CCHMC's rule corpus, not the engine's correctness.

**Required refactoring**:
- Move `KNOWN_MAPPINGS` and `test_rule_counts` to a client-specific test file (`tests/test_cchmc_rules.py`) or parameterize via per-client fixture files.
- The structural validation tests (`TestYAMLStructure`, `TestRegexValidity`, `TestTaxonomyKeyValidity`, `TestConfidenceRanges`) are already client-agnostic -- they validate any rule file's structural integrity.
- The conflict detection tests (`TestConflictDetection` excluding `test_rule_counts`) are also client-agnostic.

Estimated effort: 3-4 hours to split the test suite, including writing a minimal set of UCH-specific known mapping assertions after the first classification run.

---

## 5. Architecture Assessment

### 5.1 Is the Config-Driven Conditional Tier Approach Sufficient?

**Yes** -- for 2-3 clients with structured procurement data from major ERPs (Workday, Oracle Fusion, SAP, Coupa). The column aliasing, per-client regex patterns, and per-client rule files provide the necessary flexibility without introducing plugin complexity.

The waterfall is not CCHMC-shaped -- it is healthcare-procurement-shaped. Both clients have: a category code system, suppliers, item descriptions, cost centers, and amounts. The column names and code formats differ; the classification logic does not.

### 5.2 When Should It Be Refactored to a Pluggable Pipeline?

When client #4+ arrives with a fundamentally different classification **algorithm**, not just a different data shape. Specifically:
- A client with NO structured category codes (pure free-text) would need an embedding-based fallback tier that doesn't exist today.
- A client with a hierarchical approval workflow where classification depends on prior approvals would need a stateful tier.
- A client with real-time streaming data would need a different execution model entirely.

None of these are on the horizon. The current architecture handles all major ERP exports.

### 5.3 Is a Preprocessing Normalizer a Better Approach?

**No.** A preprocessing normalizer would transform each client's data into a canonical intermediate format before classification. This adds a layer of indirection that is unnecessary when the data structures are already close enough.

UCH's data doesn't need to be "normalized" into CCHMC's format. It needs to be *configured* -- column aliases, regex pattern, code mappings. The config IS the normalization layer. Adding a separate preprocessing step would be premature abstraction for 2 clients.

---

## 6. Classification Quality Projection for UCH

### 6.1 Tier-by-Tier Projection

| Tier | Estimated Coverage | Row Count | Reasoning |
|------|-------------------|-----------|-----------|
| Tier 1 (UNSPSC mapping) | ~62% | ~2,899 | 117 non-ambiguous UNSPSC codes (4,649 - 1,750 catch-all) |
| Tier 2 (Supplier refinement) | ~15-20% | ~700-930 | Targeted rules for top suppliers under `39101612` |
| Tier 3 (Keyword rules) | ~10-15% | ~465-700 | Item Description matching for remaining catch-all rows |
| Tier 4 (Context/LoS) | 0% | 0 | No Line of Service column |
| Tier 5 (Cost center) | ~2-3% | ~93-140 | Refine within ambiguous codes by cost center (non-MAINTENANCE only) |
| Tier 6 (Ambiguous fallback) | ~3-5% | ~140-232 | Residual `39101612` rows not caught by Tiers 2-5 |
| Tier 7 (Supplier override) | ~1-2% | ~47-93 | Post-classification corrections for specific misclassifications |

### 6.2 Projected Review Tier Distribution

- **Auto-Accept**: 85-92% (high-confidence Tier 1 + well-targeted Tier 2/3 rules)
- **Quick Review**: 5-10% (medium-confidence matches, primarily Tier 6 ambiguous fallback)
- **Manual Review**: 3-5% (unmapped or very low confidence)

### 6.3 Key Blocker to 95%+ Auto-Accept

The 1,750 catch-all rows. Without dense supplier refinement and keyword rules for this bucket, they fall to Tier 6 with low confidence. Getting from 85% to 95% Auto-Accept requires:
- ~30-40 supplier refinement rules for the catch-all code
- ~20-30 keyword rules targeting Item Description patterns
- Cost center rules for ELECTRICAL SERVICES, MECHANICAL SERVICES, GROUNDS & MOVERS rows under the catch-all

This is achievable but requires an iterative classify-review-refine cycle. Budget 2-3 iterations after the first run.

---

## 7. Effort Estimate Validation

| Work Item | Estimated Hours | Notes |
|-----------|----------------|-------|
| XLSX input support (line 230) | 1 | Extension detection, `pd.read_excel()`, optional `sheet_name` config |
| Make `line_of_service` optional (line 51, 269) | 1 | Config validation + conditional column loading |
| Rename SC-specific output columns | 1 | `SC Code` -> `Category Code`, `Unmapped SC Codes` -> `Unmapped Codes` |
| 118 UNSPSC-to-taxonomy mappings | 4-6 | Manual mapping using UNSPSC descriptions + UCH context |
| Supplier refinement rules (top 20 suppliers) | 3-5 | Focused on `39101612` catch-all bucket |
| Keyword rules (Item Description patterns) | 2-3 | Fork from CCHMC, add UCH-specific patterns |
| Cost center rules | 1 | 7 cost center values, straightforward mapping |
| UCH config.yaml | 0.5 | Column mappings, regex pattern, file paths |
| Test suite refactoring | 3-4 | Split CCHMC-specific assertions, add UCH assertions |
| CCHMC regression test | 1-2 | Golden-output assertion for method/tier distribution |
| Validation + iteration | 2-3 | Run, review, fix, repeat |
| **Total** | **~20-28 hours** | |

The old analysis suggested 40+ hours. That estimate was inflated by the assumption that the data was fundamentally different. With 6/7 tiers working, the engine changes are minimal. The bulk of the effort is rule authoring (UNSPSC mappings + supplier rules + keyword rules), which is content work, not engineering work.

---

## 8. Recommendations Summary Table

| # | Concern | Severity | Recommendation | Effort |
|---|---------|----------|----------------|--------|
| 1 | `pd.read_csv()` hardcoded (line 230) | **High** | Extension-based format detection; add `pd.read_excel()` path | 1 hr |
| 2 | `line_of_service` required (line 51) | **High** | Make optional; fill with empty Series if absent | 1 hr |
| 3 | `39101612` catch-all = 37.6% of rows | **High** | Mark ambiguous; write dense supplier + keyword rules for top suppliers | 4-6 hrs |
| 4 | `test_rule_counts` CCHMC-specific (lines 261-273) | **High** | Move to client-specific test file | 1 hr |
| 5 | `KNOWN_MAPPINGS` CCHMC-specific (lines 190-198) | **High** | Move to per-client fixture YAML | 1 hr |
| 6 | 118 UNSPSC codes need taxonomy mapping | **Medium** | Manual mapping; start with top 20 codes by volume | 4-6 hrs |
| 7 | GRAINGER at 30.9% spans many categories | **Medium** | Do NOT write blanket supplier rule; use Item Description + Cost Center | 0 (design) |
| 8 | `99xxxxxx` internal codes vs standard UNSPSC | **Medium** | Treat identically in engine; encode quality difference via confidence values | 0 (design) |
| 9 | No CCHMC regression test exists | **Medium** | Add golden-output assertion for method/tier counts post-refactor | 2 hrs |
| 10 | SC-specific variable/column names | **Low** | Rename to generic names (`category_code`, `Category Code`) in output | 1 hr |
| 11 | Cost center skewed (67.6% MAINTENANCE) | **Low** | Use cost center rules sparingly for UCH; focus on Tier 2/3 | 0 (awareness) |
| 12 | Sheet selection for XLSX inputs | **Low** | Add optional `sheet_name` config parameter under `paths` | 0.5 hr |

---

## 9. Verdict: STRONG GO

The multi-client generalization is straightforward. 6 of 7 tiers work without modification. The engine changes are two small features (XLSX support + optional column) and some naming cleanup. The bulk of the work is rule content authoring for UCH.

### Conditions for Success

1. **Engine changes ship first** (XLSX support, optional `line_of_service`, test suite split). Estimated: 1 day.
2. **CCHMC regression test passes** before and after engine changes. The existing CCHMC classification must remain unchanged.
3. **`39101612` catch-all receives dedicated rule attention**. This is 37.6% of rows. Skimping on rules here drops Auto-Accept from 92% to 70%.
4. **GRAINGER is NOT given a blanket supplier rule**. Let the tiered waterfall handle the disambiguation through UNSPSC codes and Item Description.

### Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `39101612` residual > 10% after rules | Medium | Medium | Iterate supplier + keyword rules; accept 5% Tier 6 fallback initially |
| UNSPSC mapping errors | Medium | Low | 4,649 rows are manually reviewable; fix mismatches in iteration 2 |
| CCHMC regression from engine changes | Low | High | Golden-output regression test before merging |
| GRAINGER blanket rule misclassification | Low (if avoided) | High | Design decision: no blanket rule. Enforce in code review. |

---

## 10. What NOT to Build

- **No ML classifier.** 118 structured UNSPSC codes + rich Item Description text = rule-based classification is sufficient. ML requires labeled training data that doesn't exist and is overkill for 4,649 rows.
- **No embedding-based fallback tier.** UNSPSC codes provide category signal. Item Description provides disambiguation signal. The data is structured enough for deterministic rules.
- **No preprocessing normalizer.** UCH's data does not need reshaping into CCHMC's format. Config-driven column aliasing handles the differences.
- **No canonical intermediate format.** Premature abstraction for 2 clients. The config IS the adapter layer.
- **No pluggable pipeline refactor.** The monolithic waterfall with config-driven column aliasing is simpler and more maintainable for 2-3 clients. Refactor to plugins when client #4 needs a fundamentally different tier composition.
- **No UNSPSC hierarchical fallback.** 118 codes is tractable for flat mapping. Hierarchical fallback is a nice-to-have for clients with 500+ codes.
- **No auto-detection of input format or code patterns.** Explicit config is more transparent and debuggable than inference. A config typo is easier to find than an auto-detection bug.
