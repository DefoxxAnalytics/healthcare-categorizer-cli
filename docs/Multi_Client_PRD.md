# PRD: Multi-Client Healthcare Categorization Engine

**Product**: Healthcare Categorization CLI v2.0
**Owner**: VTX Solutions / Defoxx Analytics
**Date**: 2026-02-14
**Status**: Draft

---

## 1. Problem Statement

The categorization engine (`categorize.py`, 614 lines) classifies healthcare procurement transactions against Healthcare Taxonomy v2.9 using a config-driven, 7-tier waterfall. It was built for a single client -- CCHMC (Workday ERP, SC codes). A second client, UCH (Oracle Fusion ERP, UNSPSC codes), needs to run through the same engine without code changes.

The engine cannot process UCH today. Here is exactly what breaks and where:

### 1.1 Breaking Points in categorize.py

| What Breaks | Where | Why |
|-------------|-------|-----|
| **All 6 columns required** | Line 51: `required_columns = ['spend_category', 'supplier', 'line_memo', 'line_of_service', 'cost_center', 'amount']` | UCH has no `Line of Service` equivalent. Config validation rejects any config missing it. |
| **CSV-only input** | Line 230: `df = pd.read_csv(paths['input'], low_memory=False)` | UCH data is in `uch-2026.xlsx` (Excel). `pd.read_csv()` will fail on an `.xlsx` file. |
| **Hardcoded column validation** | Lines 237-244: `required_csv_cols` dict includes `'line_of_service': cols['line_of_service']` | Crashes when `line_of_service` key is missing from config. |
| **Line of service Series creation** | Line 269: `line_of_service = df[cols['line_of_service']].fillna('').astype(str)` | KeyError when `line_of_service` is not in config. |
| **Output column reference** | Line 450: `output_columns[cols['line_of_service']] = df.get(cols['line_of_service'], ...)` | KeyError when `line_of_service` is not in config. |

### 1.2 What Works Without Changes

The sc_code_pattern is already config-driven (line 257-262). Swapping `((?:DNU\s+)?SC\d+)` for `(\d+)` requires zero code changes -- the regex is read from config and applied via `str.extract()`. The taxonomy lookup, tier waterfall logic, output schema, review tier assignment, and aggregation logic are all generic. The variable name `sc_code` is internal and works regardless of whether the extracted code is an SC code or a UNSPSC code.

### 1.3 Tier Compatibility: 6 of 7 Tiers Work

| Tier | Mechanism | UCH Has Prerequisites? | Status |
|------|-----------|----------------------|--------|
| 1: Category Code Mapping | Code lookup via regex extraction | YES -- extract UNSPSC code via `(\d+)` from `Category Name` | Works |
| 2: Supplier Refinement | Code + supplier regex | YES -- has both category codes and `Supplier` | Works |
| 3: Keyword Rules | Regex on supplier + description | YES -- has `Supplier` + `Item Description` | Works |
| 4: Context/LoS Refinement | Code + line of service | NO -- no `Line of Service` column | Disabled |
| 5: Cost Center Refinement | Code + cost center | YES -- has `Cost Center Description` (7 values) | Works |
| 6: Ambiguous Fallback | Ambiguous code lookup | YES -- has category codes | Works |
| 7: Supplier Override | Post-classification supplier check | YES -- has `Supplier` | Works |

The generalization gap is narrow: make one column optional, add Excel input support, and UCH runs through 6 of 7 tiers.

---

## 2. Data Comparison: CCHMC vs UCH

### 2.1 Dataset Overview

| Dimension | CCHMC (Workday) | UCH (Oracle Fusion) |
|-----------|-----------------|---------------------|
| File | `cchmc-ftp-new.csv` | `uch-2026.xlsx` |
| Format | CSV | Excel (.xlsx) |
| Rows | 596,796 | 4,649 |
| Columns | 46 | 44 |
| ERP System | Workday | Oracle Fusion |
| Total Spend | ~$1.2B | $20.47M |

### 2.2 Classification-Relevant Columns

| Engine Concept | CCHMC Column | UCH Column | Notes |
|----------------|-------------|------------|-------|
| Category source | `Spend Category` | `Category Name` | Both contain code + description in a single field |
| Code format | SC codes: `SC0250`, `DNU SC0175` | UNSPSC codes: `99000038`, `39101612` | Different regex, same extraction mechanism |
| Code extraction regex | `((?:DNU\s+)?SC\d+)` | `(\d+)` | Config-driven, no code change |
| Unique codes | 326 | 118 | |
| Supplier | `Supplier` | `Supplier` | Identical column name |
| Unique suppliers | ~10,000+ | 294 | |
| Description | `Line Memo` | `Item Description` | Same concept, different column name |
| Unique descriptions | ~200,000+ | 4,155 | Rich text in both cases |
| Line of Service | `Line of Service` | **N/A** | UCH has no equivalent |
| Cost Center | `Cost Center` | `Cost Center Description` | CCHMC: many values; UCH: 7 values |
| Amount | `Invoice Line Amount` (float64) | `Paid Amount` (float64) | Both already numeric -- no parsing needed |

### 2.3 UCH-Specific Columns (Not in CCHMC)

| Column | Unique Values | Example | Potential Use |
|--------|--------------|---------|---------------|
| `Line Type` | 4 | Goods, Fixed Price Services, Capital Services, Internal | Tier 4 proxy candidate |
| `Organization Code` | 4 | DANIELDRAKECENT, WESTCHESTERHOSP, UCMEDICALCENTER, UCHEALTH | Site-level segmentation |
| `Manufacturer` | 198 (74.3% null) | SYLVANIA, EATON | Refine generic categories when present |
| `Account Code` | 29 | GL codes | Accounting-driven signal |
| `Location Code` | multiple | UC MEDICAL CENTER MAIN | Facility-level context |
| `Manufacturer Part Number` | varies | Part-level identification | |

### 2.4 UCH Dead Columns (100% Null)

- Agreement Sub Type
- Agreement Type
- UNSPSC Category Name
- UNSPSC Category Description
- Tecsys Order Line number

### 2.5 UCH Data Characteristics

- **`Paid Amount`**: float64, range $0 to ~$1M, total $20.47M. Already numeric -- no currency string parsing needed.
- **Column names are clean**: No whitespace padding, no encoding issues.
- **`39101612-Incandescent Lamps and Bulbs`**: 37.6% of all rows (1,750/4,649). This is almost certainly a catch-all bucket, not actually all lamps. Must be treated as ambiguous in the mapping file, then refined via supplier/keyword/cost-center tiers.
- **Top supplier dominance**: GRAINGER INC accounts for 30.9% of rows (1,436/4,649).

---

## 3. Goals

| ID | Goal |
|----|------|
| G1 | Process UCH's Oracle Fusion export (4,649 rows, 44 columns, UNSPSC codes) via config and reference YAML only -- no engine code changes after refactoring |
| G2 | Preserve CCHMC behavior exactly (zero regression) |
| G3 | Support clients with any subset of classification columns -- `line_of_service` is optional |
| G4 | Support UNSPSC codes (not just SC codes) via config-driven regex extraction |
| G5 | Support XLSX input files in addition to CSV |
| G6 | Onboard a new client with structured category codes and item descriptions in < 4 hours (config + reference YAML, no code changes) |

## 4. Non-Goals

| ID | Non-Goal | Reason |
|----|----------|--------|
| NG1 | ML/NLP-based classification | Engine is rule-based by design |
| NG2 | Real-time or streaming classification | Batch CLI tool |
| NG3 | GUI or web interface | CLI-only for v2 |
| NG4 | Currency string parsing | Both CCHMC and UCH have float64 amounts. Build when a client actually needs it. |
| NG5 | Renaming `sc_code` to `category_code` throughout the engine | Internal naming is cosmetic. The engine works with any regex pattern regardless of what the codes are called internally. |
| NG6 | Composite or verbatim code extraction modes | UCH has real UNSPSC codes extractable via simple regex. Standard `str.extract()` handles it. |
| NG7 | Auto-detection of available tiers | Explicit config is more predictable. Tier 4 skips when its column is absent -- that is sufficient. |

---

## 5. Functional Requirements

### 5.1 Column Optionality

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-100 | `columns.line_of_service` is optional. If absent or `null` in config, Tier 4 (context refinement) is skipped. | P0 |
| FR-101 | All other column mappings (`spend_category`, `supplier`, `line_memo`, `cost_center`, `amount`) remain required. | P0 |
| FR-102 | When `line_of_service` is omitted, the engine prints a notice: `Tier 4 (context refinement): disabled -- no line_of_service column` and continues. | P0 |
| FR-103 | When `line_of_service` is mapped to a column name that does not exist in the input data, the engine raises `ConfigError` (same behavior as any other missing column). | P0 |
| FR-104 | When `line_of_service` is absent, the engine creates an empty `pd.Series('', index=df.index)` internally so downstream code that references the variable does not crash. | P0 |

### 5.2 Category Code Generalization

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-110 | `classification.sc_code_pattern` is the config key for the regex applied to the `spend_category` column to extract the category code. This key name is unchanged. | P0 |
| FR-111 | CCHMC config: pattern `((?:DNU\s+)?SC\d+)` extracts `SC0250` from `"SC0250 - Professional Services"`. No change to CCHMC behavior. | P0 |
| FR-112 | UCH config: pattern `(\d+)` extracts `99000038` from `"99000038-Equipment Maintenance Services"`. | P0 |
| FR-113 | If the regex produces no match for a row, the full `spend_category` string is used as the code (current fallback behavior on line 265, unchanged). | P0 |
| FR-114 | The mapping file (`sc_code_mapping.yaml`) uses extracted code strings as keys. CCHMC keys: `SC0250`, `DNU SC0175`. UCH keys: `99000038`, `39101612`. Same YAML structure, different key values. | P0 |

### 5.3 Input Format Support

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-120 | If `paths.input` ends in `.xlsx` or `.xls`, the engine calls `pd.read_excel()` instead of `pd.read_csv()`. | P0 |
| FR-121 | New optional config key: `paths.input_sheet` (string). When present and input is Excel, passed as the `sheet_name` parameter to `pd.read_excel()`. Defaults to the first sheet (index 0) when omitted. | P0 |
| FR-122 | CSV input behavior is completely unchanged. Detection is based solely on file extension. | P0 |
| FR-123 | The `--input` CLI override also respects file extension detection (`.xlsx` -> `read_excel`, `.csv` -> `read_csv`). | P0 |

### 5.4 Tier Configuration

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-130 | When `columns.line_of_service` is absent or `null`, Tier 4's loop body is skipped entirely. `tier4_count` is reported as 0 in console output. | P0 |
| FR-131 | When `columns.line_of_service` is present and mapped, Tier 4 runs exactly as it does today. | P0 |
| FR-132 | No other tier's behavior changes based on `line_of_service` availability. Tiers 1, 2, 3, 5, 6, 7 are unaffected. | P0 |
| FR-133 | The refinement rules file for a client without `line_of_service` should have `context_rules: []` (empty list). The engine must not crash on an empty list. | P0 |

### 5.5 Shared vs Per-Client Reference Data

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-140 | Taxonomy file (`Healthcare Taxonomy v2.9.xlsx`) is shared across all clients. Path resolved relative to config file location. | P0 |
| FR-141 | `sc_code_mapping.yaml`, `keyword_rules.yaml`, and refinement rules YAML are per-client. Each client directory has its own set. | P0 |
| FR-142 | UCH's `sc_code_mapping.yaml` uses UNSPSC codes as keys with the same YAML structure as CCHMC's. 118 unique codes need mapping entries. | P0 |

### 5.6 Output Schema

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-150 | Classification output columns are unchanged: `CategoryLevel1` through `CategoryLevel5`, `TaxonomyKey`, `ClassificationMethod`, `Confidence`, `ReviewTier`. | P0 |
| FR-151 | When `line_of_service` is absent, the output omits that column (no empty column header for a nonexistent source column). The `Spend Category (Source)` and `SC Code` columns are always present. | P0 |
| FR-152 | `SC Code` output column contains the extracted code regardless of code system (UNSPSC or SC). The label is cosmetic; the data is always the regex extraction result. | P0 |
| FR-153 | Passthrough columns from config are carried through as-is. UCH passes through columns like `Order`, `Category Name`, `Line Type`, `Organization Code`, `Location Code`, etc. | P0 |

### 5.7 Config Validation

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-160 | Config validation checks required sections: `client`, `paths`, `columns`, `classification`. No change. | P0 |
| FR-161 | Config validation checks required columns: `spend_category`, `supplier`, `line_memo`, `cost_center`, `amount`. `line_of_service` is removed from the required list. | P0 |
| FR-162 | Config validation checks required paths: `input`, `sc_mapping`, `taxonomy`, `keyword_rules`, `refinement_rules`, `output_dir`, `output_prefix`. No change. `input_sheet` is optional. | P0 |
| FR-163 | Config validation checks required classification params: `sc_code_pattern`, `confidence_high`, `confidence_medium`. No change. | P0 |

---

## 6. Config Schema v2

### 6.1 Schema Definition

```yaml
# --- Required sections ---
client:
  name: string        # required, client identifier
  description: string # required, human-readable description

paths:
  input: string              # required, path to input file (.csv, .xlsx, .xls)
  input_sheet: string        # optional, Excel sheet name (default: first sheet)
  sc_mapping: string         # required, path to category code mapping YAML
  taxonomy: string           # required, path to taxonomy Excel file
  keyword_rules: string      # required, path to keyword rules YAML
  refinement_rules: string   # required, path to refinement rules YAML
  output_dir: string         # required, output directory
  output_prefix: string      # required, output file prefix

columns:
  spend_category: string     # required, column containing category code + description
  supplier: string           # required, column containing supplier name
  line_memo: string          # required, column containing item description
  line_of_service: string    # OPTIONAL, column containing line of service (null or omitted to disable Tier 4)
  cost_center: string        # required, column containing cost center
  amount: string             # required, column containing transaction amount (must be numeric)
  passthrough: list[string]  # optional, additional columns to carry through to output

classification:
  sc_code_pattern: string    # required, regex to extract category code from spend_category column
  confidence_high: float     # required, threshold for Auto-Accept (e.g., 0.7)
  confidence_medium: float   # required, threshold for Quick Review (e.g., 0.5)

aggregations:                # optional, list of dynamic aggregation sheets
  - name: string             # sheet name
    column: string           # column to group by
    top_n: int | null         # limit rows (null = all)
```

### 6.2 CCHMC Config (Backwards Compatible -- No Changes)

```yaml
client:
  name: "CCHMC"
  description: "Cincinnati Children's Hospital Medical Center - Workday AP/Procurement"

paths:
  input: "data/input/cchmc-ftp-new.csv"
  sc_mapping: "data/reference/sc_code_mapping.yaml"
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
  sc_code_pattern: '((?:DNU\s+)?SC\d+)'
  confidence_high: 0.7
  confidence_medium: 0.5

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

### 6.3 UCH Config (New)

```yaml
client:
  name: "UCH"
  description: "UC Health - Oracle Fusion Procurement (Facilities)"

paths:
  input: "data/input/uch-2026.xlsx"
  input_sheet: "Org Data Pull"
  sc_mapping: "data/reference/sc_code_mapping.yaml"
  taxonomy: "../../shared/reference/Healthcare Taxonomy v2.9.xlsx"
  keyword_rules: "data/reference/keyword_rules.yaml"
  refinement_rules: "data/reference/uch_refinement_rules.yaml"
  output_dir: "output"
  output_prefix: "uch_categorization_results"

columns:
  spend_category: "Category Name"
  supplier: "Supplier"
  line_memo: "Item Description"
  # line_of_service: omitted -- UCH has no Line of Service equivalent
  cost_center: "Cost Center Description"
  amount: "Paid Amount"
  passthrough:
    - "Order"
    - "Requisition"
    - "Category Name"
    - "Item Name"
    - "Line Type"
    - "Organization Code"
    - "Location Code"
    - "Location Address"
    - "Cost Center Code"
    - "Account Code"
    - "Purchase Order Amount"
    - "PO Line Amount"
    - "Price"
    - "UOM"
    - "Manufacturer"
    - "Manufacturer Part Number"
    - "Supplier Item"
    - "Purchase Requestor Display Name"
    - "Full Name"
    - "Creation Date"

classification:
  sc_code_pattern: '(\d+)'
  confidence_high: 0.7
  confidence_medium: 0.5

aggregations:
  - name: "Spend by Cost Center"
    column: "Cost Center Description"
    top_n: null
  - name: "Spend by Organization"
    column: "Organization Code"
    top_n: null
  - name: "Spend by Line Type"
    column: "Line Type"
    top_n: null
  - name: "Spend by Location (Top 25)"
    column: "Location Code"
    top_n: 25
```

### 6.4 Config Differences Side-by-Side

| Config Key | CCHMC | UCH | Why |
|------------|-------|-----|-----|
| `paths.input` | `.csv` | `.xlsx` | Different ERP export format |
| `paths.input_sheet` | *(absent)* | `"Org Data Pull"` | Excel requires sheet name |
| `columns.spend_category` | `"Spend Category"` | `"Category Name"` | Different ERP column naming |
| `columns.line_memo` | `"Line Memo"` | `"Item Description"` | Different ERP column naming |
| `columns.line_of_service` | `"Line of Service"` | *(absent)* | UCH has no equivalent column |
| `columns.cost_center` | `"Cost Center"` | `"Cost Center Description"` | Different ERP column naming |
| `columns.amount` | `"Invoice Line Amount"` | `"Paid Amount"` | Different ERP column naming |
| `classification.sc_code_pattern` | `((?:DNU\s+)?SC\d+)` | `(\d+)` | UNSPSC codes vs SC codes |

### 6.5 UCH SC Code Mapping File (Structure)

UCH's `sc_code_mapping.yaml` uses the same YAML structure as CCHMC's, with UNSPSC numeric codes as keys:

```yaml
mappings:
  "99000038":
    name: "Equipment Maintenance Services"
    taxonomy_key: "Facilities > Facilities Services > Equipment Maintenance"
    confidence: 0.90
    ambiguous: false

  "39101612":
    name: "Incandescent Lamps and Bulbs"
    taxonomy_key: "Facilities > Operating Supplies and Equipment > Lighting"
    confidence: 0.70
    ambiguous: true    # 37.6% of rows -- catch-all bucket, NOT actually all lamps

  "46182402":
    name: "Parts"
    taxonomy_key: "Facilities > Operating Supplies and Equipment > Parts & Components"
    confidence: 0.75
    ambiguous: true    # generic "Parts" needs supplier/keyword refinement

  "31160000":
    name: "Hardware"
    taxonomy_key: "Facilities > Operating Supplies and Equipment > Hardware"
    confidence: 0.80
    ambiguous: false

  "99000059":
    name: "Infrastructure Services"
    taxonomy_key: "Facilities > Facilities Services > Infrastructure"
    confidence: 0.85
    ambiguous: false

  "99999999":
    name: "Default Category"
    taxonomy_key: "Unclassified"
    confidence: 0.30
    ambiguous: true
```

118 unique UNSPSC codes need mapping entries. Code `39101612` (37.6% of rows) should be marked `ambiguous: true` so it falls through to Tiers 2-5 for refinement rather than being blindly assigned as "Lamps and Bulbs."

### 6.6 UCH Refinement Rules File (Structure)

```yaml
supplier_rules:
  - sc_codes: ["39101612"]    # "Incandescent Lamps and Bulbs" catch-all
    supplier_pattern: "GRAINGER"
    taxonomy_key: "Facilities > Operating Supplies and Equipment > MRO Supplies"
    confidence: 0.90

  - sc_codes: ["46182402"]    # "Parts"
    supplier_pattern: "MCMASTER"
    taxonomy_key: "Facilities > Operating Supplies and Equipment > Hardware & Fasteners"
    confidence: 0.88

context_rules: []   # No line_of_service available; empty list required

cost_center_rules:
  - sc_codes: ["99000038"]    # Equipment Maintenance Services
    cost_center_pattern: "ELECTRICAL"
    taxonomy_key: "Facilities > Facilities Services > Electrical Maintenance"
    confidence: 0.88

  - sc_codes: ["99000038"]
    cost_center_pattern: "MECHANICAL"
    taxonomy_key: "Facilities > Facilities Services > Mechanical Maintenance"
    confidence: 0.88

supplier_override_rules:
  - supplier_pattern: "OTIS ELEVATOR"
    override_from_l1: ["Facilities"]
    taxonomy_key: "Facilities > Facilities Services > Elevator Maintenance"
    confidence: 0.95

  - supplier_pattern: "JOHNSON CONTROLS FIRE"
    override_from_l1: ["Facilities"]
    taxonomy_key: "Facilities > Facilities Services > Fire Protection"
    confidence: 0.95
```

---

## 7. Data Model

### 7.1 Internal Transaction Model

The engine maps client columns to internal pandas Series variables. This mapping is config-driven via the `columns` section. The internal variable names do not change between clients.

| Internal Variable | Type | Required | CCHMC Source Column | UCH Source Column |
|-------------------|------|----------|---------------------|-------------------|
| `spend_cat_str` | `str` | Yes | `Spend Category` | `Category Name` |
| `sc_code` | `str` | Derived | Regex `((?:DNU\s+)?SC\d+)` yields `SC0250` | Regex `(\d+)` yields `99000038` |
| `supplier` | `str` | Yes | `Supplier` | `Supplier` |
| `line_memo` | `str` | Yes | `Line Memo` | `Item Description` |
| `line_of_service` | `str` | **Optional** | `Line of Service` | *absent -- empty Series* |
| `cost_center` | `str` | Yes | `Cost Center` | `Cost Center Description` |
| `amount` | `float64` | Yes | `Invoice Line Amount` | `Paid Amount` |
| `combined_text` | `str` | Derived | `supplier + " " + line_memo` | `supplier + " " + item_description` |

### 7.2 Code Extraction Flow

```
CCHMC:
  "SC0250 - Professional Services"
    --> regex ((?:DNU\s+)?SC\d+) --> "SC0250"
    --> sc_code_mapping.yaml["SC0250"] --> taxonomy_key

UCH:
  "99000038-Equipment Maintenance Services"
    --> regex (\d+) --> "99000038"
    --> sc_code_mapping.yaml["99000038"] --> taxonomy_key

  "39101612-Incandescent Lamps and Bulbs"
    --> regex (\d+) --> "39101612"
    --> sc_code_mapping.yaml["39101612"].ambiguous == true
    --> falls through to Tier 2/3/5 for refinement
```

The engine code on line 262 (`spend_cat_str.str.extract(f'({sc_pattern})', expand=False)`) wraps the config pattern in an additional capture group. Both `((?:DNU\s+)?SC\d+)` and `(\d+)` produce a single match group via `str.extract()`. No code change needed.

---

## 8. Classification Architecture

### 8.1 Current Engine Flow

```
categorize.py main() (line 183)
  |
  +-- Line 261-265: Extract code from spend_category via sc_code_pattern regex
  |
  +-- Lines 277-284: Tier 1 -- Non-ambiguous code lookup in sc_mapping
  |     Result: taxonomy_key, method='sc_code_mapping', confidence from mapping
  |
  +-- Lines 289-308: Tier 2 -- Supplier refinement (code + supplier regex)
  |     Scoped by rule['sc_codes'], matches supplier column
  |
  +-- Lines 311-326: Tier 3 -- Keyword rules on combined_text (supplier + line_memo)
  |     Pattern match on combined supplier + description text
  |
  +-- Lines 328-348: Tier 4 -- Context refinement (code + line_of_service)
  |     [CHANGE NEEDED: Guard clause when line_of_service absent]
  |
  +-- Lines 350-370: Tier 5 -- Cost center refinement (code + cost_center)
  |     Scoped by rule['sc_codes'], matches cost_center column
  |
  +-- Lines 372-379: Tier 6 -- Ambiguous code fallback
  |     Maps ambiguous codes to default taxonomy keys
  |
  +-- Lines 402-421: Tier 7 -- Supplier override (post-classification)
  |     Overrides L1 assignment based on supplier patterns
  |
  +-- Lines 423-429: Review tier assignment (Auto-Accept / Quick Review / Manual Review)
  +-- Lines 434-574: Output Excel construction (All Results, Manual Review, Quick Review, Summary, aggregations)
```

### 8.2 Proposed Changes

Only four changes to `categorize.py`:

**Change 1: Column optionality (line 51)**

```python
# Current
required_columns = ['spend_category', 'supplier', 'line_memo', 'line_of_service', 'cost_center', 'amount']

# Proposed
required_columns = ['spend_category', 'supplier', 'line_memo', 'cost_center', 'amount']
optional_columns = ['line_of_service']
```

**Change 2: Column validation (lines 237-244)**

```python
# Current
required_csv_cols = {
    'line_of_service': cols['line_of_service'],
    ...
}

# Proposed
required_csv_cols = {k: cols[k] for k in required_columns if k in cols}
if cols.get('line_of_service'):
    required_csv_cols['line_of_service'] = cols['line_of_service']
```

**Change 3: Line of service Series (line 269)**

```python
# Current
line_of_service = df[cols['line_of_service']].fillna('').astype(str)

# Proposed
has_line_of_service = bool(cols.get('line_of_service'))
if has_line_of_service:
    line_of_service = df[cols['line_of_service']].fillna('').astype(str)
else:
    line_of_service = pd.Series('', index=df.index, dtype='object')
```

**Change 4: Tier 4 guard (line 329)**

```python
# Current
tier4_count = 0
for rule in refinement['context_rules']:
    ...

# Proposed
tier4_count = 0
if has_line_of_service:
    for rule in refinement['context_rules']:
        ...
else:
    print("  Tier 4 (context refinement): disabled -- no line_of_service column")
```

**Change 5: Input format detection (line 230)**

```python
# Current
df = pd.read_csv(paths['input'], low_memory=False)

# Proposed
input_path = paths['input']
if input_path.suffix in ('.xlsx', '.xls'):
    sheet = config['paths'].get('input_sheet', 0)
    df = pd.read_excel(input_path, sheet_name=sheet)
else:
    df = pd.read_csv(input_path, low_memory=False)
```

**Change 6: Output line_of_service column (line 450)**

```python
# Current
output_columns[cols['line_of_service']] = df.get(cols['line_of_service'], pd.Series('', index=df.index))

# Proposed
if cols.get('line_of_service'):
    output_columns[cols['line_of_service']] = df.get(cols['line_of_service'], pd.Series('', index=df.index))
```

### 8.3 How UCH Gets Classified Through the Waterfall

```
Input: uch-2026.xlsx, sheet "Org Data Pull", 4,649 rows

Step 1 -- Code extraction:
  regex (\d+) applied to "Category Name" column
  "99000038-Equipment Maintenance Services" --> "99000038"
  "39101612-Incandescent Lamps and Bulbs"   --> "39101612"
  "31160000-Hardware"                        --> "31160000"
  118 unique codes extracted

Step 2 -- Tier 1 (category code mapping):
  Non-ambiguous UNSPSC codes mapped directly.
  Codes like 99000038, 31160000, 99000059 resolved here.
  Ambiguous codes (39101612 catch-all, 46182402 Parts, 99999999 Default) skip to later tiers.

Step 3 -- Tier 2 (supplier refinement):
  Ambiguous code + supplier pattern matching.
  e.g., code "39101612" + supplier "GRAINGER" --> MRO Supplies
  e.g., code "46182402" + supplier "MCMASTER" --> Hardware & Fasteners

Step 4 -- Tier 3 (keyword rules):
  Regex on Supplier + Item Description.
  e.g., "GRAINGER.*LAMP" on combined text --> Lighting
  e.g., "REPAIR.*FREEZER" --> Refrigeration Maintenance

Step 5 -- Tier 4: SKIPPED (no line_of_service column configured)

Step 6 -- Tier 5 (cost center refinement):
  Code + cost center pattern matching.
  e.g., code "99000038" + cost center "ELECTRICAL SERVICES" --> Electrical Maintenance
  e.g., code "99000038" + cost center "MECHANICAL SERVICES" --> Mechanical Maintenance

Step 7 -- Tier 6 (ambiguous fallback):
  Remaining rows with ambiguous codes get default taxonomy assignment.
  e.g., code "99999999" (8 rows) --> Unclassified

Step 8 -- Tier 7 (supplier override):
  Post-classification supplier corrections.
  e.g., supplier "OTIS ELEVATOR" in Facilities L1 --> Elevator Maintenance
  e.g., supplier "JOHNSON CONTROLS FIRE" in Facilities L1 --> Fire Protection

Step 9 -- Review tier assignment:
  Auto-Accept: high confidence, direct mapping or rule match
  Quick Review: medium confidence
  Manual Review: low confidence
```

### 8.4 Tier Prerequisite Table

| Tier | Required Config Keys | Required Data Columns | Required Rule Sections |
|------|---------------------|-----------------------|----------------------|
| 1 | `columns.spend_category`, `classification.sc_code_pattern`, `paths.sc_mapping` | Category source column | `sc_code_mapping.yaml` with non-ambiguous entries |
| 2 | `columns.supplier`, `paths.refinement_rules` | Supplier column | `supplier_rules` in refinement YAML |
| 3 | `columns.supplier`, `columns.line_memo`, `paths.keyword_rules` | Supplier + description columns | `keyword_rules.yaml` |
| 4 | `columns.line_of_service` (optional), `paths.refinement_rules` | Line of service column | `context_rules` in refinement YAML |
| 5 | `columns.cost_center`, `paths.refinement_rules` | Cost center column | `cost_center_rules` in refinement YAML |
| 6 | `columns.spend_category`, `classification.sc_code_pattern`, `paths.sc_mapping` | Category source column | `sc_code_mapping.yaml` with ambiguous entries |
| 7 | `columns.supplier`, `paths.refinement_rules` | Supplier column | `supplier_override_rules` in refinement YAML |

---

## 9. Test Strategy

### 9.1 Test Categories

| Category | Scope | Trigger |
|----------|-------|---------|
| CCHMC regression | Full pipeline, assert exact tier counts | Every engine change |
| UCH integration | Full pipeline with UCH config and data | Every engine change |
| Config validation | Optional column handling, Excel input detection | Every engine change |
| Rule validation | Per-client sc_code_mapping and refinement rule integrity | Every rule file change |

### 9.2 CCHMC Regression Tests

```
test_cchmc_total_rows:           assert total == 596,796
test_cchmc_auto_accept_count:    assert auto_accept == 594,807
test_cchmc_quick_review_count:   assert quick_review == 1,989
test_cchmc_manual_review_count:  assert manual_review == 0
test_cchmc_unmapped_count:       assert unmapped == 0
test_cchmc_output_columns:       all expected columns present including Line of Service
test_cchmc_tier4_runs:           tier4_count > 0 (context refinement active)
```

### 9.3 UCH Integration Tests

```
test_uch_loads_excel:            pd.read_excel called with sheet_name="Org Data Pull"
test_uch_total_rows:             assert total == 4,649
test_uch_no_crash:               pipeline completes without exception
test_uch_code_extraction:        all codes match (\d+), extracted from "Category Name"
test_uch_amount_is_numeric:      Paid Amount column is float64, no NaN from parsing
test_uch_tier4_skipped:          console output includes "Tier 4 (context refinement): disabled"
test_uch_tier5_runs:             cost center refinement produces > 0 classified rows
test_uch_has_passthrough:        "Order", "Line Type", "Organization Code" present in output
test_uch_classification_rate:    < 5% unmapped after mapping 118 UNSPSC codes
test_uch_total_spend:            output total Paid Amount ~= $20,469,256.49 (within $0.01)
test_uch_no_line_of_service_col: "Line of Service" column NOT in output (UCH doesn't have it)
```

### 9.4 Config Validation Tests

```
test_config_no_line_of_service:      omit line_of_service from columns --> loads OK, notice printed
test_config_null_line_of_service:    set line_of_service: null --> same behavior as omitted
test_config_xlsx_input:              paths.input ends in .xlsx --> engine calls read_excel
test_config_xlsx_with_sheet:         paths.input_sheet = "Org Data Pull" --> passed to read_excel
test_config_csv_input_unchanged:     paths.input ends in .csv --> engine calls read_csv (no regression)
test_config_missing_supplier:        omit columns.supplier --> ConfigError
test_config_missing_amount:          omit columns.amount --> ConfigError
test_config_missing_spend_category:  omit columns.spend_category --> ConfigError
test_config_bad_column_mapping:      columns.supplier = "Nonexistent" --> ConfigError at data load
```

### 9.5 Per-Client Rule Validation

| Test | CCHMC | UCH |
|------|-------|-----|
| All sc_mapping keys are strings | `SC0250` format | `99000038` format |
| All sc_mapping taxonomy_keys exist in taxonomy | Same check | Same check |
| All refinement rule sc_codes exist in mapping | Same check | Same check |
| Keyword rule regexes compile | Same check | Same check |
| Refinement rule regexes compile | Same check | Same check |
| context_rules section | 8+ rules | 0 rules (empty list) |
| Ambiguous codes have refinement rules | SC codes with `ambiguous: true` | `39101612`, `46182402`, `99999999` have refinement paths |

---

## 10. Migration Path

### Phase 1: Make `line_of_service` Optional

**Goal**: The engine accepts configs without `line_of_service` and skips Tier 4 gracefully.

**Changes to `categorize.py`**:

1. Line 51: Remove `'line_of_service'` from `required_columns` list.
2. Lines 237-244: Build `required_csv_cols` dict only from columns present in config.
3. Line 269: Guard `line_of_service` Series creation with `cols.get('line_of_service')` check.
4. Line 329: Wrap Tier 4 loop in `if has_line_of_service:` guard.
5. Line 450: Guard output column reference for `line_of_service`.

**Verification**: Run CCHMC regression. Output must be byte-identical.

**Estimated effort**: 2-3 hours.

### Phase 2: Add Excel Input Support

**Goal**: The engine reads `.xlsx` files when configured.

**Changes to `categorize.py`**:

1. Line 230: Detect file extension and dispatch to `pd.read_excel()` or `pd.read_csv()`.
2. Read `paths.input_sheet` from config when present.

**Verification**: Run CCHMC regression (CSV input, unchanged). Manually test with an `.xlsx` file.

**Estimated effort**: 1-2 hours.

### Phase 3: UCH Onboarding

**Goal**: First non-CCHMC client runs successfully through the engine.

1. Create `clients/uch/` directory structure mirroring `clients/cchmc/`.
2. Write UCH `config.yaml` per Section 6.3.
3. Create `sc_code_mapping.yaml` with 118 UNSPSC code mappings to taxonomy keys.
   - Mark `39101612` as `ambiguous: true` (37.6% catch-all bucket).
   - Mark `46182402` (Parts) and `99999999` (Default Category) as `ambiguous: true`.
4. Write UCH-specific keyword rules (supplier + item description patterns for the 294 suppliers).
5. Write UCH-specific refinement rules (supplier, cost center, supplier override sections).
6. Run UCH pipeline. Iterate until classification rate > 95%.
7. Write UCH integration tests per Section 9.3.

**Estimated effort**: 8-12 hours (dominated by rule authoring for 118 UNSPSC codes and 294 suppliers).

### Phase 4: Validation and Hardening

**Goal**: Both clients pass all tests, output is verified.

1. Run CCHMC regression suite -- zero delta.
2. Run UCH integration suite -- all pass.
3. Run config validation suite -- all pass.
4. Verify UCH total spend reconciles to $20,469,256.49.
5. Review UCH unmapped rows and author additional rules if needed.

**Estimated effort**: 2-3 hours.

### Total Migration Effort: 13-20 hours

| Phase | Hours | Description |
|-------|-------|-------------|
| Phase 1 | 2-3 | Column optionality |
| Phase 2 | 1-2 | Excel input support |
| Phase 3 | 8-12 | UCH onboarding (rule authoring dominates) |
| Phase 4 | 2-3 | Validation and hardening |
| **Total** | **13-20** | |

---

## 11. Success Criteria

| ID | Metric | Target | Measurement |
|----|--------|--------|-------------|
| SC1 | CCHMC zero regression | Identical tier counts before and after refactoring | Automated regression test |
| SC2 | UCH pipeline completes | No errors, valid Excel output | Automated integration test |
| SC3 | UCH classification rate | > 95% of 4,649 rows classified (not "unmapped") | Summary sheet |
| SC4 | UCH Auto-Accept rate | > 85% after UNSPSC mapping + refinement rules | Summary sheet |
| SC5 | UCH total spend reconciliation | Output total matches $20,469,256.49 within $0.01 | Summary sheet financial total |
| SC6 | Config-only onboarding | UCH required 0 changes to tier logic, output construction, or review assignment | Git diff of categorize.py |
| SC7 | Engine changes are minimal | < 30 lines changed in `categorize.py` (excluding comments) | Line count of diff |
| SC8 | Tier 4 graceful skip | UCH run reports Tier 4 disabled, no crash, no misclassification | Console output assertion |
| SC9 | Excel input works | UCH `.xlsx` with sheet name loads correctly, 4,649 rows | Row count assertion |
| SC10 | Third-client onboarding estimate | < 4 hours for a client with structured category codes and item descriptions | Timed during next engagement |

---

## Appendix A: UCH Data Sample

```
Order: PO-12345
Supplier: GRAINGER INC
Category Name: 39101612-Incandescent Lamps and Bulbs
Item Description: LED TUBE LAMP T8 48IN 15W 4000K FROSTED
Item Name: LED TUBE LAMP
Cost Center Code: 10020
Cost Center Description: MAINTENANCE
Line Type: Goods
Organization Code: UCMEDICALCENTER
Location Code: UC MEDICAL CENTER MAIN
Paid Amount: 156.80
Price: 15.68
UOM: Each
Manufacturer: SYLVANIA
```

## Appendix B: UCH UNSPSC Categories (118 Unique -- Top 20 by Row Count)

| Code | Description | Rows | % | Treatment |
|------|-------------|------|---|-----------|
| `39101612` | Incandescent Lamps and Bulbs | 1,750 | 37.6% | **Ambiguous** -- catch-all bucket, needs supplier/keyword refinement |
| `99000038` | Equipment Maintenance Services | 773 | 16.6% | Direct mapping, cost center refinement |
| `46182402` | Parts | 447 | 9.6% | **Ambiguous** -- generic, needs supplier refinement |
| `31160000` | Hardware | 382 | 8.2% | Direct mapping |
| `99000059` | Infrastructure Services | 220 | 4.7% | Direct mapping |
| `72101507` | Building Maintenance or Repair | 116 | 2.5% | Direct mapping |
| `99000072` | Mechanical Services | 93 | 2.0% | Direct mapping |
| `99000015` | Capital Projects | 83 | 1.8% | Direct mapping |
| `27112800` | Paints and Primers | 70 | 1.5% | Direct mapping |
| `72102900` | Plumbing | 65 | 1.4% | Direct mapping |
| `40141700` | Pipe Fittings | 48 | 1.0% | Direct mapping |
| `99000069` | Elevator Maintenance | 38 | 0.8% | Direct mapping |
| `73152100` | Pest Control | 35 | 0.8% | Direct mapping |
| `72151500` | Electrical Services | 34 | 0.7% | Direct mapping |
| `56101500` | Seating | 29 | 0.6% | Direct mapping |
| `30171500` | Doors and Frames | 28 | 0.6% | Direct mapping |
| `99000067` | Waste Management | 25 | 0.5% | Direct mapping |
| `76111500` | Cleaning and Janitorial Services | 24 | 0.5% | Direct mapping |
| `99000043` | Security Services | 22 | 0.5% | Direct mapping |
| `72151800` | HVAC Services | 22 | 0.5% | Direct mapping |

Top 5 codes cover 76.8% of all rows. Standard UNSPSC codes (`31xxxxxx`, `39xxxxxx`, `46xxxxxx`) coexist with custom/internal codes prefixed `99xxxxxx`.

## Appendix C: UCH Cost Centers (All 7)

| Cost Center Description | Row Count | % |
|------------------------|-----------|---|
| MAINTENANCE | 3,143 | 67.6% |
| MECHANICAL SERVICES | 774 | 16.6% |
| GROUNDS & MOVERS | 222 | 4.8% |
| EMERGENCY MAINTENANCE | 187 | 4.0% |
| BUILDING SERVICES | 181 | 3.9% |
| ELECTRICAL SERVICES | 84 | 1.8% |
| PLANT OPERATIONS | 58 | 1.2% |

## Appendix D: UCH Top Suppliers

**By row count:**

| Supplier | Rows | % |
|----------|------|---|
| GRAINGER INC | 1,436 | 30.9% |
| FD LAWRENCE ELECTRIC CO | 328 | 7.1% |
| MCMASTER-CARR | 253 | 5.4% |
| EMCOR SERVICES TEAM MECHANICAL | 181 | 3.9% |
| CERTIFIED LABS | 120 | 2.6% |

**By spend:**

| Supplier | Total Spend |
|----------|-------------|
| USI INC | ~$1.2M |
| EMCOR SERVICES | ~$1.1M |
| OTIS ELEVATOR | ~$910K |
| JOHNSON CONTROLS FIRE PROTECTION | ~$900K |
| CERTIFIED LABS | ~$650K |

## Appendix E: UCH Dead Columns (100% Null)

These columns exist in the Excel file but contain no data:
- Agreement Sub Type
- Agreement Type
- UNSPSC Category Name
- UNSPSC Category Description
- Tecsys Order Line number

## Appendix F: CCHMC Column Headers (Reference)

46 columns in CCHMC's Workday export:

`Company, Supplier, Invoice Date, Invoice Number, Invoice Line, Spend Category, Line Memo, Invoice Amount, Invoice Line Amount, Requester, Created Moment, Cost Center, Fund, Funding Source, Grant, Program, Line of Service, Revenue Category, Spend Type, PO Type, Invoice Status, Payment Status, Payment Type, ...`

## Appendix G: UCH Full Column List (44 Columns)

`Order, Requisition, Creation Date, Purchase Order Amount, Item Name, Item Description, Line, Line Status, Category Name, Manufacturer Part Number, Supplier Item, UOM, Ordered Quantity, Price, PO Line Amount, Received Quantity, Supplier, Manufacturer, Agreement, Agreement Sub Type, Agreement Type, Supplier Number, Supplier Order, Line Type, Balancing Segment Code, Cost Center Code, Cost Center Description, Account Code, Location Segment Value, Organization Code, Concatenated Segments, Location Code, Location Address, Purchase Requestor Display Name, Full Name, Document Status Description, Document Status Meaning, Is it Backordered?, Release Date, Release Notes, UNSPSC Category Name, UNSPSC Category Description, Tecsys Order Line number, Paid Amount`
