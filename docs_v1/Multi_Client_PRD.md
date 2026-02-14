# PRD: Multi-Client Healthcare Categorization Engine

**Product**: Healthcare Categorization CLI v2.0
**Owner**: VTX Solutions / Defoxx Analytics
**Date**: 2026-02-14
**Status**: Draft

---

## 1. Problem Statement

The categorization engine (`categorize.py`, 614 lines) classifies healthcare procurement transactions against Healthcare Taxonomy v2.9. It was built around a single client's data shape: CCHMC on Workday, with 46 columns including structured spend category codes (`SC0250`), line memos, line-of-service, and cost centers.

The engine cannot process UCH (University of Cincinnati Health) data without code changes. Here is why:

### 1.1 Column Mismatch

CCHMC provides 6 classification-relevant columns. UCH provides 2.

| Engine Expects | CCHMC Column | UCH Equivalent | Status |
|----------------|-------------|----------------|--------|
| `spend_category` | `Spend Category` ("SC0250 - Professional Services") | `Category` ("Facilities") | Different semantics |
| `supplier` | `Supplier` | `Supplier` | Compatible |
| `line_memo` | `Line Memo` | *Does not exist* | Missing |
| `line_of_service` | `Line of Service` | *Does not exist* | Missing |
| `cost_center` | `Cost Center` | *Does not exist* | Missing |
| `amount` | `Invoice Line Amount` (numeric: `1234.56`) | `  Spend Amount  ` (string: `"$5,567.76 "`) | Incompatible format |
| *Not expected* | *N/A* | `Subcategory` ("Office Equipment & Supplies") | New field, no engine support |
| *Not expected* | *N/A* | `Capex/Opex` | New field |
| *Not expected* | *N/A* | `SpendBand` ("5K - 10K") | New field |
| *Not expected* | *N/A* | `Location` ("Cincinnati") | New field |

### 1.2 Category Code Incompatibility

CCHMC uses structured spend category codes extracted via regex `((?:DNU\s+)?SC\d+)` from strings like `"SC0250 - Professional Services"`. The engine has 326 SC code mappings that translate these codes to taxonomy keys.

UCH has no coded category system. It has two free-text fields:
- `Category`: always `"Facilities"` (single value in this dataset)
- `Subcategory`: 24 values like `"Office Equipment & Supplies"`, `"HVAC Installation & Maintenance"`, `"Pest Control"`

There is no regex to extract. The `sc_code_pattern` config field is meaningless for UCH.

### 1.3 Tier Availability

| Tier | Requires | UCH Has It? | Result |
|------|----------|-------------|--------|
| 1: SC Code Mapping | Spend category codes | No | **Unusable** |
| 2: Supplier Refinement | SC codes + supplier | No SC codes | **Unusable** |
| 3: Keyword Rules | Supplier + line memo | No line memo | **Degraded** (supplier-only) |
| 4: Context Refinement | SC codes + line of service | Neither | **Unusable** |
| 5: Cost Center Refinement | SC codes + cost center | Neither | **Unusable** |
| 6: Ambiguous Fallback | SC codes | No | **Unusable** |
| 7: Supplier Override | Supplier + L1 | Has supplier | **Usable** |

5 of 7 tiers are completely unusable. The engine would classify 0% of UCH transactions.

### 1.4 Hardcoded Assumptions in Code

The engine enforces all columns as required at three points:

**Config validation (line 51-54):**
```python
required_columns = ['spend_category', 'supplier', 'line_memo', 'line_of_service', 'cost_center', 'amount']
for key in required_columns:
    if key not in config['columns']:
        raise ConfigError(f"Missing required column mapping: 'columns.{key}'")
```

**CSV column validation (line 237-251):**
```python
required_csv_cols = {
    'spend_category': cols['spend_category'],
    'supplier': cols['supplier'],
    'line_memo': cols['line_memo'],
    ...
}
missing_csv_cols = [
    f"'{v}' (from columns.{k})"
    for k, v in required_csv_cols.items()
    if v not in df.columns
]
if missing_csv_cols:
    raise ConfigError(f"Columns not found in input CSV: ...")
```

**SC code extraction (line 261-265):**
```python
sc_extracted = spend_cat_str.str.extract(f'({sc_pattern})', expand=False)
```
This line crashes or produces all-NaN if there are no SC codes to extract.

### 1.5 Amount Parsing

The engine assumes `amount` is numeric (pandas reads `1234.56` as float64). UCH amounts are strings: `"$5,567.76 "` with dollar signs, commas, and whitespace. The engine would fail on `df[amount_col].sum()` at line 534.

---

## 2. Goals & Non-Goals

### Goals

| ID | Goal |
|----|------|
| G1 | Process UCH's 11-column, no-SC-code, currency-string dataset without code changes |
| G2 | Preserve CCHMC's current behavior exactly (zero regression: 594,807 Auto-Accept, 1,989 Quick Review) |
| G3 | Support clients with any subset of: category codes, line memos, line of service, cost centers |
| G4 | Support Category+Subcategory as a first-class mapping dimension (not just SC codes) |
| G5 | Handle amount columns in numeric, USD string (`$1,234.56`), and European (`1.234,56`) formats |
| G6 | Allow tiers to be dynamically enabled/disabled based on available data columns |
| G7 | Onboard a new client in < 4 hours with config + reference YAML only, no code changes |

### Non-Goals

| ID | Non-Goal | Reason |
|----|----------|--------|
| NG1 | ML/NLP-based classification | The engine is rule-based by design. ML is a future product. |
| NG2 | Real-time / streaming classification | Batch CLI tool. Not a service. |
| NG3 | Auto-generating rules from data | Rule authoring remains manual. |
| NG4 | Supporting non-healthcare taxonomies | Healthcare Taxonomy v2.9 is the only target. |
| NG5 | Multi-taxonomy per client | One taxonomy version per run. |
| NG6 | GUI / web interface | CLI-only for v2. |
| NG7 | Modifying the taxonomy Excel file | Read-only reference data. |

---

## 3. User Personas

### 3.1 VTX/Defoxx Analyst (Primary Operator)

**Tasks**: Receives client ERP export (CSV), writes config YAML, authors classification rules, runs CLI, iterates until Auto-Accept rate exceeds 99%, delivers Excel to client.

**Pain points with current engine**:
- Must map every client column to 6 fixed fields even if the client does not have them.
- Cannot skip tiers that don't apply. Forced to create placeholder files.
- Amount parsing failures on non-numeric columns require pre-processing outside the tool.
- Cannot reuse keyword rules across clients without copying files.

### 3.2 Client Stakeholder (Results Consumer)

**Tasks**: Reviews Excel output. Checks Quick Review items. Validates taxonomy assignments against institutional knowledge.

**Needs**: Consistent output format across engagements. Recognizable column names from their source data in the output. Understands the `ClassificationMethod` field to gauge reliability.

---

## 4. Functional Requirements

### 4.1 Column Optionality

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-100 | `columns.supplier` is the only mandatory column mapping | P0 |
| FR-101 | `columns.amount` is required for financial aggregations but the engine runs without it (aggregation sheets omitted) | P0 |
| FR-102 | `columns.spend_category` is optional. If absent, all SC-code-dependent tiers (1, 2, 4, 5, 6) are automatically disabled | P0 |
| FR-103 | `columns.line_memo` is optional. If absent, Tier 3 keyword matching uses `supplier` text only (not `supplier + line_memo`) | P0 |
| FR-104 | `columns.line_of_service` is optional. If absent, Tier 4 is disabled | P0 |
| FR-105 | `columns.cost_center` is optional. If absent, Tier 5 is disabled | P0 |
| FR-106 | `columns.category` is a new optional field for free-text category (UCH: `"Facilities"`) | P1 |
| FR-107 | `columns.subcategory` is a new optional field for free-text subcategory (UCH: `"Office Equipment & Supplies"`) | P1 |
| FR-108 | Any column mapping set to `null` or omitted is treated as absent. The engine fills a synthetic empty-string Series internally. | P0 |

### 4.2 Category Code Generalization

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-110 | Rename internal concept from "SC code" to "category code" to be ERP-agnostic | P0 |
| FR-111 | `classification.code_extraction` replaces `sc_code_pattern`. It defines how to derive a code from the category column. Options: `regex` (current), `verbatim` (use full column value as-is), `composite` (concatenate multiple columns) | P0 |
| FR-112 | `regex` mode: works exactly as today. `sc_code_pattern` becomes `classification.code_extraction.pattern` | P0 |
| FR-113 | `verbatim` mode: the full value of `columns.spend_category` is the code. No regex extraction. Useful for clients with clean enumerated categories. | P0 |
| FR-114 | `composite` mode: concatenates two or more column values with a delimiter to form the code. Example: `Category + " > " + Subcategory` = `"Facilities > Office Equipment & Supplies"`. This composite string is the lookup key in the mapping file. | P0 |
| FR-115 | When `columns.spend_category` is absent and no `code_extraction` is configured, all code-dependent tiers are disabled. The engine falls through to keyword/supplier rules. | P0 |
| FR-116 | The mapping file (currently `sc_code_mapping.yaml`) is renamed conceptually to `category_mapping.yaml`. The YAML structure is the same: `mappings:` section with code → `{name, taxonomy_key, confidence, ambiguous}`. | P1 |

**Example: CCHMC code extraction (unchanged behavior)**
```yaml
classification:
  code_extraction:
    mode: regex
    source_column: spend_category
    pattern: '((?:DNU\s+)?SC\d+)'
```

**Example: UCH code extraction (new composite mode)**
```yaml
classification:
  code_extraction:
    mode: composite
    columns: [category, subcategory]
    delimiter: " > "
```
This produces codes like `"Facilities > Office Equipment & Supplies"`, which are used as keys in the category mapping file:
```yaml
mappings:
  "Facilities > Office Equipment & Supplies":
    name: "Office Equipment & Supplies"
    taxonomy_key: "Facilities > Operating Supplies and Equipment > Office Equipment & Supplies"
    confidence: 0.90
  "Facilities > HVAC Installation & Maintenance":
    name: "HVAC"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance > HVAC Installation & Maintenance"
    confidence: 0.95
```

### 4.3 Amount Parsing

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-120 | `columns.amount_format` specifies parsing mode: `numeric` (default, current behavior), `usd` (strip `$`, commas, whitespace), `eur` (swap `.` and `,` then parse), `auto` (detect format from first 100 non-null values) | P0 |
| FR-121 | After parsing, the internal amount column is always `float64`. All downstream aggregation code operates on the parsed float. | P0 |
| FR-122 | Rows where amount parsing fails are flagged with a warning in console output and the amount is set to `NaN` (not 0). | P0 |
| FR-123 | Column name whitespace is stripped during CSV load. UCH's `"  Spend Amount  "` becomes `"Spend Amount"` internally. | P1 |

**Parsing logic for `usd` mode:**
```python
# Input: "$5,567.76 " -> 5567.76
amount_str.str.strip().str.replace(r'[\$,]', '', regex=True).astype(float)
```

### 4.4 Tier Configuration

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-130 | Each tier can be explicitly enabled or disabled in config via `classification.tiers` | P0 |
| FR-131 | If `classification.tiers` is omitted, tier availability is auto-determined from available columns (backward compatible with CCHMC) | P0 |
| FR-132 | Auto-determination rules: Tier 1 requires `spend_category` + `code_extraction` + mapping file. Tier 2 requires Tier 1 prerequisites + `supplier`. Tier 3 requires `supplier` (line_memo optional). Tier 4 requires `spend_category` + `line_of_service`. Tier 5 requires `spend_category` + `cost_center`. Tier 6 requires `spend_category` + mapping file. Tier 7 requires `supplier`. | P0 |
| FR-133 | Console output reports which tiers are enabled and which are disabled (with reason). | P0 |
| FR-134 | Tier 3 adapts text source: uses `supplier + line_memo` if both exist, `supplier + subcategory` if subcategory exists and line_memo does not, `supplier`-only otherwise. Config key `classification.keyword_text_columns` allows explicit override of which columns to concatenate. | P1 |
| FR-135 | Attempting to force-enable a tier whose prerequisites are unmet produces a `ConfigError` at startup, not a silent runtime failure. | P0 |

### 4.5 Shared vs Per-Client Reference Data

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-140 | Taxonomy file (`Healthcare Taxonomy v2.9.xlsx`) is shared across all clients. Path is resolved relative to config file. | P0 |
| FR-141 | Category mapping, keyword rules, and refinement rules are per-client. Each client directory has its own copies. | P0 |
| FR-142 | A client config may reference shared rule files (e.g., `../../shared/reference/common_keyword_rules.yaml`) for cross-client reuse. No merge logic; the engine loads whatever file the config points to. | P2 |

### 4.6 Output Schema

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-150 | Classification columns are always present in output: `CategoryLevel1` through `CategoryLevel5`, `TaxonomyKey`, `ClassificationMethod`, `Confidence`, `ReviewTier` | P0 |
| FR-151 | Source category column in output adapts to client: named `"Spend Category (Source)"` for CCHMC, `"Category (Source)"` for UCH. Controlled by config `output.source_category_label` (default: `"Spend Category (Source)"`). | P1 |
| FR-152 | `"SC Code"` output column is renamed to `"Category Code"`. Contains the extracted/composed code, or empty if no code extraction is configured. | P0 |
| FR-153 | Columns that do not exist in the client's data are omitted from output (not filled with empty strings). UCH output has no `"Line Memo"`, `"Cost Center"`, or `"Line of Service"` columns. | P0 |
| FR-154 | `"Unmapped SC Codes"` sheet is renamed to `"Unmapped Category Codes"`. Only present if code extraction is configured and unmapped codes exist. | P1 |
| FR-155 | Summary sheet adapts metrics to available data. If no SC codes, the `"Unique SC Codes"` row is omitted. | P1 |

### 4.7 Aggregation Flexibility

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-160 | `aggregations` section in config is unchanged: list of `{name, column, top_n}`. | P0 |
| FR-161 | Aggregation columns that do not exist in the output DataFrame produce a warning and skip (current behavior, no change). | P0 |
| FR-162 | Default aggregations (`Spend by Category L1`, `Spend by Category L2`) are always generated regardless of config. | P0 |
| FR-163 | If `columns.amount` is absent, aggregation sheets that require summing spend are omitted. Sheets that only count rows are still generated. | P1 |

### 4.8 New Tier: Category+Subcategory Mapping (Tier 1B)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-170 | When `code_extraction.mode` is `composite` or `verbatim`, Tier 1 uses the composed/verbatim code for lookup in the category mapping file. This is not a new tier -- it is Tier 1 generalized. | P0 |
| FR-171 | For UCH, the composite code `"Facilities > Office Equipment & Supplies"` maps to a taxonomy key at the confidence specified in the mapping file. | P0 |
| FR-172 | Ambiguous flag works the same way: non-ambiguous composites are Tier 1, ambiguous composites are Tier 6 fallback. | P0 |

### 4.9 Config Validation

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-180 | Config schema validation runs at startup. Reports all errors at once, not one at a time. | P0 |
| FR-181 | Required fields: `client.name`, `paths.taxonomy`, `paths.output_dir`, `paths.output_prefix`, `columns.supplier` | P0 |
| FR-182 | Conditionally required: `paths.category_mapping` required if `code_extraction` is configured. `paths.refinement_rules` required if any refinement tier is enabled. `paths.keyword_rules` required if Tier 3 is enabled. | P0 |
| FR-183 | If `code_extraction` references columns not present in `columns`, produce `ConfigError`. | P0 |

---

## 5. Data Model

### 5.1 Internal Transaction Model

The engine maps any client's columns to an internal model. This is the canonical set of fields the engine operates on.

| Internal Field | Type | Required | Source (CCHMC) | Source (UCH) |
|---------------|------|----------|----------------|--------------|
| `supplier` | `str` | Yes | `Supplier` | `Supplier` |
| `amount` | `float64` | No (aggregations only) | `Invoice Line Amount` | `  Spend Amount  ` (parsed from USD string) |
| `category_code` | `str` | No | Extracted via regex: `"SC0250"` | Composed: `"Facilities > Office Equipment & Supplies"` |
| `category_source` | `str` | No | `Spend Category` raw value | `Category` raw value |
| `line_memo` | `str` | No | `Line Memo` | *empty Series* |
| `line_of_service` | `str` | No | `Line of Service` | *empty Series* |
| `cost_center` | `str` | No | `Cost Center` | *empty Series* |
| `subcategory` | `str` | No | *N/A* | `Subcategory` |
| `keyword_text` | `str` | Derived | `supplier + " " + line_memo` | `supplier + " " + subcategory` |

### 5.2 What is Truly Required

To classify a transaction, the engine needs exactly one of:
1. A `category_code` that maps to a taxonomy key (Tier 1/6), OR
2. A `supplier` name that matches a keyword rule (Tier 3) or override rule (Tier 7)

Everything else is enhancement:

| Enhancement | What it enables |
|-------------|----------------|
| `line_memo` | Richer keyword matching (Tier 3 text expansion) |
| `line_of_service` | Context refinement (Tier 4) |
| `cost_center` | Cost center refinement (Tier 5) |
| `subcategory` | Composite category codes, keyword text expansion |
| `amount` | Financial aggregations in output |

### 5.3 Column Mapping Contract

The config's `columns` section maps the client's CSV header names to the engine's internal model.

**Rules:**
- Keys are the engine's internal names (lowercase, snake_case).
- Values are the exact CSV column header strings (case-sensitive, including whitespace).
- Omitted keys mean the field is unavailable. The engine creates an empty `pd.Series('')`.
- `null` values are treated the same as omission.

**CCHMC mapping:**
```yaml
columns:
  spend_category: "Spend Category"
  supplier: "Supplier"
  line_memo: "Line Memo"
  line_of_service: "Line of Service"
  cost_center: "Cost Center"
  amount: "Invoice Line Amount"
```

**UCH mapping:**
```yaml
columns:
  supplier: "Supplier"
  category: "Category"
  subcategory: "Subcategory"
  amount: "  Spend Amount  "
```

Note: UCH omits `spend_category`, `line_memo`, `line_of_service`, `cost_center`. These fields are absent from the internal model.

---

## 6. Classification Architecture

### 6.1 Current Architecture (Hardcoded Waterfall)

```
main()
  ├── Extract SC code from spend_category (always)
  ├── Tier 1: SC code lookup in non-ambiguous mappings (always)
  ├── Tier 2: SC code + supplier regex (always)
  ├── Tier 3: keyword regex on supplier + line_memo (always)
  ├── Tier 4: SC code + line_of_service regex (always)
  ├── Tier 5: SC code + cost_center regex (always)
  ├── Tier 6: SC code lookup in ambiguous mappings (always)
  ├── Tier 7: supplier override post-classification (always)
  └── Review tier assignment
```

Every tier runs unconditionally. Missing columns cause either a crash or silent misclassification.

### 6.2 Proposed Architecture (Dynamic Tier Composition)

```
main()
  ├── Resolve column availability from config
  ├── Derive category_code (regex / verbatim / composite / none)
  ├── Build tier list from config + column availability
  ├── For each enabled tier:
  │     ├── Check prerequisites (column availability)
  │     ├── Run tier logic on unclassified rows
  │     └── Update taxonomy_key, method, confidence
  ├── Tier 7 (override): runs post-classification if enabled
  └── Review tier assignment
```

### 6.3 Tier Prerequisite Table

| Tier | Internal Name | Requires Columns | Requires Reference Files | Description |
|------|---------------|------------------|-------------------------|-------------|
| 1 | `category_code_mapping` | `category_code` | category mapping YAML | Non-ambiguous code lookup |
| 2 | `supplier_refinement` | `category_code`, `supplier` | refinement rules (supplier section) | Code + supplier regex |
| 3 | `keyword_rules` | `supplier` | keyword rules YAML | Regex on keyword_text |
| 4 | `context_refinement` | `category_code`, `line_of_service` | refinement rules (context section) | Code + LoS regex |
| 5 | `cost_center_refinement` | `category_code`, `cost_center` | refinement rules (CC section) | Code + CC regex |
| 6 | `ambiguous_fallback` | `category_code` | category mapping YAML (ambiguous entries) | Low-confidence code lookup |
| 7 | `supplier_override` | `supplier` | refinement rules (override section) | Post-classification L1 correction |

### 6.4 How UCH Gets Classified

With the proposed architecture, UCH config produces:

```
Enabled tiers: 1, 3, 6, 7
Disabled tiers: 2 (no supplier refinement rules), 4 (no line_of_service), 5 (no cost_center)

Tier 1: Composite code "Facilities > Office Equipment & Supplies" →
        lookup in UCH category_mapping.yaml →
        "Facilities > Operating Supplies and Equipment > Office Equipment & Supplies"
        confidence: 0.90

Tier 3: Supplier "GENERAL DATA COMPANY" matches keyword rule →
        More specific taxonomy key if rule exists

Tier 6: Ambiguous composite codes → generic fallback

Tier 7: Supplier overrides → L1 corrections
```

UCH's 24 subcategories can each be mapped in the category mapping file, giving Tier 1 immediate coverage of nearly all rows. Supplier keyword rules (Tier 3) handle within-subcategory refinement.

### 6.5 What Replaces SC-Code-Dependent Tiers

| Missing Field | Lost Tier | Replacement Strategy |
|---------------|-----------|---------------------|
| No SC codes | Tiers 1, 2, 4, 5, 6 | Use `composite` code extraction (Category + Subcategory). This restores Tiers 1 and 6. |
| No line memo | Tier 3 (degraded) | Use `supplier + subcategory` as keyword text instead of `supplier + line_memo` |
| No line of service | Tier 4 | No direct replacement. Compensate with more specific keyword rules (Tier 3). |
| No cost center | Tier 5 | No direct replacement. Compensate with supplier overrides (Tier 7) or keyword rules. |

### 6.6 Tier 2 Without SC Codes

Tier 2 (supplier refinement) scopes rules to specific category codes. For UCH, this means scoping rules to composite codes:

```yaml
supplier_rules:
  - category_codes: ["Facilities > Office Equipment & Supplies"]
    supplier_pattern: "general data"
    taxonomy_key: "Facilities > Operating Supplies and Equipment > Office Equipment & Supplies > Forms & Printing"
    confidence: 0.92
```

This works identically to CCHMC's `sc_codes` field, just with different key values. The config schema renames `sc_codes` to `category_codes` (with backward-compatible alias).

---

## 7. Config Schema v2

### 7.1 Schema Definition

```yaml
# REQUIRED
client:
  name: string                    # Required. Banner and output naming.
  description: string             # Optional.

# REQUIRED
paths:
  input: string                   # Required. CSV file, relative to config dir.
  taxonomy: string                # Required. Healthcare Taxonomy Excel.
  output_dir: string              # Required. Output directory.
  output_prefix: string           # Required. Output filename prefix.
  category_mapping: string        # Conditional. Required if code_extraction configured.
  keyword_rules: string           # Conditional. Required if Tier 3 is enabled.
  refinement_rules: string        # Conditional. Required if Tiers 2/4/5/7 are enabled.

# REQUIRED (at minimum: supplier)
columns:
  supplier: string                # Required. Supplier name column.
  amount: string                  # Optional. Monetary amount column.
  amount_format: string           # Optional. "numeric" | "usd" | "eur" | "auto". Default: "numeric".
  spend_category: string          # Optional. Category code source column.
  line_memo: string               # Optional. Line item description column.
  line_of_service: string         # Optional. Department / service context column.
  cost_center: string             # Optional. Cost center column.
  category: string                # Optional. Free-text category column.
  subcategory: string             # Optional. Free-text subcategory column.
  passthrough: list[string]       # Optional. Additional columns to carry into output.

# OPTIONAL
classification:
  confidence_high: float          # Required. Default: 0.7
  confidence_medium: float        # Required. Default: 0.5
  code_extraction:                # Optional. Omit to disable code-based tiers.
    mode: string                  # "regex" | "verbatim" | "composite"
    source_column: string         # For "regex"/"verbatim": which columns key (e.g., "spend_category")
    pattern: string               # For "regex" mode only.
    columns: list[string]         # For "composite" mode: column keys to join.
    delimiter: string             # For "composite" mode: join delimiter. Default: " > "
  keyword_text_columns: list[str] # Optional. Override columns concatenated for Tier 3.
                                  # Default: ["supplier", "line_memo"] (filtered to available).
  tiers:                          # Optional. Explicit tier control.
    category_code_mapping: bool   # Default: auto (enabled if prerequisites met)
    supplier_refinement: bool     # Default: auto
    keyword_rules: bool           # Default: auto
    context_refinement: bool      # Default: auto
    cost_center_refinement: bool  # Default: auto
    ambiguous_fallback: bool      # Default: auto
    supplier_override: bool       # Default: auto

# OPTIONAL
output:
  source_category_label: string   # Default: "Spend Category (Source)"
  code_column_label: string       # Default: "Category Code"

# OPTIONAL
aggregations:
  - name: string
    column: string
    top_n: int | null
```

### 7.2 CCHMC Config (v2 format, backward compatible)

```yaml
client:
  name: "CCHMC"
  description: "Cincinnati Children's Hospital Medical Center - Workday AP/Procurement"

paths:
  input: "data/input/cchmc-ftp-new.csv"
  category_mapping: "data/reference/sc_code_mapping.yaml"
  taxonomy: "../../shared/reference/Healthcare Taxonomy v2.9.xlsx"
  keyword_rules: "data/reference/keyword_rules.yaml"
  refinement_rules: "data/reference/cchmc_refinement_rules.yaml"
  output_dir: "output"
  output_prefix: "cchmc_categorization_results"

columns:
  spend_category: "Spend Category"
  supplier: "Supplier"
  line_memo: "Line Memo"
  line_of_service: "Line of Service"
  cost_center: "Cost Center"
  amount: "Invoice Line Amount"
  passthrough:
    - "Invoice Number"
    - "Invoice Line"
    - "Invoice Date"
    - "Invoice Status"
    - "Invoice Amount"
    - "Invoice Line Amount"
    - "Payment Status"
    - "Payment Type"
    - "Fund"
    - "Program"
    - "Grant"
    - "Funding Source"
    - "PO Type"
    - "Spend Type"
    - "Company"

classification:
  code_extraction:
    mode: regex
    source_column: spend_category
    pattern: '((?:DNU\s+)?SC\d+)'
  confidence_high: 0.7
  confidence_medium: 0.5

output:
  source_category_label: "Spend Category (Source)"
  code_column_label: "SC Code"

aggregations:
  - name: "Spend by Cost Center (Top 100)"
    column: "Cost Center"
    top_n: 100
  - name: "Spend by Line of Service"
    column: "Line of Service"
    top_n: null
  - name: "Spend by Fund (Top 30)"
    column: "Fund"
    top_n: 30
```

### 7.3 UCH Config (v2 format)

```yaml
client:
  name: "UCH"
  description: "University of Cincinnati Health - Facilities Procurement"

paths:
  input: "data/input/UCH-Facilities-InScope-07312025 1.csv"
  category_mapping: "data/reference/category_mapping.yaml"
  taxonomy: "../../shared/reference/Healthcare Taxonomy v2.9.xlsx"
  keyword_rules: "data/reference/keyword_rules.yaml"
  refinement_rules: "data/reference/refinement_rules.yaml"
  output_dir: "output"
  output_prefix: "uch_categorization_results"

columns:
  supplier: "Supplier"
  category: "Category"
  subcategory: "Subcategory"
  amount: "  Spend Amount  "
  amount_format: "usd"
  passthrough:
    - "PO Number"
    - "PO Date"
    - "Capex/Opex"
    - "SuppliersFlag"
    - "SpendBand"
    - "Category Type"
    - "Location"

classification:
  code_extraction:
    mode: composite
    columns: [category, subcategory]
    delimiter: " > "
  keyword_text_columns: [supplier, subcategory]
  confidence_high: 0.7
  confidence_medium: 0.5

output:
  source_category_label: "Category (Source)"
  code_column_label: "Category Code"

aggregations:
  - name: "Spend by Location"
    column: "Location"
    top_n: null
  - name: "Spend by Subcategory"
    column: "Subcategory"
    top_n: null
  - name: "Spend by SpendBand"
    column: "SpendBand"
    top_n: null
```

### 7.4 Backward Compatibility

The v1 config schema must still work without modification. Migration rules:

| v1 Field | v2 Equivalent | Migration |
|----------|--------------|-----------|
| `paths.sc_mapping` | `paths.category_mapping` | Accept either. Warn on `sc_mapping` (deprecated). |
| `classification.sc_code_pattern` | `classification.code_extraction.pattern` | If `sc_code_pattern` found and `code_extraction` absent, auto-construct `code_extraction: {mode: regex, source_column: spend_category, pattern: <value>}` |
| `columns.spend_category` (required) | `columns.spend_category` (optional) | If present and `code_extraction` absent, auto-construct regex mode with `spend_category` as source. |
| All 6 column mappings required | Only `supplier` required | Omitted columns are internally empty. |

The engine logs a deprecation notice when v1 fields are used:
```
NOTICE: Config uses v1 field 'paths.sc_mapping'. Use 'paths.category_mapping' in future configs.
```

### 7.5 Refinement Rules Schema (v2)

The refinement rules YAML renames `sc_codes` to `category_codes` with backward compatibility:

```yaml
supplier_rules:
  - category_codes: ["Facilities > Office Equipment & Supplies"]
    supplier_pattern: "general data"
    taxonomy_key: "Facilities > Operating Supplies and Equipment > Office Equipment & Supplies > Forms & Printing"
    confidence: 0.92
```

If the engine encounters `sc_codes` instead of `category_codes`, it treats them identically. No migration required for existing CCHMC rules.

---

## 8. Test Strategy

### 8.1 Test Categories

| Category | Scope | Trigger |
|----------|-------|---------|
| Unit: Config parsing | Config validation, column optionality, code extraction modes | Every PR |
| Unit: Amount parsing | Numeric, USD, EUR, mixed, edge cases | Every PR |
| Unit: Tier prerequisite resolution | Given columns X, tiers Y are enabled | Every PR |
| Integration: CCHMC regression | Full pipeline run, assert exact counts | Every PR |
| Integration: UCH pipeline | Full pipeline run with UCH data and config | Every PR |
| Integration: Minimal client | Client with only `supplier` + `amount`, no codes | Every PR |
| Config validation | Invalid configs produce correct errors | Every PR |
| Per-client: Rule validation | Existing test_rules.py adapted for multi-client | Every PR |

### 8.2 Unit Tests: Config Parsing

```
test_config_minimal_valid: only client.name, paths.taxonomy, paths.output_dir,
    paths.output_prefix, columns.supplier → loads without error
test_config_missing_supplier: omit columns.supplier → ConfigError
test_config_v1_compat: v1 config with sc_code_pattern → loads with deprecation notice
test_config_code_extraction_regex: mode=regex, source_column=spend_category,
    pattern='...' → valid
test_config_code_extraction_composite: mode=composite, columns=[category, subcategory],
    delimiter=" > " → valid
test_config_code_extraction_references_missing_column: mode=composite,
    columns=[nonexistent] → ConfigError
test_config_amount_format_usd: amount_format="usd" → accepted
test_config_amount_format_invalid: amount_format="gbp" → ConfigError
test_config_force_enable_impossible_tier: tiers.context_refinement=true but
    no line_of_service column → ConfigError
```

### 8.3 Unit Tests: Amount Parsing

```
test_parse_numeric: "1234.56" → 1234.56
test_parse_usd_basic: "$5,567.76 " → 5567.76
test_parse_usd_negative: "-$1,234.56" → -1234.56
test_parse_usd_no_cents: "$1,000" → 1000.0
test_parse_eur_basic: "5.567,76" → 5567.76
test_parse_auto_detects_usd: column with "$" values → auto-selects usd mode
test_parse_auto_detects_numeric: column with plain floats → auto-selects numeric mode
test_parse_unparseable_row: "N/A" → NaN, warning logged
```

### 8.4 Unit Tests: Tier Resolution

```
test_all_columns_present: all 6 columns + code_extraction → all 7 tiers enabled
test_no_category_column: no spend_category, no code_extraction → tiers 1,2,4,5,6 disabled;
    tiers 3,7 enabled
test_no_line_memo: line_memo absent → tier 3 enabled (supplier-only text), tier 4 unchanged
test_no_line_of_service: line_of_service absent → tier 4 disabled
test_no_cost_center: cost_center absent → tier 5 disabled
test_supplier_only: only supplier column → tiers 3,7 enabled
test_composite_code: composite code_extraction → tiers 1,2,6 enabled (if refinement rules exist)
test_explicit_disable_overrides_auto: tiers.keyword_rules=false even though supplier
    exists → tier 3 disabled
```

### 8.5 Integration Tests: CCHMC Regression

```
test_cchmc_total_rows: assert total == 596796
test_cchmc_auto_accept_count: assert auto_accept == 594807
test_cchmc_quick_review_count: assert quick_review == 1989
test_cchmc_manual_review_count: assert manual_review == 0
test_cchmc_unmapped_count: assert unmapped == 0
test_cchmc_output_has_sc_code_column: "SC Code" column present (via output.code_column_label)
test_cchmc_output_has_line_memo_column: "Line Memo" column present
```

### 8.6 Integration Tests: UCH Pipeline

```
test_uch_total_rows: assert total == 3092
test_uch_no_crash: pipeline completes without exception
test_uch_amount_parsed: all amount values are float64, no "$" in parsed column
test_uch_category_code_composed: category codes are "Facilities > <Subcategory>"
test_uch_no_line_memo_column: "Line Memo" NOT in output columns
test_uch_no_cost_center_column: "Cost Center" NOT in output columns
test_uch_has_passthrough: "PO Number", "Location" present in output
test_uch_tiers_disabled: console output shows tiers 4, 5 disabled
test_uch_classification_rate: < 5% unmapped (with category mapping covering 24 subcategories)
```

### 8.7 Integration Tests: Minimal Client

```
test_minimal_client_runs: CSV with only "Supplier" and "Amount" columns,
    config with only supplier + amount mapped, no code_extraction, no rules →
    all rows classified as "unmapped", pipeline completes, output has
    CategoryLevel1-5 = "", ReviewTier = "Manual Review"
```

### 8.8 Per-Client Rule Tests (Generalized test_rules.py)

The existing `test_rules.py` must work for any client. Changes:

| Current | v2 |
|---------|-----|
| `test_refinement_has_required_sections` asserts all 4 sections exist | Only asserts sections that the client's config references (e.g., UCH may have no context_rules) |
| `TestSCCodeValidity` asserts every `sc_codes` entry is in the mapping | Asserts every `category_codes` entry (or `sc_codes` alias) is in the mapping |
| `test_rule_counts` hardcodes CCHMC counts (230+ supplier rules) | Parameterized by client; each client specifies expected minimums in its config or a test fixture |

### 8.9 Config Validation Tests

```
test_config_schema_reports_all_errors: config missing 3 fields → error message
    lists all 3, not just the first
test_config_file_not_found: paths.input points to nonexistent file → ConfigError
    with path in message
test_config_column_not_in_csv: columns.supplier = "Vendor" but CSV has "Supplier" →
    ConfigError listing missing column
```

---

## 9. Migration Path

### Phase 1: Refactor Engine Internals (No Behavior Change)

**Goal**: Make columns optional internally without changing config schema or output.

1. Replace `required_columns` list with a `REQUIRED = {'supplier'}` set and `OPTIONAL = {'spend_category', 'line_memo', ...}` set.
2. For each optional column, create an empty `pd.Series('')` if the column mapping is absent or `null`.
3. Wrap each tier in a guard: `if tier_prerequisites_met(config):`.
4. Run CCHMC regression tests. Output must be byte-identical.

**Estimated effort**: 4-6 hours.

### Phase 2: Add Code Extraction Modes

**Goal**: Support `regex`, `verbatim`, and `composite` code extraction.

1. Add `code_extraction` config section parsing.
2. Implement `extract_category_code(df, config)` function that returns a `pd.Series` of codes.
3. Replace hardcoded `spend_cat_str.str.extract(...)` with the new function.
4. Add backward compatibility: if `sc_code_pattern` is present and `code_extraction` is absent, auto-construct regex config.
5. Run CCHMC regression tests.

**Estimated effort**: 3-4 hours.

### Phase 3: Add Amount Parsing

**Goal**: Parse currency-formatted strings into float64.

1. Add `amount_format` config field.
2. Implement `parse_amount(series, format)` function.
3. Insert parsing step after CSV load, before any aggregation.
4. Run CCHMC regression tests (amount_format defaults to `numeric`, so no change).

**Estimated effort**: 2-3 hours.

### Phase 4: Adapt Output Schema

**Goal**: Dynamic output columns based on available data.

1. Replace hardcoded output column construction with a builder that checks column availability.
2. Implement `output.source_category_label` and `output.code_column_label`.
3. Omit columns from output that are not present in client data.
4. Rename `"SC Code"` to configured label.
5. Run CCHMC regression tests (with v2 config specifying `code_column_label: "SC Code"`).

**Estimated effort**: 3-4 hours.

### Phase 5: UCH Onboarding

**Goal**: First non-CCHMC client runs successfully.

1. Create `clients/uch/` directory structure.
2. Write UCH `config.yaml` (v2 schema).
3. Create `category_mapping.yaml` with 24 Subcategory composite codes mapped to taxonomy keys.
4. Write UCH-specific keyword rules (supplier patterns).
5. Write UCH-specific refinement rules (if needed).
6. Run UCH pipeline. Iterate until classification rate > 95%.
7. Write UCH integration tests.

**Estimated effort**: 8-12 hours (including rule authoring).

### Phase 6: Rename Repo and Stabilize

**Goal**: The codebase is `healthcare-categorization-cli`, not `categorization-cli`.

1. Rename repository.
2. Update all internal paths, imports, documentation.
3. Add backward-compatibility aliases for v1 config fields.
4. Run all client regression tests.
5. Tag v2.0 release.

**Estimated effort**: 2-3 hours.

### Total Migration Effort: 22-32 hours

Each phase is independently shippable and testable. CCHMC regression tests gate every phase.

---

## 10. Success Criteria

| ID | Metric | Target | How to Measure |
|----|--------|--------|----------------|
| SC1 | CCHMC regression | 0 differences vs v1 output (594,807 AA, 1,989 QR, 0 MR) | Automated integration test |
| SC2 | UCH pipeline runs | Completes without errors, produces valid Excel | Automated integration test |
| SC3 | UCH classification rate | > 95% of 3,092 rows classified (not "unmapped") | Count from Summary sheet |
| SC4 | UCH Auto-Accept rate | > 90% after category mapping + keyword rules | Count from Summary sheet |
| SC5 | Config-only onboarding | Adding UCH required 0 changes to `categorize.py` | Git diff shows no changes to engine source |
| SC6 | Column optionality | Client with only `supplier` + `amount` runs without crash | Minimal client integration test |
| SC7 | Amount parsing | `"$5,567.76 "` parses to `5567.76` | Unit test |
| SC8 | Tier auto-detection | UCH config with no explicit tier config results in tiers 1,3,6,7 enabled; 2,4,5 disabled | Console output assertion in integration test |
| SC9 | Backward compatibility | v1 CCHMC config (unchanged) loads and runs correctly with deprecation notices | Integration test using original config file |
| SC10 | Onboarding time | Third client onboard in < 4 hours (config + mapping + first passing run) | Timed during next client engagement |

---

## Appendix A: UCH Data Sample

```csv
PO Number,Supplier,Category,PO Date,Subcategory,Capex/Opex,SuppliersFlag,SpendBand,  Spend Amount  ,Category Type,Location
UCH124749,GENERAL DATA COMPANY,Facilities,9/18/2024,Office Equipment & Supplies,OPEX,No,5K - 10K,"$5,567.76 ",In Scope,Cincinnati
UCH136564,GENERAL DATA COMPANY,Facilities,12/2/2024,Office Equipment & Supplies,OPEX,No,5K - 10K,"$8,463.52 ",In Scope,Cincinnati
DDC14390,JB DOPPES & SONS LUMBER CO,Facilities,11/20/2024,Building Maintenance,OPEX,No,2K - 5K,"$2,010.24 ",In Scope,Cincinnati
UCH135681,BARRY FARMER DRAPERIES INC,Facilities,11/22/2024,Furniture and Fixtures,OPEX,No,2K - 5K,"$2,648.00 ",In Scope,Cincinnati
```

## Appendix B: UCH Subcategory Values (Complete)

All 24 values present in the dataset:

1. Building Maintenance
2. Catering
3. Cleaning Supplies
4. Door Installation & Maintenance
5. Electrical Services
6. Environmental Services
7. Facilities Services
8. Fire
9. Flooring Services
10. Furniture and Fixtures
11. Grounds Maintenance
12. HVAC Installation & Maintenance
13. Interior Plant Services
14. Janitorial Services
15. Landscaping Services
16. Office Equipment & Supplies
17. Operating Supplies and Equipment
18. Painting Services
19. Pest Control
20. Plumbing Maintenance
21. Roof Maintenance
22. Service & Maintenance
23. Vehicle Maintenance
24. Window Cleaning Services

## Appendix C: CCHMC Column Headers (for reference)

46 columns in CCHMC's Workday export:

`Company, Supplier, Invoice Date, Invoice Number, Invoice Line, Spend Category, Line Memo, Invoice Amount, Invoice Line Amount, Requester, Created Moment, Cost Center, Fund, Funding Source, Grant, Program, Line of Service, Revenue Category, Spend Type, PO Type, Invoice Status, Payment Status, Payment Type, ...` (plus additional Workday-specific fields)
