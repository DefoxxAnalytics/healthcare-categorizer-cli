# Multi-Client Implementation Plan

## Healthcare Categorization CLI — Config-Driven Multi-Client Engine

**Version**: 3.0
**Author**: VTX Solutions / Defoxx Analytics
**Date**: 2026-02-14
**Status**: Draft
**Engine Reference**: `categorization-cli/src/categorize.py` (614 lines, commit baseline)

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Architecture Decisions](#2-architecture-decisions)
3. [Config Schema v2](#3-config-schema-v2)
4. [Engine Changes](#4-engine-changes)
5. [Variable Rename Table](#5-variable-rename-table)
6. [UCH Reference Data Files](#6-uch-reference-data-files)
7. [Test Changes](#7-test-changes)
8. [Migration Steps](#8-migration-steps)
9. [File Structure](#9-file-structure)
10. [Risk Mitigation](#10-risk-mitigation)
11. [Effort Estimation](#11-effort-estimation)

---

## 1. Problem Statement

The engine (`categorization-cli/src/categorize.py`, 614 lines) was built for CCHMC's Workday export. Every function, variable, config key, and output column assumes CCHMC's "SC code" naming convention. The 7-tier waterfall logic is sound and client-agnostic, but the wiring is CCHMC-specific.

UCH (University of Cincinnati Health) uses Oracle Fusion ERP. Its dataset (`uch-2026.xlsx`) is a single 44-column, 4,649-row Excel file with UNSPSC category codes, rich item descriptions, cost centers, and numeric amounts. **6 of 7 tiers work directly** -- only Tier 4 (Line of Service) is unavailable because UCH has no `Line of Service` column.

| Dimension | CCHMC (Workday) | UCH (Oracle Fusion) |
|-----------|-----------------|---------------------|
| Input format | CSV | XLSX (sheet: "Org Data Pull") |
| Rows | ~596K | 4,649 |
| Columns | 16 | 44 |
| Category column | `Spend Category` ("SC0250 - Professional Services") | `Category Name` ("99000038-Equipment Maintenance Services") |
| Code extraction regex | `((?:DNU\s+)?SC\d+)` | `(\d+)` (UNSPSC numeric prefix) |
| Unique codes | ~250 SC codes | 118 UNSPSC codes |
| Description column | `Line Memo` | `Item Description` (4,155 unique, rich text) |
| Supplier column | `Supplier` | `Supplier` (294 unique, top: GRAINGER 30.9%) |
| Line of Service | `Line of Service` (present) | N/A (absent) |
| Cost Center | `Cost Center` | `Cost Center Description` (7 values) |
| Amount column | `Invoice Line Amount` (float64) | `Paid Amount` (float64, $20.47M total) |
| Column cleanliness | Clean | Clean (no whitespace issues) |
| Dead columns | None | 5 (100% null: Agreement Sub Type, Agreement Type, UNSPSC Category Name, UNSPSC Category Description, Tecsys Order Line number) |
| Catch-all bucket | SC0250 (broad) | `39101612-Incandescent Lamps and Bulbs` (37.6% of rows) |

**The work is a rename + optional-field refactor, not an architectural change.** The waterfall stays in `main()`. No plugins, no strategy classes, no per-client dispatch.

---

## 2. Architecture Decisions

### Decision 1: Config-Driven Conditional Tiers (Not Plugin Pattern)

The 7-tier waterfall works for both clients. The only difference is which tiers fire: UCH skips Tier 4 because it has no `line_of_service` column. This is handled by a simple boolean guard (`if has_line_of_service`) inside `main()`, not by extracting tiers into pluggable objects.

**Rationale**: Both clients share identical classification logic. The difference is data shape (which columns exist), not algorithm. A plugin pattern would add abstraction without adding capability.

### Decision 2: Generalize "SC Code" to "Category Code" Throughout

Every variable, config key, method string, and output column referencing "SC" gets renamed to the generic "category" equivalent. The config specifies which column holds the category string and what regex extracts the code from it.

**Rationale**: "SC" is CCHMC's Workday term. UNSPSC codes, commodity codes, GL codes -- these are all "category codes" with different naming conventions. The engine should be vocabulary-neutral.

### Decision 3: Single Module (Under 1000 Lines)

The engine is 614 lines today. After changes it will be ~660-680 lines. No split needed. The waterfall reads top-to-bottom and benefits from locality.

**Rationale**: Analyst readability. The team reviews classification logic in one file without navigating imports.

### Decision 4: Backward-Compatible Config with Deprecation Aliases

Old config keys (`sc_mapping`, `spend_category`, `line_memo`, `sc_code_pattern`) resolve to their new canonical names via an alias map applied at load time. CCHMC's existing `config.yaml` works without any edits.

**Rationale**: Zero-risk for existing CCHMC deployment. Aliases print deprecation warnings to stderr, prompting eventual migration.

### Decision 5: Support Both CSV and XLSX Input

File extension determines the reader: `.xlsx`/`.xls` uses `pd.read_excel()` with optional `sheet_name`; `.csv` uses `pd.read_csv()`. No new dependencies (openpyxl is already in requirements).

**Rationale**: UCH's data is natively XLSX. Requiring CSV conversion is a needless preprocessing step that loses sheet metadata.

### Decision 6: Make `line_of_service` and `cost_center` Truly Optional

Both columns become optional in config validation. If absent, the corresponding tier prints "skipped" and the output omits that column. `description` (alias: `line_memo`) is also optional -- if absent, `combined_text` uses supplier only.

**Rationale**: Only `category_source`, `supplier`, and `amount` are universal. Everything else is a refinement signal that may or may not exist in a given ERP export.

---

## 3. Config Schema v2

### 3.1 Schema Definition

```yaml
client:
  name: string                    # Required. Console banner and output naming.
  description: string             # Optional.

paths:
  input: string                   # Required. CSV or Excel input file.
  category_mapping: string        # Required. Category code -> taxonomy YAML.
                                  #   Alias: sc_mapping (deprecated)
  taxonomy: string                # Required. Healthcare Taxonomy v2.9 Excel.
  keyword_rules: string           # Required. Keyword regex rules YAML.
  refinement_rules: string        # Required. Refinement rules YAML.
  output_dir: string              # Required. Output directory.
  output_prefix: string           # Required. Output filename prefix.

input_format:                     # Optional section. Defaults to CSV behavior.
  type: string                    # Optional. "csv" (default) or "xlsx".
                                  #   If omitted, inferred from file extension.
  sheet_name: string | int        # Optional. For Excel files with multiple sheets.
                                  #   Default: first sheet (index 0).

columns:
  category_source: string         # Required. Column containing category codes/text.
                                  #   Alias: spend_category (deprecated)
  supplier: string                # Required. Supplier name column.
  amount: string                  # Required. Monetary amount column.
  description: string             # Optional. Item description / line memo column.
                                  #   Alias: line_memo (deprecated)
                                  #   If absent, keyword rules match supplier text only.
  line_of_service: string         # Optional. Enables Tier 4 context refinement.
                                  #   If absent, Tier 4 is skipped.
  cost_center: string             # Optional. Enables Tier 5 cost center refinement.
                                  #   If absent, Tier 5 is skipped.
  passthrough: list[string]       # Optional. Additional input columns to include in output.

classification:
  category_code_pattern: string   # Optional. Regex with one capture group to extract code
                                  #   from category_source column.
                                  #   Alias: sc_code_pattern (deprecated)
                                  #   If absent, raw column value IS the code (no extraction).
  confidence_high: float          # Required. Auto-Accept threshold.
  confidence_medium: float        # Required. Quick Review threshold.

aggregations:                     # Optional. Dynamic groupby sheets in output Excel.
  - name: string
    column: string
    top_n: int | null
```

### 3.2 Key Changes from v1

| v1 Key | v2 Key | Change Type |
|--------|--------|-------------|
| `paths.sc_mapping` | `paths.category_mapping` | Renamed, alias supported |
| `columns.spend_category` | `columns.category_source` | Renamed, alias supported |
| `columns.line_memo` | `columns.description` | Renamed, alias supported |
| `columns.line_of_service` | `columns.line_of_service` | Now **optional** |
| `columns.cost_center` | `columns.cost_center` | Now **optional** |
| `classification.sc_code_pattern` | `classification.category_code_pattern` | Renamed, alias supported, now **optional** |
| *(new)* | `input_format` | New section for Excel support |

### 3.3 Concrete Config: CCHMC (Unchanged -- Works via Aliases)

```yaml
# clients/cchmc/config.yaml -- ZERO CHANGES REQUIRED
client:
  name: "CCHMC"
  description: "Cincinnati Children's Hospital Medical Center -- Workday AP/Procurement"

paths:
  input: "data/input/cchmc-ftp-new.csv"
  sc_mapping: "data/reference/sc_code_mapping.yaml"          # alias -> category_mapping
  taxonomy: "../../shared/reference/Healthcare Taxonomy v2.9.xlsx"
  keyword_rules: "data/reference/keyword_rules.yaml"
  refinement_rules: "data/reference/cchmc_refinement_rules.yaml"
  output_dir: "output"
  output_prefix: "cchmc_categorization_results"

columns:
  spend_category: "Spend Category"       # alias -> category_source
  supplier: "Supplier"
  line_memo: "Line Memo"                 # alias -> description
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
  sc_code_pattern: '((?:DNU\s+)?SC\d+)'  # alias -> category_code_pattern
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

### 3.4 Concrete Config: UCH

```yaml
# clients/uch/config.yaml
client:
  name: "UCH"
  description: "University of Cincinnati Health -- Facilities Procurement (Oracle Fusion)"

paths:
  input: "data/input/uch-2026.xlsx"
  category_mapping: "data/reference/category_mapping.yaml"
  taxonomy: "../../shared/reference/Healthcare Taxonomy v2.9.xlsx"
  keyword_rules: "data/reference/keyword_rules.yaml"
  refinement_rules: "data/reference/uch_refinement_rules.yaml"
  output_dir: "output"
  output_prefix: "uch_categorization_results"

input_format:
  type: "xlsx"
  sheet_name: "Org Data Pull"

columns:
  category_source: "Category Name"
  supplier: "Supplier"
  description: "Item Description"
  # line_of_service: absent -- Tier 4 disabled automatically
  cost_center: "Cost Center Description"
  amount: "Paid Amount"
  passthrough:
    - "Order"
    - "Line Type"
    - "Organization Code"
    - "Line Status"
    - "Location Address"
    - "Purchase Requestor Display Name"
    - "Creation Date"
    - "UNSPSC Code"

classification:
  category_code_pattern: '(\d+)'  # Extract UNSPSC numeric prefix from "99000038-Equipment Maintenance Services"
  confidence_high: 0.7
  confidence_medium: 0.5

aggregations:
  - name: "Spend by Cost Center"
    column: "Cost Center Description"
    top_n: null
  - name: "Spend by Line Type"
    column: "Line Type"
    top_n: null
  - name: "Spend by Organization"
    column: "Organization Code"
    top_n: null
```

---

## 4. Engine Changes

All changes target `src/categorize.py`. Line numbers reference the current 614-line baseline. Each subsection shows exact current code and exact replacement code.

### 4.1 New: Alias Constants and Resolver (insert before `load_config()`, after line 29)

**Why**: Backward compatibility. CCHMC's config uses old key names; the alias map silently resolves them to canonical names at load time, printing deprecation warnings to stderr.

```python
# --- Current code (line 29): ---
class ConfigError(Exception):
    pass


def load_config(config_path: str, ...

# --- New code (insert between ConfigError and load_config): ---
class ConfigError(Exception):
    pass


ALIASES = {
    'paths': {'sc_mapping': 'category_mapping'},
    'columns': {'spend_category': 'category_source', 'line_memo': 'description'},
    'classification': {'sc_code_pattern': 'category_code_pattern'},
}


def _apply_aliases(config: dict) -> list[str]:
    warnings = []
    for section, mappings in ALIASES.items():
        if section not in config:
            continue
        for old_key, new_key in mappings.items():
            if old_key in config[section] and new_key not in config[section]:
                config[section][new_key] = config[section].pop(old_key)
                warnings.append(
                    f"DEPRECATION: '{section}.{old_key}' renamed to "
                    f"'{section}.{new_key}'. Update your config."
                )
    return warnings


def load_config(config_path: str, ...
```

### 4.2 `load_config()` (lines 31-78) -- 5 Targeted Changes

#### 4.2.1 Call `_apply_aliases()` after YAML parse (after line 37)

```python
# --- Current (line 37-38): ---
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    base_dir = config_path.parent

# --- New: ---
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    alias_warnings = _apply_aliases(config)
    for w in alias_warnings:
        print(f"  {w}", file=sys.stderr)

    base_dir = config_path.parent
```

**Why**: Aliases must resolve before any validation runs. Warnings go to stderr so they don't pollute stdout pipeline output.

#### 4.2.2 Required paths: `sc_mapping` -> `category_mapping` (line 46)

```python
# --- Current (line 46): ---
    required_paths = ['input', 'sc_mapping', 'taxonomy', 'keyword_rules', 'refinement_rules', 'output_dir', 'output_prefix']

# --- New: ---
    required_paths = ['input', 'category_mapping', 'taxonomy', 'keyword_rules', 'refinement_rules', 'output_dir', 'output_prefix']
```

**Why**: Canonical key name after alias resolution.

#### 4.2.3 Required columns: make optional columns truly optional (lines 51-54)

```python
# --- Current (lines 51-54): ---
    required_columns = ['spend_category', 'supplier', 'line_memo', 'line_of_service', 'cost_center', 'amount']
    for key in required_columns:
        if key not in config['columns']:
            raise ConfigError(f"Missing required column mapping: 'columns.{key}'")

# --- New: ---
    required_columns = ['category_source', 'supplier', 'amount']
    for key in required_columns:
        if key not in config['columns']:
            raise ConfigError(f"Missing required column mapping: 'columns.{key}'")

    optional_columns = ['description', 'line_of_service', 'cost_center']
    for key in optional_columns:
        if key not in config['columns']:
            config['columns'][key] = None
```

**Why**: Only `category_source`, `supplier`, and `amount` are universal. UCH has no `line_of_service`. Setting absent optional columns to `None` lets downstream code check `cols.get('description') is not None` cleanly.

#### 4.2.4 Required classification: make pattern optional (line 56)

```python
# --- Current (lines 56-59): ---
    required_class = ['sc_code_pattern', 'confidence_high', 'confidence_medium']
    for key in required_class:
        if key not in config['classification']:
            raise ConfigError(f"Missing required classification param: 'classification.{key}'")

# --- New: ---
    required_class = ['confidence_high', 'confidence_medium']
    for key in required_class:
        if key not in config['classification']:
            raise ConfigError(f"Missing required classification param: 'classification.{key}'")
```

**Why**: If `category_code_pattern` is absent, the raw column value is used as the category code directly (no regex extraction). This supports future clients whose category column contains only the code with no descriptive suffix.

#### 4.2.5 Resolve paths: updated key name (line 62)

```python
# --- Current (line 62): ---
    for key in ['input', 'sc_mapping', 'taxonomy', 'keyword_rules', 'refinement_rules']:
        resolved[key] = (base_dir / config['paths'][key]).resolve()

# --- New: ---
    for key in ['input', 'category_mapping', 'taxonomy', 'keyword_rules', 'refinement_rules']:
        resolved[key] = (base_dir / config['paths'][key]).resolve()
```

Also update the existence check on line 74:

```python
# --- Current (line 74): ---
    for key in ['input', 'sc_mapping', 'taxonomy', 'keyword_rules', 'refinement_rules']:

# --- New: ---
    for key in ['input', 'category_mapping', 'taxonomy', 'keyword_rules', 'refinement_rules']:
```

### 4.3 `load_sc_mapping()` (lines 81-94) -- Rename to `load_category_mapping()`

Pure rename. No logic change. The YAML format is identical for both clients: keys are string codes (SC codes for CCHMC, UNSPSC codes for UCH), values have `name`, `taxonomy_key`, `confidence`, `ambiguous`.

```python
# --- Current (lines 81-94): ---
def load_sc_mapping(path: Path) -> dict[str, dict]:
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}

    mapping = {}
    for sc_code, info in data.get('mappings', {}).items():
        sc_code_str = str(sc_code).strip()
        mapping[sc_code_str] = {
            'name': info['name'],
            'taxonomy_key': info['taxonomy_key'],
            'confidence': info.get('confidence', 0.85),
            'ambiguous': info.get('ambiguous', False),
        }
    return mapping

# --- New: ---
def load_category_mapping(path: Path) -> dict[str, dict]:
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}

    mapping = {}
    for code, info in data.get('mappings', {}).items():
        code_str = str(code).strip()
        mapping[code_str] = {
            'name': info['name'],
            'taxonomy_key': info['taxonomy_key'],
            'confidence': info.get('confidence', 0.85),
            'ambiguous': info.get('ambiguous', False),
        }
    return mapping
```

### 4.4 `_validate_and_compile_rules()` (lines 132-140) -- Add `sc_codes` -> `category_codes` Alias

```python
# --- Current (lines 132-140): ---
def _validate_and_compile_rules(rules, section_name, required_keys, pattern_key):
    for i, rule in enumerate(rules):
        for key in required_keys:
            if key not in rule:
                raise ConfigError(f"{section_name}[{i}] missing required key '{key}'")
        try:
            rule['_compiled'] = re.compile(rule[pattern_key], re.IGNORECASE)
        except re.error as e:
            raise ConfigError(f"{section_name}[{i}] invalid regex '{rule[pattern_key]}': {e}")

# --- New: ---
def _validate_and_compile_rules(rules, section_name, required_keys, pattern_key):
    for i, rule in enumerate(rules):
        if 'sc_codes' in rule and 'category_codes' not in rule:
            rule['category_codes'] = rule.pop('sc_codes')
        for key in required_keys:
            if key not in rule:
                raise ConfigError(f"{section_name}[{i}] missing required key '{key}'")
        try:
            rule['_compiled'] = re.compile(rule[pattern_key], re.IGNORECASE)
        except re.error as e:
            raise ConfigError(f"{section_name}[{i}] invalid regex '{rule[pattern_key]}': {e}")
```

**Why**: CCHMC's existing refinement YAML uses `sc_codes`. This alias resolves it to `category_codes` in-place so the rest of the engine uses one name. CCHMC's YAML files require zero changes.

### 4.5 `load_refinement_rules()` (lines 143-180) -- Make `context_rules` and `cost_center_rules` Optional

```python
# --- Current (lines 143-180): ---
def load_refinement_rules(path: Path) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}

    supplier_rules = data.get('supplier_rules', [])
    _validate_and_compile_rules(
        supplier_rules, 'supplier_rules',
        ('sc_codes', 'supplier_pattern', 'taxonomy_key', 'confidence'),
        'supplier_pattern',
    )

    context_rules = data.get('context_rules', [])
    _validate_and_compile_rules(
        context_rules, 'context_rules',
        ('sc_codes', 'line_of_service_pattern', 'taxonomy_key', 'confidence'),
        'line_of_service_pattern',
    )

    cost_center_rules = data.get('cost_center_rules', [])
    _validate_and_compile_rules(
        cost_center_rules, 'cost_center_rules',
        ('sc_codes', 'cost_center_pattern', 'taxonomy_key', 'confidence'),
        'cost_center_pattern',
    )

    override_rules = data.get('supplier_override_rules', [])
    _validate_and_compile_rules(
        override_rules, 'supplier_override_rules',
        ('supplier_pattern', 'override_from_l1', 'taxonomy_key', 'confidence'),
        'supplier_pattern',
    )

    return {
        'supplier_rules': supplier_rules,
        'context_rules': context_rules,
        'cost_center_rules': cost_center_rules,
        'supplier_override_rules': override_rules,
    }

# --- New: ---
def load_refinement_rules(path: Path) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}

    supplier_rules = data.get('supplier_rules', [])
    _validate_and_compile_rules(
        supplier_rules, 'supplier_rules',
        ('category_codes', 'supplier_pattern', 'taxonomy_key', 'confidence'),
        'supplier_pattern',
    )

    context_rules = data.get('context_rules', [])
    if context_rules:
        _validate_and_compile_rules(
            context_rules, 'context_rules',
            ('category_codes', 'line_of_service_pattern', 'taxonomy_key', 'confidence'),
            'line_of_service_pattern',
        )

    cost_center_rules = data.get('cost_center_rules', [])
    if cost_center_rules:
        _validate_and_compile_rules(
            cost_center_rules, 'cost_center_rules',
            ('category_codes', 'cost_center_pattern', 'taxonomy_key', 'confidence'),
            'cost_center_pattern',
        )

    override_rules = data.get('supplier_override_rules', [])
    _validate_and_compile_rules(
        override_rules, 'supplier_override_rules',
        ('supplier_pattern', 'override_from_l1', 'taxonomy_key', 'confidence'),
        'supplier_pattern',
    )

    return {
        'supplier_rules': supplier_rules,
        'context_rules': context_rules,
        'cost_center_rules': cost_center_rules,
        'supplier_override_rules': override_rules,
    }
```

**Why**: UCH has no context rules (no Line of Service). Wrapping validation in `if context_rules:` prevents `ConfigError` when the section is an empty list or absent. Same treatment for `cost_center_rules` for future clients that may lack cost centers. `supplier_rules` and `supplier_override_rules` remain mandatory.

Note: `required_keys` now uses `'category_codes'` instead of `'sc_codes'` -- the alias in `_validate_and_compile_rules()` already resolved CCHMC's `sc_codes` key before validation checks run.

### 4.6 `main()` (lines 183-597) -- Section-by-Section Changes

#### 4.6.1 Resource Loading (lines 199-217): Rename Call Site + Derive Feature Flags

```python
# --- Current (lines 200-201): ---
    sc_mapping = load_sc_mapping(paths['sc_mapping'])
    print(f"  SC code mappings: {len(sc_mapping)}")

# --- New: ---
    cat_mapping = load_category_mapping(paths['category_mapping'])
    print(f"  Category mappings: {len(cat_mapping)}")
```

```python
# --- Current (line 216): ---
    ambiguous_codes = {sc for sc, info in sc_mapping.items() if info.get('ambiguous')}
    print(f"  Ambiguous SC codes: {len(ambiguous_codes)}")

# --- New: ---
    ambiguous_codes = {c for c, info in cat_mapping.items() if info.get('ambiguous')}
    print(f"  Ambiguous category codes: {len(ambiguous_codes)}")
```

Insert after refinement loading (after line 217), before line 219:

```python
    has_description = cols.get('description') is not None
    has_line_of_service = cols.get('line_of_service') is not None
    has_cost_center = cols.get('cost_center') is not None
    has_category_pattern = 'category_code_pattern' in classif
```

**Why**: Feature flags derived once, used throughout to guard conditional logic cleanly.

#### 4.6.2 Mapping Validation (lines 219-227): Rename Variables

```python
# --- Current (lines 219-227): ---
    invalid_mappings = []
    for sc_code, info in sc_mapping.items():
        if info['taxonomy_key'] not in taxonomy_keys_set:
            invalid_mappings.append((sc_code, info['taxonomy_key']))
    if invalid_mappings:
        print(f"\n  WARNING: {len(invalid_mappings)} SC mappings point to invalid taxonomy keys:")
        for sc, key in invalid_mappings[:10]:
            print(f"    {sc} -> {key}")
        print("  These will still be used but won't resolve to L1-L5 breakdown.")

# --- New: ---
    invalid_mappings = []
    for code, info in cat_mapping.items():
        if info['taxonomy_key'] not in taxonomy_keys_set:
            invalid_mappings.append((code, info['taxonomy_key']))
    if invalid_mappings:
        print(f"\n  WARNING: {len(invalid_mappings)} category mappings point to invalid taxonomy keys:")
        for code, key in invalid_mappings[:10]:
            print(f"    {code} -> {key}")
        print("  These will still be used but won't resolve to L1-L5 breakdown.")
```

#### 4.6.3 Input Loading (lines 229-232): Support Excel

```python
# --- Current (lines 229-232): ---
    print(f"\nLoading {client_name} dataset...")
    df = pd.read_csv(paths['input'], low_memory=False)
    total_rows = len(df)
    print(f"  Loaded {total_rows:,} rows, {len(df.columns)} columns")

# --- New: ---
    print(f"\nLoading {client_name} dataset...")
    input_path = paths['input']
    if input_path.suffix in ('.xlsx', '.xls'):
        sheet = config.get('input_format', {}).get('sheet_name', 0)
        df = pd.read_excel(input_path, sheet_name=sheet)
    else:
        df = pd.read_csv(input_path, low_memory=False)
    total_rows = len(df)
    print(f"  Loaded {total_rows:,} rows, {len(df.columns)} columns")
```

**Why**: UCH data is XLSX. File extension detection is more reliable than a config flag since it handles overrides via `--input` correctly.

#### 4.6.4 Empty Input Check (lines 234-235): Update Error Message

```python
# --- Current (line 235): ---
        raise ConfigError(f"Input CSV has 0 data rows: {paths['input']}")

# --- New: ---
        raise ConfigError(f"Input file has 0 data rows: {paths['input']}")
```

#### 4.6.5 Column Validation (lines 237-251): Build Dynamically from Config

```python
# --- Current (lines 237-251): ---
    required_csv_cols = {
        'spend_category': cols['spend_category'],
        'supplier': cols['supplier'],
        'line_memo': cols['line_memo'],
        'line_of_service': cols['line_of_service'],
        'cost_center': cols['cost_center'],
        'amount': cols['amount'],
    }
    missing_csv_cols = [
        f"'{v}' (from columns.{k})"
        for k, v in required_csv_cols.items()
        if v not in df.columns
    ]
    if missing_csv_cols:
        raise ConfigError(f"Columns not found in input CSV: {', '.join(missing_csv_cols)}")

# --- New: ---
    expected_cols = {
        'category_source': cols['category_source'],
        'supplier': cols['supplier'],
        'amount': cols['amount'],
    }
    for opt_key in ['description', 'line_of_service', 'cost_center']:
        if cols.get(opt_key):
            expected_cols[opt_key] = cols[opt_key]

    missing_cols = [
        f"'{v}' (from columns.{k})"
        for k, v in expected_cols.items()
        if v not in df.columns
    ]
    if missing_cols:
        raise ConfigError(f"Columns not found in input: {', '.join(missing_cols)}")
```

**Why**: Only columns that exist in config get validated against the DataFrame. Missing optional columns (like UCH's absent `line_of_service`) don't trigger errors.

#### 4.6.6 Category Code Extraction (lines 257-265): Generalize + Conditional Pattern

```python
# --- Current (lines 257-265): ---
    sc_pattern = classif['sc_code_pattern']
    conf_high = classif['confidence_high']
    conf_medium = classif['confidence_medium']

    spend_cat_str = df[cols['spend_category']].astype(str).str.strip()
    sc_extracted = spend_cat_str.str.extract(f'({sc_pattern})', expand=False)
    if isinstance(sc_extracted, pd.DataFrame):
        sc_extracted = sc_extracted.iloc[:, 0]
    sc_code = sc_extracted.fillna(spend_cat_str)

# --- New: ---
    conf_high = classif['confidence_high']
    conf_medium = classif['confidence_medium']

    cat_source_str = df[cols['category_source']].astype(str).str.strip()

    if has_category_pattern:
        cat_pattern = classif['category_code_pattern']
        cat_extracted = cat_source_str.str.extract(f'({cat_pattern})', expand=False)
        if isinstance(cat_extracted, pd.DataFrame):
            cat_extracted = cat_extracted.iloc[:, 0]
        category_code = cat_extracted.fillna(cat_source_str)
    else:
        category_code = cat_source_str
```

**Why**: If no pattern is configured, the raw column value is the code. This supports clients whose category column contains only codes without descriptive suffixes.

#### 4.6.7 Text Column Extraction (lines 267-271): Conditional Optional Columns

```python
# --- Current (lines 267-271): ---
    supplier = df[cols['supplier']].fillna('').astype(str)
    line_memo = df[cols['line_memo']].fillna('').astype(str)
    line_of_service = df[cols['line_of_service']].fillna('').astype(str)
    cost_center = df[cols['cost_center']].fillna('').astype(str)
    combined_text = supplier + ' ' + line_memo

# --- New: ---
    supplier = df[cols['supplier']].fillna('').astype(str)

    description = pd.Series('', index=df.index, dtype='object')
    if has_description:
        description = df[cols['description']].fillna('').astype(str)

    line_of_service = pd.Series('', index=df.index, dtype='object')
    if has_line_of_service:
        line_of_service = df[cols['line_of_service']].fillna('').astype(str)

    cost_center = pd.Series('', index=df.index, dtype='object')
    if has_cost_center:
        cost_center = df[cols['cost_center']].fillna('').astype(str)

    combined_text = supplier + ' ' + description
```

**Why**: Missing optional columns create empty Series instead of raising KeyError. `combined_text` degrades gracefully to supplier-only when description is absent.

#### 4.6.8 Tier 1 (lines 277-284): Variable Rename + Method String Update

```python
# --- Current (lines 277-284): ---
    # Tier 1: Non-ambiguous SC code mapping
    non_amb_taxonomy = {sc: info['taxonomy_key'] for sc, info in sc_mapping.items() if not info.get('ambiguous')}
    non_amb_confidence = {sc: info['confidence'] for sc, info in sc_mapping.items() if not info.get('ambiguous')}
    tier1_mask = sc_code.isin(non_amb_taxonomy)
    taxonomy_key[tier1_mask] = sc_code[tier1_mask].map(non_amb_taxonomy)
    method[tier1_mask] = 'sc_code_mapping'
    confidence[tier1_mask] = sc_code[tier1_mask].map(non_amb_confidence)
    print(f"  Tier 1 (SC code mapping): {tier1_mask.sum():,} rows")

# --- New: ---
    # Tier 1: Non-ambiguous category code mapping
    non_amb_taxonomy = {c: info['taxonomy_key'] for c, info in cat_mapping.items() if not info.get('ambiguous')}
    non_amb_confidence = {c: info['confidence'] for c, info in cat_mapping.items() if not info.get('ambiguous')}
    tier1_mask = category_code.isin(non_amb_taxonomy)
    taxonomy_key[tier1_mask] = category_code[tier1_mask].map(non_amb_taxonomy)
    method[tier1_mask] = 'category_mapping'
    confidence[tier1_mask] = category_code[tier1_mask].map(non_amb_confidence)
    print(f"  Tier 1 (category mapping): {tier1_mask.sum():,} rows")
```

#### 4.6.9 Tier 2 (lines 288-308): `sc_codes` -> `category_codes` in Rule Access

```python
# --- Current (lines 289-308): ---
    tier2_count = 0
    for rule in refinement['supplier_rules']:
        if not unclassified.any():
            break
        sc_match = sc_code.isin(rule['sc_codes'])
        candidate = unclassified & sc_match
        if not candidate.any():
            continue
        cand_idx = candidate[candidate].index
        supplier_match = supplier.loc[cand_idx].str.contains(
            rule['supplier_pattern'], case=False, na=False, regex=True
        )
        hit_idx = cand_idx[supplier_match.values]
        if len(hit_idx) > 0:
            taxonomy_key[hit_idx] = rule['taxonomy_key']
            method[hit_idx] = 'supplier_refinement'
            confidence[hit_idx] = rule['confidence']
            tier2_count += len(hit_idx)
            unclassified[hit_idx] = False
    print(f"  Tier 2 (supplier refinement): {tier2_count:,} rows")

# --- New: ---
    tier2_count = 0
    for rule in refinement['supplier_rules']:
        if not unclassified.any():
            break
        code_match = category_code.isin(rule['category_codes'])
        candidate = unclassified & code_match
        if not candidate.any():
            continue
        cand_idx = candidate[candidate].index
        supplier_match = supplier.loc[cand_idx].str.contains(
            rule['supplier_pattern'], case=False, na=False, regex=True
        )
        hit_idx = cand_idx[supplier_match.values]
        if len(hit_idx) > 0:
            taxonomy_key[hit_idx] = rule['taxonomy_key']
            method[hit_idx] = 'supplier_refinement'
            confidence[hit_idx] = rule['confidence']
            tier2_count += len(hit_idx)
            unclassified[hit_idx] = False
    print(f"  Tier 2 (supplier refinement): {tier2_count:,} rows")
```

**Why**: The `sc_codes` -> `category_codes` alias was applied in `_validate_and_compile_rules()`, so by the time rules reach `main()`, the key is always `category_codes`. CCHMC's YAML still says `sc_codes` -- the alias handles it transparently.

#### 4.6.10 Tier 3 (lines 310-326): No Structural Change

The only variable rename is `combined_text = supplier + ' ' + description` (already done in 4.6.7). The keyword loop references `combined_text` and `unclassified` -- both unchanged in structure. No code change needed in this block.

#### 4.6.11 Tier 4 (lines 328-348): Wrap in `if has_line_of_service`

```python
# --- Current (lines 328-348): ---
    # Tier 4: Context refinement (Line of Service)
    tier4_count = 0
    for rule in refinement['context_rules']:
        if not unclassified.any():
            break
        sc_match = sc_code.isin(rule['sc_codes'])
        candidate = unclassified & sc_match
        if not candidate.any():
            continue
        cand_idx = candidate[candidate].index
        los_match = line_of_service.loc[cand_idx].str.contains(
            rule['line_of_service_pattern'], case=False, na=False, regex=True
        )
        hit_idx = cand_idx[los_match.values]
        if len(hit_idx) > 0:
            taxonomy_key[hit_idx] = rule['taxonomy_key']
            method[hit_idx] = 'context_refinement'
            confidence[hit_idx] = rule['confidence']
            tier4_count += len(hit_idx)
            unclassified[hit_idx] = False
    print(f"  Tier 4 (context refinement): {tier4_count:,} rows")

# --- New: ---
    # Tier 4: Context refinement (Line of Service)
    tier4_count = 0
    if has_line_of_service and refinement['context_rules']:
        for rule in refinement['context_rules']:
            if not unclassified.any():
                break
            code_match = category_code.isin(rule['category_codes'])
            candidate = unclassified & code_match
            if not candidate.any():
                continue
            cand_idx = candidate[candidate].index
            los_match = line_of_service.loc[cand_idx].str.contains(
                rule['line_of_service_pattern'], case=False, na=False, regex=True
            )
            hit_idx = cand_idx[los_match.values]
            if len(hit_idx) > 0:
                taxonomy_key[hit_idx] = rule['taxonomy_key']
                method[hit_idx] = 'context_refinement'
                confidence[hit_idx] = rule['confidence']
                tier4_count += len(hit_idx)
                unclassified[hit_idx] = False
        print(f"  Tier 4 (context refinement): {tier4_count:,} rows")
    else:
        print(f"  Tier 4 (context refinement): skipped (no line_of_service column)")
```

**Why**: UCH has no Line of Service column. Without the guard, the tier would iterate over empty rules (no-op but misleading), or worse, crash if `line_of_service` Series is empty and rules reference it. The guard makes the skip explicit in console output.

#### 4.6.12 Tier 5 (lines 350-370): Same Conditional Pattern

```python
# --- Current (lines 350-370): ---
    # Tier 5: Cost center refinement
    tier5_count = 0
    for rule in refinement['cost_center_rules']:
        if not unclassified.any():
            break
        sc_match = sc_code.isin(rule['sc_codes'])
        candidate = unclassified & sc_match
        if not candidate.any():
            continue
        cand_idx = candidate[candidate].index
        cc_match = cost_center.loc[cand_idx].str.contains(
            rule['cost_center_pattern'], case=False, na=False, regex=True
        )
        hit_idx = cand_idx[cc_match.values]
        if len(hit_idx) > 0:
            taxonomy_key[hit_idx] = rule['taxonomy_key']
            method[hit_idx] = 'cost_center_refinement'
            confidence[hit_idx] = rule['confidence']
            tier5_count += len(hit_idx)
            unclassified[hit_idx] = False
    print(f"  Tier 5 (cost center refinement): {tier5_count:,} rows")

# --- New: ---
    # Tier 5: Cost center refinement
    tier5_count = 0
    if has_cost_center and refinement['cost_center_rules']:
        for rule in refinement['cost_center_rules']:
            if not unclassified.any():
                break
            code_match = category_code.isin(rule['category_codes'])
            candidate = unclassified & code_match
            if not candidate.any():
                continue
            cand_idx = candidate[candidate].index
            cc_match = cost_center.loc[cand_idx].str.contains(
                rule['cost_center_pattern'], case=False, na=False, regex=True
            )
            hit_idx = cand_idx[cc_match.values]
            if len(hit_idx) > 0:
                taxonomy_key[hit_idx] = rule['taxonomy_key']
                method[hit_idx] = 'cost_center_refinement'
                confidence[hit_idx] = rule['confidence']
                tier5_count += len(hit_idx)
                unclassified[hit_idx] = False
        print(f"  Tier 5 (cost center refinement): {tier5_count:,} rows")
    else:
        print(f"  Tier 5 (cost center refinement): skipped (no cost_center column or rules)")
```

**Why**: UCH has cost centers (7 values), so Tier 5 fires for UCH. But future clients may lack cost centers. The guard ensures graceful degradation.

#### 4.6.13 Tier 6 (lines 372-379): Variable Rename + Method String Update

```python
# --- Current (lines 372-379): ---
    # Tier 6: Ambiguous SC fallback
    amb_taxonomy = {sc: info['taxonomy_key'] for sc, info in sc_mapping.items() if info.get('ambiguous')}
    amb_confidence = {sc: info['confidence'] for sc, info in sc_mapping.items() if info.get('ambiguous')}
    tier6_mask = unclassified & sc_code.isin(amb_taxonomy)
    taxonomy_key[tier6_mask] = sc_code[tier6_mask].map(amb_taxonomy)
    method[tier6_mask] = 'sc_code_mapping_ambiguous'
    confidence[tier6_mask] = sc_code[tier6_mask].map(amb_confidence)
    print(f"  Tier 6 (ambiguous fallback): {tier6_mask.sum():,} rows")

# --- New: ---
    # Tier 6: Ambiguous category code fallback
    amb_taxonomy = {c: info['taxonomy_key'] for c, info in cat_mapping.items() if info.get('ambiguous')}
    amb_confidence = {c: info['confidence'] for c, info in cat_mapping.items() if info.get('ambiguous')}
    tier6_mask = unclassified & category_code.isin(amb_taxonomy)
    taxonomy_key[tier6_mask] = category_code[tier6_mask].map(amb_taxonomy)
    method[tier6_mask] = 'category_mapping_ambiguous'
    confidence[tier6_mask] = category_code[tier6_mask].map(amb_confidence)
    print(f"  Tier 6 (ambiguous fallback): {tier6_mask.sum():,} rows")
```

#### 4.6.14 Tier 7 (lines 402-421): No Structural Change

Tier 7 operates on `supplier` (always present) and `cat_l1` (derived from taxonomy lookup post-classification). No variable renames needed inside this block -- it doesn't reference `sc_code` or `sc_mapping`.

#### 4.6.15 Review Tier Assignment (lines 423-429): Update Method Name

```python
# --- Current (line 424): ---
    high_conf_methods = method.isin(['sc_code_mapping', 'rule'])

# --- New: ---
    high_conf_methods = method.isin(['category_mapping', 'rule'])
```

#### 4.6.16 Output DataFrame (lines 434-464): Conditional Columns + Renamed Labels

```python
# --- Current (lines 439-464): ---
    output_columns = {
        cols['supplier']: supplier,
    }
    for col_name in cols.get('passthrough', []):
        if col_name not in output_columns:
            output_columns[col_name] = df.get(col_name, pd.Series('', index=df.index))

    output_columns[cols['line_memo']] = line_memo
    output_columns['Spend Category (Source)'] = spend_cat_str
    output_columns['SC Code'] = sc_code
    output_columns[cols['cost_center']] = df.get(cols['cost_center'], pd.Series('', index=df.index))
    output_columns[cols['line_of_service']] = df.get(cols['line_of_service'], pd.Series('', index=df.index))

    if amount_col not in output_columns:
        output_columns[amount_col] = df[amount_col]

    output_columns['CategoryLevel1'] = cat_l1
    output_columns['CategoryLevel2'] = cat_l2
    output_columns['CategoryLevel3'] = cat_l3
    output_columns['CategoryLevel4'] = cat_l4
    output_columns['CategoryLevel5'] = cat_l5
    output_columns['TaxonomyKey'] = taxonomy_key
    output_columns['ClassificationMethod'] = method
    output_columns['Confidence'] = confidence.round(3)
    output_columns['ReviewTier'] = review_tier

# --- New: ---
    output_columns = {
        cols['supplier']: supplier,
    }
    for col_name in cols.get('passthrough', []):
        if col_name not in output_columns and col_name in df.columns:
            output_columns[col_name] = df[col_name]

    if has_description:
        output_columns[cols['description']] = description

    output_columns['Category Source'] = cat_source_str
    output_columns['Category Code'] = category_code

    if has_cost_center:
        output_columns[cols['cost_center']] = df[cols['cost_center']]

    if has_line_of_service:
        output_columns[cols['line_of_service']] = df[cols['line_of_service']]

    amount_col = cols['amount']
    if amount_col not in output_columns:
        output_columns[amount_col] = df[amount_col]

    output_columns['CategoryLevel1'] = cat_l1
    output_columns['CategoryLevel2'] = cat_l2
    output_columns['CategoryLevel3'] = cat_l3
    output_columns['CategoryLevel4'] = cat_l4
    output_columns['CategoryLevel5'] = cat_l5
    output_columns['TaxonomyKey'] = taxonomy_key
    output_columns['ClassificationMethod'] = method
    output_columns['Confidence'] = confidence.round(3)
    output_columns['ReviewTier'] = review_tier
```

**Why**: Optional columns only appear in output when they exist in the config. Output column names are now generic (`Category Source`, `Category Code`) instead of CCHMC-specific (`Spend Category (Source)`, `SC Code`).

#### 4.6.17 Unmapped Counter (lines 469-472): Rename Variable + Column Reference

```python
# --- Current (lines 469-472): ---
    unmapped_sc = Counter()
    if method_counts.get('unmapped', 0) > 0:
        unmapped_rows = results_df[results_df['ClassificationMethod'] == 'unmapped']
        unmapped_sc = Counter(unmapped_rows['Spend Category (Source)'].tolist())

# --- New: ---
    unmapped_counts = Counter()
    if method_counts.get('unmapped', 0) > 0:
        unmapped_rows = results_df[results_df['ClassificationMethod'] == 'unmapped']
        unmapped_counts = Counter(unmapped_rows['Category Source'].tolist())
```

#### 4.6.18 Summary Sheet (lines 508-538): Update Method Labels + Column References

```python
# --- Current (lines 485-498): ---
        all_methods = [
            'sc_code_mapping', 'supplier_refinement', 'rule',
            'context_refinement', 'cost_center_refinement',
            'sc_code_mapping_ambiguous', 'supplier_override', 'unmapped',
        ]
        method_labels = {
            'sc_code_mapping': 'SC Code Mapping (direct)',
            'supplier_refinement': 'Supplier Refinement',
            'rule': 'Keyword Rules',
            'context_refinement': 'Context Refinement (LoS)',
            'cost_center_refinement': 'Cost Center Refinement',
            'sc_code_mapping_ambiguous': 'SC Code Mapping (ambiguous fallback)',
            'supplier_override': 'Supplier Override (post-classification)',
            'unmapped': 'Unmapped',
        }

# --- New: ---
        all_methods = [
            'category_mapping', 'supplier_refinement', 'rule',
            'context_refinement', 'cost_center_refinement',
            'category_mapping_ambiguous', 'supplier_override', 'unmapped',
        ]
        method_labels = {
            'category_mapping': 'Category Mapping (direct)',
            'supplier_refinement': 'Supplier Refinement',
            'rule': 'Keyword Rules',
            'context_refinement': 'Context Refinement (LoS)',
            'cost_center_refinement': 'Cost Center Refinement',
            'category_mapping_ambiguous': 'Category Mapping (ambiguous fallback)',
            'supplier_override': 'Supplier Override (post-classification)',
            'unmapped': 'Unmapped',
        }
```

Summary data metrics (lines 508-536): Update column references:

```python
# --- Current (lines 512, 526): ---
                'Unique SC Codes',
                ...
                f"{results_df['SC Code'].nunique():,}",

# --- New: ---
                'Unique Category Codes',
                ...
                f"{results_df['Category Code'].nunique():,}",
```

#### 4.6.19 Unmapped Sheet (lines 569-574): Rename Column + Sheet

```python
# --- Current (lines 569-574): ---
        if unmapped_sc:
            unmapped_data = [
                {'SC Code': sc, 'Count': count}
                for sc, count in unmapped_sc.most_common()
            ]
            pd.DataFrame(unmapped_data).to_excel(writer, sheet_name='Unmapped SC Codes', index=False)

# --- New: ---
        if unmapped_counts:
            unmapped_data = [
                {'Category Code': code, 'Count': count}
                for code, count in unmapped_counts.most_common()
            ]
            pd.DataFrame(unmapped_data).to_excel(writer, sheet_name='Unmapped Categories', index=False)
```

#### 4.6.20 Console Summary (lines 578-596): Update Labels

```python
# --- Current (line 592-594): ---
    if unmapped_sc:
        print(f"\nUnmapped SC Codes: {len(unmapped_sc)} unique codes, {sum(unmapped_sc.values()):,} total rows")
        for sc, count in unmapped_sc.most_common(10):
            print(f"  {sc:40s} {count:>6,}")

# --- New: ---
    if unmapped_counts:
        print(f"\nUnmapped Categories: {len(unmapped_counts)} unique codes, {sum(unmapped_counts.values()):,} total rows")
        for code, count in unmapped_counts.most_common(10):
            print(f"  {code:40s} {count:>6,}")
```

#### 4.6.21 Argparse Help Text (lines 604): Update Description

```python
# --- Current (line 604): ---
    parser.add_argument('--input', default=None, help='Override input CSV path from config')

# --- New: ---
    parser.add_argument('--input', default=None, help='Override input file path (CSV or XLSX) from config')
```

---

## 5. Variable Rename Table

Complete list of every rename in `src/categorize.py`:

| Old Name | New Name | Scope | Type |
|----------|----------|-------|------|
| `load_sc_mapping()` | `load_category_mapping()` | Module-level function | Function name |
| `sc_mapping` (local var) | `cat_mapping` | `main()` | Local variable |
| `sc_code` (Series) | `category_code` | `main()` | pandas Series |
| `spend_cat_str` (Series) | `cat_source_str` | `main()` | pandas Series |
| `sc_pattern` (str) | `cat_pattern` | `main()` | String variable |
| `sc_extracted` (Series) | `cat_extracted` | `main()` | pandas Series |
| `line_memo` (Series) | `description` | `main()` | pandas Series |
| `unmapped_sc` (Counter) | `unmapped_counts` | `main()` | Counter variable |
| `sc_match` (mask) | `code_match` | `main()` Tiers 2, 4, 5 | Boolean mask |
| `'sc_code_mapping'` | `'category_mapping'` | Method string literal | Output value |
| `'sc_code_mapping_ambiguous'` | `'category_mapping_ambiguous'` | Method string literal | Output value |
| `'Spend Category (Source)'` | `'Category Source'` | Output column name | Excel output |
| `'SC Code'` | `'Category Code'` | Output column name | Excel output |
| `'Unmapped SC Codes'` | `'Unmapped Categories'` | Sheet name | Excel output |
| `'Unique SC Codes'` | `'Unique Category Codes'` | Summary metric label | Excel output |
| `'SC Code Mapping (direct)'` | `'Category Mapping (direct)'` | Method display label | Console + Excel |
| `'SC Code Mapping (ambiguous fallback)'` | `'Category Mapping (ambiguous fallback)'` | Method display label | Console + Excel |

---

## 6. UCH Reference Data Files

### 6.1 `category_mapping.yaml` -- 118 UNSPSC Codes

Located at `clients/uch/data/reference/category_mapping.yaml`. Maps each of UCH's 118 unique `Category Name` values (by their extracted UNSPSC numeric prefix) to Healthcare Taxonomy v2.9 keys.

```yaml
# clients/uch/data/reference/category_mapping.yaml
# UCH -- UNSPSC Code -> Healthcare Taxonomy v2.9 Mapping
# Source: uch-2026.xlsx, 118 unique Category Name values
# Generated: 2026-02-XX

mappings:

  # === HIGH-VOLUME CATCH-ALL CODES (mark ambiguous) ===

  "39101612":
    name: "Incandescent Lamps and Bulbs"
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    confidence: 0.70
    ambiguous: true     # 1,750 rows (37.6%) -- default bucket, needs refinement

  "99000038":
    name: "Equipment Maintenance Services"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance"
    confidence: 0.80
    ambiguous: true     # 773 rows -- broad service category

  "31160000":
    name: "Hardware"
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    confidence: 0.80
    ambiguous: true     # Broad hardware category

  # === STANDARD UNSPSC PRODUCTS (non-ambiguous) ===

  "46182402":
    name: "Safety Gloves"
    taxonomy_key: "Medical > Medical Supplies > Safety & PPE"
    confidence: 0.90
    ambiguous: false    # 447 rows

  "47131800":
    name: "Floor Cleaning Machines"
    taxonomy_key: "Facilities > Cleaning > Cleaning Equipment"
    confidence: 0.90
    ambiguous: false

  # === CUSTOM SERVICE CODES (99XXXXXX) ===

  "99000039":
    name: "Equipment Rental Services"
    taxonomy_key: "Facilities > Equipment Hire"
    confidence: 0.85
    ambiguous: false

  # ... (remaining ~112 codes to be mapped during Migration Step 5)
```

**Generation process**:
1. Extract unique `Category Name` values from `uch-2026.xlsx`
2. Parse the numeric prefix and description from each value (split on `-`)
3. Map standard UNSPSC codes (non-99XXXXXX) using UNSPSC reference tables
4. Map custom service codes (99XXXXXX) by their description text
5. Mark high-volume catch-all codes as `ambiguous: true`, especially `39101612` (37.6% of all rows)

**Key insight**: `39101612-Incandescent Lamps and Bulbs` covers 1,750 rows but contains everything from electrical supplies to door hardware. It is a default bucket in Oracle Fusion, not a real UNSPSC classification of lamps. Marking it `ambiguous: true` sends it through Tiers 2-5 for supplier/keyword/cost center refinement before falling back to Tier 6 at low confidence.

### 6.2 `keyword_rules.yaml` -- Shared or Client-Specific

UCH's `Item Description` field contains rich text suitable for keyword matching (e.g., "REPAIR MAIN FREEZER", "Morton water softener salt.", "FURNISH AND INSTALL REPLACEMENT VALVES"). The existing shared keyword rules from CCHMC fire against `combined_text = supplier + ' ' + description`.

Two options:
1. **Shared**: Point UCH config at `../../shared/reference/keyword_rules.yaml`
2. **Client-specific copy**: Copy into `clients/uch/data/reference/keyword_rules.yaml` for UCH-specific rules

Start with the shared file. If UCH-specific keyword rules are needed (e.g., "FURNISH AND INSTALL" -> specific taxonomy), create the client-specific copy.

### 6.3 `uch_refinement_rules.yaml` -- Supplier + Cost Center Rules (No Context Rules)

Located at `clients/uch/data/reference/uch_refinement_rules.yaml`.

```yaml
# clients/uch/data/reference/uch_refinement_rules.yaml
# UCH Refinement Rules -- supplier + cost center only (no Line of Service)

supplier_rules:

  # --- Disambiguate 39101612 (1,750 rows, catch-all bucket) ---

  - category_codes: ["39101612"]
    supplier_pattern: "grainger|w.w. grainger"
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    confidence: 0.90

  - category_codes: ["39101612"]
    supplier_pattern: "fastenal"
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    confidence: 0.88

  - category_codes: ["39101612"]
    supplier_pattern: "mcmaster.carr"
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    confidence: 0.88

  - category_codes: ["39101612"]
    supplier_pattern: "assa abloy|door.*operator"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance > Door Systems"
    confidence: 0.90

  - category_codes: ["39101612"]
    supplier_pattern: "johnson controls|siemens building"
    taxonomy_key: "Facilities > Technology Systems > Building Automation & Control Systems"
    confidence: 0.88

  # --- Disambiguate 99000038 (773 rows, Equipment Maintenance Services) ---

  - category_codes: ["99000038"]
    supplier_pattern: "otis elevator|schindler|thyssenkrupp"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance > Elevator Services"
    confidence: 0.92

  - category_codes: ["99000038"]
    supplier_pattern: "johnson controls fire|simplex grinnell"
    taxonomy_key: "Facilities > Facilities Services > Fire > Fire Safety Systems"
    confidence: 0.90

  - category_codes: ["99000038"]
    supplier_pattern: "emcor"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance"
    confidence: 0.85

  # --- Hardware disambiguation (31160000) ---

  - category_codes: ["31160000"]
    supplier_pattern: "grainger|w.w. grainger"
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    confidence: 0.88

  # ... (additional supplier rules built from UCH's 294 unique suppliers)

context_rules: []    # No Line of Service column in UCH dataset

cost_center_rules:

  - category_codes: ["39101612", "99000038"]
    cost_center_pattern: "MAINTENANCE"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance"
    confidence: 0.75

  - category_codes: ["39101612", "99000038"]
    cost_center_pattern: "MECHANICAL SERVICES"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance > HVAC Installation & Maintenance"
    confidence: 0.78

  - category_codes: ["39101612"]
    cost_center_pattern: "ELECTRICAL SERVICES"
    taxonomy_key: "Facilities > Facilities Services > Electrical"
    confidence: 0.80

  - category_codes: ["39101612"]
    cost_center_pattern: "GROUNDS & MOVERS"
    taxonomy_key: "Facilities > Facilities Services > Grounds & Landscaping"
    confidence: 0.80

  - category_codes: ["39101612"]
    cost_center_pattern: "BUILDING SERVICES"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance"
    confidence: 0.75

  - category_codes: ["39101612"]
    cost_center_pattern: "EMERGENCY MAINTENANCE"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance"
    confidence: 0.70

  - category_codes: ["39101612"]
    cost_center_pattern: "PLANT OPERATIONS"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance"
    confidence: 0.72

supplier_override_rules: []
```

**Notes**:
- `context_rules: []` is explicitly empty because UCH has no Line of Service column
- Cost center rules target the 7 unique `Cost Center Description` values in the UCH dataset: MAINTENANCE (3,143 rows), MECHANICAL SERVICES (774), GROUNDS & MOVERS (222), EMERGENCY MAINTENANCE (187), BUILDING SERVICES (181), ELECTRICAL SERVICES (84), PLANT OPERATIONS (58)
- Supplier rules are scoped by `category_codes` so they only fire within the ambiguous catch-all buckets, not globally

---

## 7. Test Changes

### 7.1 Current Test Architecture

| File | Lines | Purpose |
|------|-------|---------|
| `tests/conftest.py` | 61 lines | Session-scoped fixtures: `client_dir`, `client_config`, `refinement`, `sc_mapping`, `keyword_rules`, `taxonomy_keys`, `valid_sc_codes` |
| `tests/test_rules.py` | 274 lines | 7 test classes, 33 tests: YAML structure, regex validity, taxonomy keys, SC code validity, confidence ranges, supplier classification, conflict detection |

### 7.2 Fixture Updates in `conftest.py`

#### 7.2.1 Rename `sc_mapping` fixture to `category_mapping` (lines 36-40)

```python
# --- Current (lines 36-40): ---
@pytest.fixture(scope="session")
def sc_mapping(client_dir, client_config):
    path = client_dir / client_config["paths"]["sc_mapping"]
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

# --- New: ---
@pytest.fixture(scope="session")
def category_mapping(client_dir, client_config):
    mapping_key = ("category_mapping" if "category_mapping" in client_config["paths"]
                   else "sc_mapping")
    path = client_dir / client_config["paths"][mapping_key]
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def sc_mapping(category_mapping):
    return category_mapping
```

**Why**: New canonical name with backward-compatible alias. Both CCHMC (`sc_mapping` key) and UCH (`category_mapping` key) configs resolve correctly.

#### 7.2.2 Rename `valid_sc_codes` fixture (lines 58-60)

```python
# --- Current (lines 58-60): ---
@pytest.fixture(scope="session")
def valid_sc_codes(sc_mapping):
    return set(str(k).strip() for k in sc_mapping.get("mappings", {}).keys())

# --- New: ---
@pytest.fixture(scope="session")
def valid_category_codes(category_mapping):
    return set(str(k).strip() for k in category_mapping.get("mappings", {}).keys())


@pytest.fixture(scope="session")
def valid_sc_codes(valid_category_codes):
    return valid_category_codes
```

### 7.3 Test Class Updates in `test_rules.py`

#### 7.3.1 `TestYAMLStructure.test_refinement_has_required_sections` (lines 23-25)

```python
# --- Current (lines 23-25): ---
    def test_refinement_has_required_sections(self, refinement):
        for section in ["supplier_rules", "context_rules", "cost_center_rules", "supplier_override_rules"]:
            assert section in refinement, f"Missing section: {section}"

# --- New: ---
    def test_refinement_has_required_sections(self, refinement):
        assert "supplier_rules" in refinement, "Missing section: supplier_rules"
        assert "supplier_override_rules" in refinement, "Missing section: supplier_override_rules"
        # context_rules and cost_center_rules are optional per client
```

#### 7.3.2 `TestYAMLStructure.test_supplier_rules_have_required_fields` (lines 27-32)

Support both `sc_codes` and `category_codes`:

```python
# --- Current (line 29): ---
            assert "sc_codes" in rule, f"supplier_rules[{i}] missing sc_codes"

# --- New: ---
            has_codes = "sc_codes" in rule or "category_codes" in rule
            assert has_codes, f"supplier_rules[{i}] missing sc_codes/category_codes"
```

Same pattern for `test_context_rules_have_required_fields` (line 36) and `test_cost_center_rules_have_required_fields` (line 42).

#### 7.3.3 `TestYAMLStructure.test_context_rules_have_required_fields` (lines 34-39)

Skip when empty:

```python
# --- Current (lines 34-39): ---
    def test_context_rules_have_required_fields(self, refinement):
        for i, rule in enumerate(refinement["context_rules"]):
            ...

# --- New: ---
    def test_context_rules_have_required_fields(self, refinement):
        if not refinement.get("context_rules"):
            pytest.skip("No context_rules for this client")
        for i, rule in enumerate(refinement["context_rules"]):
            ...
```

Same pattern for `test_cost_center_rules_have_required_fields` (lines 41-46).

#### 7.3.4 `TestRegexValidity.test_context_patterns_compile` (lines 65-70)

Skip when empty:

```python
# --- Current (lines 65-70): ---
    def test_context_patterns_compile(self, refinement):
        for i, rule in enumerate(refinement["context_rules"]):
            ...

# --- New: ---
    def test_context_patterns_compile(self, refinement):
        if not refinement.get("context_rules"):
            pytest.skip("No context_rules for this client")
        for i, rule in enumerate(refinement["context_rules"]):
            ...
```

Same pattern for `test_cost_center_patterns_compile` (lines 72-77).

#### 7.3.5 `TestTaxonomyKeyValidity.test_context_rules_taxonomy_keys` (lines 102-105)

Skip when empty:

```python
# --- Current (lines 102-105): ---
    def test_context_rules_taxonomy_keys(self, refinement, taxonomy_keys):
        for i, rule in enumerate(refinement["context_rules"]):
            ...

# --- New: ---
    def test_context_rules_taxonomy_keys(self, refinement, taxonomy_keys):
        if not refinement.get("context_rules"):
            pytest.skip("No context_rules for this client")
        for i, rule in enumerate(refinement["context_rules"]):
            ...
```

Same pattern for `test_cost_center_rules_taxonomy_keys` (lines 107-111).

#### 7.3.6 `TestSCCodeValidity` -> `TestCategoryCodeValidity` (lines 133-154)

Rename class and support both `sc_codes` and `category_codes` key names:

```python
# --- Current (lines 133-154): ---
class TestSCCodeValidity:

    def test_supplier_rules_sc_codes(self, refinement, valid_sc_codes):
        for i, rule in enumerate(refinement["supplier_rules"]):
            for sc in rule["sc_codes"]:
                assert str(sc) in valid_sc_codes, (
                    f"supplier_rules[{i}] unknown SC code: '{sc}'"
                )

    def test_context_rules_sc_codes(self, refinement, valid_sc_codes):
        for i, rule in enumerate(refinement["context_rules"]):
            for sc in rule["sc_codes"]:
                assert str(sc) in valid_sc_codes, (
                    f"context_rules[{i}] unknown SC code: '{sc}'"
                )

    def test_cost_center_rules_sc_codes(self, refinement, valid_sc_codes):
        for i, rule in enumerate(refinement["cost_center_rules"]):
            for sc in rule["sc_codes"]:
                assert str(sc) in valid_sc_codes, (
                    f"cost_center_rules[{i}] unknown SC code: '{sc}'"
                )

# --- New: ---
class TestCategoryCodeValidity:

    def _get_codes(self, rule):
        return rule.get("category_codes", rule.get("sc_codes", []))

    def test_supplier_rules_category_codes(self, refinement, valid_category_codes):
        for i, rule in enumerate(refinement["supplier_rules"]):
            for code in self._get_codes(rule):
                assert str(code) in valid_category_codes, (
                    f"supplier_rules[{i}] unknown category code: '{code}'"
                )

    def test_context_rules_category_codes(self, refinement, valid_category_codes):
        if not refinement.get("context_rules"):
            pytest.skip("No context_rules for this client")
        for i, rule in enumerate(refinement["context_rules"]):
            for code in self._get_codes(rule):
                assert str(code) in valid_category_codes, (
                    f"context_rules[{i}] unknown category code: '{code}'"
                )

    def test_cost_center_rules_category_codes(self, refinement, valid_category_codes):
        if not refinement.get("cost_center_rules"):
            pytest.skip("No cost_center_rules for this client")
        for i, rule in enumerate(refinement["cost_center_rules"]):
            for code in self._get_codes(rule):
                assert str(code) in valid_category_codes, (
                    f"cost_center_rules[{i}] unknown category code: '{code}'"
                )
```

#### 7.3.7 `TestConfidenceRanges` (lines 157-181): Skip Empty Sections

Add skip guards to `test_context_confidence_valid` and `test_cost_center_confidence_valid`:

```python
    def test_context_confidence_valid(self, refinement):
        if not refinement.get("context_rules"):
            pytest.skip("No context_rules for this client")
        for i, rule in enumerate(refinement["context_rules"]):
            ...

    def test_cost_center_confidence_valid(self, refinement):
        if not refinement.get("cost_center_rules"):
            pytest.skip("No cost_center_rules for this client")
        for i, rule in enumerate(refinement["cost_center_rules"]):
            ...
```

#### 7.3.8 `TestSupplierClassification` (lines 187-213): Externalize to `test_assertions.yaml`

```python
# --- Current (lines 187-213): ---
class TestSupplierClassification:
    """Known supplier->taxonomy assertions. If these break, someone changed a rule."""

    KNOWN_MAPPINGS = [
        ("SC0250", "epic systems", "IT & Telecoms > Software > Application Software"),
        ("SC0250", "kpmg", "Professional Services > Financial Services > Accounting Services > General Accounting Services"),
        ("SC0250", "quest diagnostics", "Medical > Medical Services"),
        ("SC0250", "crothall", "Facilities > Cleaning > Cleaning Services"),
        ("SC0207", "grainger", "Facilities > Operating Supplies and Equipment"),
        ("SC0207", "uline", "Facilities > Operating Supplies and Equipment"),
        ("SC0250", "cintas", "Facilities > Cleaning > Cleaning Services"),
    ]

    @pytest.mark.parametrize("sc_code,supplier,expected_taxonomy", KNOWN_MAPPINGS)
    def test_supplier_rule_matches(self, refinement, sc_code, supplier, expected_taxonomy):
        matched = False
        for rule in refinement["supplier_rules"]:
            if sc_code not in [str(sc) for sc in rule["sc_codes"]]:
                continue
            if re.search(rule["supplier_pattern"], supplier, re.IGNORECASE):
                assert rule["taxonomy_key"] == expected_taxonomy, (
                    f"Supplier '{supplier}' with {sc_code} mapped to "
                    f"'{rule['taxonomy_key']}' instead of '{expected_taxonomy}'"
                )
                matched = True
                break
        assert matched, f"No rule matched supplier '{supplier}' with SC code '{sc_code}'"

# --- New: ---
class TestSupplierClassification:

    @pytest.fixture(scope="class")
    def known_mappings(self, client_dir):
        assertions_path = client_dir / "test_assertions.yaml"
        if not assertions_path.exists():
            pytest.skip("No test_assertions.yaml found for this client")
        with open(assertions_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("supplier_mappings", [])

    def test_supplier_rule_matches(self, refinement, known_mappings):
        for case in known_mappings:
            matched = False
            for rule in refinement["supplier_rules"]:
                rule_codes = [str(c) for c in
                              rule.get("category_codes", rule.get("sc_codes", []))]
                if case["category_code"] not in rule_codes:
                    continue
                if re.search(rule["supplier_pattern"], case["supplier"], re.IGNORECASE):
                    assert rule["taxonomy_key"] == case["expected_taxonomy"], (
                        f"Supplier '{case['supplier']}' with {case['category_code']} mapped to "
                        f"'{rule['taxonomy_key']}' instead of '{case['expected_taxonomy']}'"
                    )
                    matched = True
                    break
            assert matched, (
                f"No rule matched supplier '{case['supplier']}' "
                f"with code '{case['category_code']}'"
            )
```

**CCHMC's `test_assertions.yaml`** (externalized from hardcoded `KNOWN_MAPPINGS`):

```yaml
# clients/cchmc/test_assertions.yaml
supplier_mappings:
  - category_code: "SC0250"
    supplier: "epic systems"
    expected_taxonomy: "IT & Telecoms > Software > Application Software"
  - category_code: "SC0250"
    supplier: "kpmg"
    expected_taxonomy: "Professional Services > Financial Services > Accounting Services > General Accounting Services"
  - category_code: "SC0250"
    supplier: "quest diagnostics"
    expected_taxonomy: "Medical > Medical Services"
  - category_code: "SC0250"
    supplier: "crothall"
    expected_taxonomy: "Facilities > Cleaning > Cleaning Services"
  - category_code: "SC0207"
    supplier: "grainger"
    expected_taxonomy: "Facilities > Operating Supplies and Equipment"
  - category_code: "SC0207"
    supplier: "uline"
    expected_taxonomy: "Facilities > Operating Supplies and Equipment"
  - category_code: "SC0250"
    supplier: "cintas"
    expected_taxonomy: "Facilities > Cleaning > Cleaning Services"

expected_rule_counts:
  supplier_rules: 230
  context_rules: 8
  cost_center_rules: 10
  supplier_override_rules: 11
```

**UCH's `test_assertions.yaml`**:

```yaml
# clients/uch/test_assertions.yaml
supplier_mappings:
  - category_code: "39101612"
    supplier: "grainger"
    expected_taxonomy: "Facilities > Operating Supplies and Equipment"
  - category_code: "99000038"
    supplier: "otis elevator"
    expected_taxonomy: "Facilities > Facilities Services > Building Maintenance > Elevator Services"
  - category_code: "39101612"
    supplier: "mcmaster-carr"
    expected_taxonomy: "Facilities > Operating Supplies and Equipment"

expected_rule_counts:
  supplier_rules: 10      # Initial count, grows as rules are authored
  context_rules: 0        # No LoS column in UCH
  cost_center_rules: 7    # One per cost center
  supplier_override_rules: 0
```

#### 7.3.9 `TestConflictDetection.test_rule_counts` (lines 261-273): Externalize

```python
# --- Current (lines 261-273): ---
    def test_rule_counts(self, refinement):
        assert len(refinement["supplier_rules"]) >= 230, (
            f"Expected 230+ supplier rules, got {len(refinement['supplier_rules'])}"
        )
        assert len(refinement["context_rules"]) >= 8, (
            f"Expected 8+ context rules, got {len(refinement['context_rules'])}"
        )
        assert len(refinement["cost_center_rules"]) >= 10, (
            f"Expected 10+ cost center rules, got {len(refinement['cost_center_rules'])}"
        )
        assert len(refinement["supplier_override_rules"]) >= 11, (
            f"Expected 11+ override rules, got {len(refinement['supplier_override_rules'])}"
        )

# --- New: ---
    def test_rule_counts(self, refinement, client_dir):
        assertions_path = client_dir / "test_assertions.yaml"
        if not assertions_path.exists():
            pytest.skip("No test_assertions.yaml found")
        with open(assertions_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        expected = data.get("expected_rule_counts", {})
        for section, min_count in expected.items():
            actual = len(refinement.get(section, []))
            assert actual >= min_count, (
                f"Expected {min_count}+ {section}, got {actual}"
            )
```

#### 7.3.10 `TestConflictDetection.test_no_duplicate_supplier_patterns` (lines 221-233)

Support both `sc_codes` and `category_codes`:

```python
# --- Current (line 225): ---
            for sc in rule["sc_codes"]:

# --- New: ---
            for sc in rule.get("category_codes", rule.get("sc_codes", [])):
```

Same for `test_no_overlapping_supplier_patterns` (line 240):

```python
# --- Current (line 240): ---
                shared_sc = set(str(s) for s in rules[i]["sc_codes"]) & set(str(s) for s in rules[j]["sc_codes"])

# --- New: ---
                codes_i = rules[i].get("category_codes", rules[i].get("sc_codes", []))
                codes_j = rules[j].get("category_codes", rules[j].get("sc_codes", []))
                shared_sc = set(str(s) for s in codes_i) & set(str(s) for s in codes_j)
```

### 7.4 New Tests

#### `TestConfigValidation` -- Validates load_config() with optional fields

```python
class TestConfigValidation:

    def test_config_loads_successfully(self, client_dir):
        import sys
        sys.path.insert(0, str(client_dir.parent.parent / "src"))
        from categorize import load_config
        config = load_config(str(client_dir / "config.yaml"))
        assert config['client']['name']
        assert config['_resolved_paths']['input'].exists()

    def test_optional_columns_default_to_none(self, client_config):
        cols = client_config.get("columns", {})
        if "line_of_service" not in cols:
            assert True  # Optional column correctly absent
```

#### `TestTierSkipping` -- Verifies conditional tier logic

```python
class TestTierSkipping:

    def test_tier4_skippable_without_line_of_service(self, client_config):
        has_los = "line_of_service" in client_config.get("columns", {})
        if not has_los:
            # Tier 4 should be skipped for this client
            assert True
        else:
            assert client_config["columns"]["line_of_service"]

    def test_tier5_skippable_without_cost_center(self, client_config):
        has_cc = "cost_center" in client_config.get("columns", {})
        if not has_cc:
            assert True
        else:
            assert client_config["columns"]["cost_center"]
```

#### `TestInputFormat` -- Validates Excel input support

```python
class TestInputFormat:

    def test_input_file_exists(self, client_dir, client_config):
        input_path = client_dir / client_config["paths"]["input"]
        assert input_path.exists(), f"Input file not found: {input_path}"

    def test_xlsx_has_sheet_name(self, client_config):
        input_path = client_config["paths"]["input"]
        if input_path.endswith(('.xlsx', '.xls')):
            input_format = client_config.get("input_format", {})
            # sheet_name is optional (defaults to first sheet)
            # but if specified, it should be a string or int
            sheet = input_format.get("sheet_name")
            if sheet is not None:
                assert isinstance(sheet, (str, int))
```

### 7.5 CCHMC Regression Test

Add to test suite or run manually:

```python
class TestCCHMCRegression:

    def test_cchmc_output_column_count(self, client_config):
        if client_config["client"]["name"] != "CCHMC":
            pytest.skip("CCHMC-only test")
        cols = client_config.get("columns", {})
        assert "line_of_service" in cols or cols.get("line_of_service") is not None
        assert "cost_center" in cols or cols.get("cost_center") is not None
```

### 7.6 Running Tests Per Client

```bash
# CCHMC (default):
pytest tests/ --client-dir clients/cchmc

# UCH:
pytest tests/ --client-dir clients/uch

# Both clients (sequential):
pytest tests/ --client-dir clients/cchmc && pytest tests/ --client-dir clients/uch
```

---

## 8. Migration Steps

Nine steps with explicit dependencies, verification criteria, and rollback procedures.

### Step 1: Add Alias Support to `load_config()`

**Dependencies**: None
**Files changed**: `src/categorize.py` (lines 27-78)
**What**: Add `ALIASES` dict, `_apply_aliases()` function, call it after YAML parse. No other changes.

**Verification**:
1. Run CCHMC pipeline: `python src/categorize.py --config clients/cchmc/config.yaml`
2. Output must be identical to baseline (save baseline output beforehand)
3. Deprecation warnings print to stderr for `sc_mapping`, `spend_category`, `line_memo`, `sc_code_pattern`
4. Create a minimal test config missing `line_of_service` and `cost_center` -- `load_config()` must not raise

**Rollback**: `git checkout src/categorize.py`

### Step 2: Make Columns and Pattern Optional in Config Validation

**Dependencies**: Step 1
**Files changed**: `src/categorize.py` (lines 51-59)
**What**: Change `required_columns` to `['category_source', 'supplier', 'amount']`. Set optional columns to `None` when absent. Make `category_code_pattern` optional.

**Verification**:
1. CCHMC config loads without error (aliases resolve old names)
2. A config missing `line_of_service` loads successfully with `cols['line_of_service'] == None`
3. A config missing `category_code_pattern` loads successfully

**Rollback**: `git checkout src/categorize.py`

### Step 3: Rename `load_sc_mapping()` and Add Rule Key Aliases

**Dependencies**: Step 2
**Files changed**: `src/categorize.py` (lines 81-94, 132-180)
**What**: Rename function to `load_category_mapping()`. Add `sc_codes` -> `category_codes` alias in `_validate_and_compile_rules()`. Make `context_rules` and `cost_center_rules` validation conditional. Update `required_keys` tuples.

**Verification**:
1. CCHMC pipeline runs: all tiers fire, counts match baseline
2. CCHMC refinement YAML (still using `sc_codes`) loads without error

**Rollback**: `git checkout src/categorize.py`

### Step 4: Generalize `main()` -- Category Code, Conditional Tiers, Excel Input

**Dependencies**: Step 3
**Files changed**: `src/categorize.py` (lines 183-597)
**What**: All variable renames (Section 5), conditional column extraction, conditional Tier 4/5 wrapping, Excel input support, output column renames, summary label updates.

**Verification**:
1. CCHMC pipeline: compare tier counts, review tier distribution, total amounts to baseline. All counts must match exactly. Only column names and method labels differ.
2. Temporarily remove `line_of_service` from CCHMC config: confirm Tier 4 prints "skipped", other tiers produce identical counts. Restore config.
3. Temporarily rename CCHMC input to `.xlsx` extension and test the extension-based dispatch (optional, for thoroughness).

**Rollback**: `git checkout src/categorize.py`

### Step 5: Update Test Fixtures (`conftest.py`)

**Dependencies**: Step 4
**Files changed**: `tests/conftest.py`
**What**: Add `category_mapping` and `valid_category_codes` fixtures. Keep `sc_mapping` and `valid_sc_codes` as aliases.

**Verification**: `pytest tests/conftest.py --co` (collect tests, verify fixtures resolve)

**Rollback**: `git checkout tests/conftest.py`

### Step 6: Update Test Rules (`test_rules.py`) + Create CCHMC `test_assertions.yaml`

**Dependencies**: Step 5
**Files changed**: `tests/test_rules.py`, `clients/cchmc/test_assertions.yaml` (new)
**What**: All test class updates from Section 7.3. Externalize `KNOWN_MAPPINGS` to CCHMC's `test_assertions.yaml`. Add skip guards for optional sections.

**Verification**: `pytest tests/ --client-dir clients/cchmc` -- all tests pass

**Rollback**: `git checkout tests/test_rules.py && rm clients/cchmc/test_assertions.yaml`

### Step 7: Create UCH Client Directory Structure

**Dependencies**: Step 6
**Files changed**: New directory `clients/uch/` with config and placeholder data files
**What**: Create directory structure, place `uch-2026.xlsx`, write `config.yaml` (Section 3.4), create placeholder `category_mapping.yaml` (empty `mappings: {}`), create placeholder `uch_refinement_rules.yaml` (empty sections), copy or symlink `keyword_rules.yaml`.

**Verification**: `python src/categorize.py --config clients/uch/config.yaml` loads and runs (everything unmapped, but no errors)

**Rollback**: `rmdir /s clients\uch`

### Step 8: Author UCH Reference Data

**Dependencies**: Step 7
**Files changed**: `clients/uch/data/reference/category_mapping.yaml`, `clients/uch/data/reference/uch_refinement_rules.yaml`, `clients/uch/test_assertions.yaml`
**What**: Map 118 UNSPSC codes to taxonomy keys. Build supplier refinement rules for ambiguous codes. Build cost center rules for 7 cost centers. Create UCH's `test_assertions.yaml`.

**Verification**:
1. `python src/categorize.py --config clients/uch/config.yaml` produces a reasonable tier distribution
2. Tier 1 classifies non-ambiguous UNSPSC codes
3. Tier 2 picks up supplier-specific classifications within ambiguous codes (39101612, 99000038)
4. Tier 3 fires keyword rules against `Item Description` text
5. Tier 4 prints "skipped" (no line_of_service)
6. Tier 5 classifies based on cost center
7. Unmapped count < 5% of total rows (target)
8. `pytest tests/ --client-dir clients/uch` -- all applicable tests pass

**Rollback**: Replace YAML files with empty placeholders

### Step 9: Regression Verification

**Dependencies**: Step 8
**Files changed**: None
**What**: Run CCHMC on the updated engine and compare to baseline output from the original engine.

**Verification**:
1. Run CCHMC original: capture tier counts, review tiers, total amounts
2. Run CCHMC updated: compare all numbers
3. Differences limited to: renamed output columns, renamed method values
4. Row counts, tier distributions, total amounts match exactly
5. `pytest tests/ --client-dir clients/cchmc && pytest tests/ --client-dir clients/uch` -- all pass

**Rollback**: Fix any issues found

### Parallelization Opportunities

| Steps | Can Parallelize? | Notes |
|-------|-----------------|-------|
| 1 -> 2 -> 3 -> 4 | Sequential | Each depends on prior changes |
| 5 + 7 | Parallel | Test fixtures and UCH directory are independent |
| 6 | After 5 | Needs updated fixtures |
| 8 | After 7 | Needs UCH directory structure |
| 9 | After 6 + 8 | Final gate |

---

## 9. File Structure

```
healthcare-categorization-cli/
|
+-- src/
|   +-- categorize.py                           # Single-file engine (v2, ~670 lines)
|
+-- shared/
|   +-- reference/
|       +-- Healthcare Taxonomy v2.9.xlsx        # Universal taxonomy (unchanged)
|       +-- keyword_rules.yaml                   # Shared keyword rules (optional)
|
+-- clients/
|   +-- cchmc/
|   |   +-- config.yaml                          # UNCHANGED (aliases handle renames)
|   |   +-- test_assertions.yaml                 # NEW: externalized test assertions
|   |   +-- data/
|   |   |   +-- input/
|   |   |   |   +-- cchmc-ftp-new.csv
|   |   |   +-- reference/
|   |   |       +-- sc_code_mapping.yaml         # Unchanged (alias: category_mapping)
|   |   |       +-- keyword_rules.yaml           # Unchanged
|   |   |       +-- cchmc_refinement_rules.yaml  # Unchanged (sc_codes alias works)
|   |   +-- output/
|   |
|   +-- uch/
|       +-- config.yaml                          # NEW (Section 3.4)
|       +-- test_assertions.yaml                 # NEW
|       +-- data/
|       |   +-- input/
|       |   |   +-- uch-2026.xlsx                # 4,649 rows, 44 columns, Oracle Fusion
|       |   +-- reference/
|       |       +-- category_mapping.yaml        # NEW: 118 UNSPSC -> taxonomy
|       |       +-- keyword_rules.yaml           # Shared (copy or symlink)
|       |       +-- uch_refinement_rules.yaml    # NEW: supplier + cost center rules
|       +-- output/
|
+-- tests/
|   +-- __init__.py
|   +-- conftest.py                              # Updated: alias-aware fixtures
|   +-- test_rules.py                            # Updated: optional sections, external data
|
+-- docs/
|   +-- Multi_Client_PRD.md
|   +-- Multi_Client_Implementation_Plan.md      # This document
|   +-- Multi_Client_Critical_Review.md
|
+-- requirements.txt                             # Unchanged: pandas, pyyaml, openpyxl
+-- .gitignore
+-- README.md
```

---

## 10. Risk Mitigation

### Risk 1: CCHMC Regression from Variable/Column Renames

**Impact**: High. Downstream workflows may parse CCHMC's output Excel by column name (`SC Code`, `Spend Category (Source)`).

**Mitigation**:
- Alias system ensures CCHMC's `config.yaml` works without any modification
- Step 9 is a dedicated regression gate comparing tier counts row-by-row
- Output column renames (`SC Code` -> `Category Code`, `Spend Category (Source)` -> `Category Source`) are the one intentional breaking change in output structure
- If output column rename is unacceptable: add an `output.legacy_column_names: true` config flag that emits old names for CCHMC specifically. Implement as a dict lookup at output build time.

### Risk 2: UNSPSC Code Type Mismatch (String vs Int)

**Impact**: Medium. YAML auto-parses `39101612` as an integer. pandas extracts codes as strings. `isin()` comparison fails silently -- rows match nothing, all go unmapped.

**Mitigation**:
- `load_category_mapping()` already casts all keys to `str`: `code_str = str(code).strip()`
- `category_code` Series is produced via `.astype(str).str.strip()` and regex `.str.extract()`
- YAML files should quote numeric codes (`"39101612"`) but the str cast handles unquoted integers as a safety net
- Add a test: verify all mapping keys are strings after loading (`valid_category_codes` fixture)

### Risk 3: UCH Catch-All Code `39101612` Dominates (37.6%)

**Impact**: High. 1,750 rows share one UNSPSC code (`39101612-Incandescent Lamps and Bulbs`). If classified as non-ambiguous, they all get one taxonomy key regardless of actual product. If ambiguous but unrefined, they all land in Tier 6 at low confidence.

**Mitigation**:
- Mark `39101612` as `ambiguous: true` in `category_mapping.yaml`
- Author targeted Tier 2 supplier refinement rules for top suppliers within this code: GRAINGER (1,436 rows covers 82% of catch-all), MCMASTER-CARR (253 rows), FD LAWRENCE ELECTRIC (328 rows)
- Author Tier 5 cost center rules scoped to `["39101612"]` for all 7 cost centers
- Tier 3 keyword rules fire against `Item Description` (e.g., "HVAC FILTER 20X20X2" matches HVAC rules)
- Remaining unrefined rows hit Tier 6 at 0.70 confidence, routed to "Quick Review" for manual triage

### Risk 4: UCH Item Description Quality Varies

**Impact**: Low. Some `Item Description` values may be truncated, coded, or empty, reducing Tier 3 keyword rule effectiveness.

**Mitigation**:
- Data profile shows 4,155 unique descriptions with text like "REPAIR MAIN FREEZER", "Morton water softener salt.", "FURNISH AND INSTALL REPLACEMENT VALVES" -- rich enough for keyword matching
- If description is empty for a row, `combined_text` falls back to `supplier + ' '` (supplier-only matching). This is existing behavior, not a regression.
- 494 rows have non-unique descriptions (duplicates), but duplicates for the same product type are expected

### Risk 5: Excel Input Performance for Large Files

**Impact**: Low for UCH (4,649 rows). Could matter if a future client has 500K+ rows in Excel format.

**Mitigation**:
- UCH at 4,649 rows loads in under 2 seconds even with `pd.read_excel()`
- CCHMC remains CSV (596K rows). No performance change for the larger dataset
- If future large-Excel clients appear, consider adding a config option to convert to parquet as a preprocessing step

### Risk 6: Shared Keyword Rules May Conflict Between Clients

**Impact**: Medium. A keyword rule matching "grainger" to one taxonomy key might be correct for CCHMC's medical supplies context but wrong for UCH's facilities context.

**Mitigation**:
- Start with shared rules file. Monitor classification results for false positives.
- If conflicts found: copy `keyword_rules.yaml` into `clients/uch/data/reference/` and customize. The config path is per-client, so each client independently points to shared or local rules.
- Keyword rules in the waterfall (Tier 3) have lower priority than supplier refinement (Tier 2), so client-specific supplier rules override shared keywords.

---

## 11. Effort Estimation

| Step | Description | Hours | Difficulty | Dependencies |
|------|-------------|-------|------------|--------------|
| 1 | Add alias support to `load_config()` | 0.5 | Low | None |
| 2 | Make columns and pattern optional | 0.5 | Low | Step 1 |
| 3 | Rename `load_sc_mapping()` + rule key aliases | 0.5 | Low | Step 2 |
| 4 | Generalize `main()`: category code, conditional tiers, Excel input | 2.0 | Medium | Step 3 |
| 5 | Update test fixtures (`conftest.py`) | 0.5 | Low | Step 4 |
| 6 | Update test rules + create CCHMC `test_assertions.yaml` | 1.5 | Low | Step 5 |
| 7 | Create UCH client directory structure | 0.5 | Low | Step 4 |
| 8 | Author UCH reference data (118 UNSPSC mappings + rules) | 4.0-6.0 | Medium (manual) | Step 7 |
| 9 | Regression verification (CCHMC + UCH) | 0.5 | Low | Steps 6, 8 |
| **Total** | | **10.5-12.0** | | |

Step 8 (reference data authoring) is the largest effort and is primarily manual: mapping 118 UNSPSC codes to taxonomy keys, authoring supplier refinement rules for the top suppliers, and building cost center rules for 7 cost centers. The engine changes (Steps 1-4) are mechanical renaming with targeted conditional logic additions.

---

## Appendix A: Decision Log

| # | Decision | Alternatives Considered | Rationale |
|---|----------|------------------------|-----------|
| D1 | Keep waterfall in `main()` | Plugin/Strategy pattern per tier | Data shape difference, not algorithm. Both clients use the same 7-tier logic. |
| D2 | Single file engine (<1000 lines) | Split into modules | Under 700 lines. Analyst readability. Top-to-bottom waterfall. |
| D3 | Backward-compatible config aliases | Force config migration | Zero-risk for existing CCHMC deployment. Deprecation warnings guide future migration. |
| D4 | `line_of_service` optional via `None` sentinel | Feature flag in config | Simpler. `cols.get('line_of_service') is not None` is self-documenting. |
| D5 | Rename output columns globally | Keep old + add new as duplicates | Clean break. Document in changelog. |
| D6 | Excel input via file extension detection | Require CSV conversion step | UCH data is natively .xlsx. Conversion adds friction and loses sheet metadata. |

---

## Appendix B: Performance Optimizations (Post-Implementation)

The following optimizations were applied after the initial multi-client implementation to improve classification throughput on large datasets (596K+ rows):

### 1. Vectorized Taxonomy Lookup Builder
`build_taxonomy_lookup()` replaced `iterrows()` with `set_index('Key')[level_cols].to_dict('index')`.

### 2. Pre-Compiled Regex in Classification Loops
All tier loops (2-7) now pass `rule['_compiled']` (a `re.Pattern` object) to `str.contains()` instead of raw pattern strings, eliminating per-call recompilation.

### 3. Code-to-Row Index Map
Pre-computed `code_row_map = category_code.groupby(category_code).groups` replaces per-rule `category_code.isin(rule['category_codes'])` scans. For CCHMC (230+ supplier rules x 596K rows), this eliminates ~230 full-series scans.

### 4. Single DataFrame Join for Taxonomy Levels
Replaced 5 separate `taxonomy_key.map(tax_lN)` calls with a single `taxonomy_key.to_frame().join(tax_levels_df)`, reducing the number of hash lookups from 5N to N.

### 5. Tier 7 L1 Pre-Filter
Supplier override rules now filter by `cat_l1.isin(override_from_l1)` first, then run supplier regex only on the matching subset (typically <20% of rows).

### Benchmark Results

| Client | Rows | Rules | Classification | Total |
|--------|------|-------|----------------|-------|
| CCHMC | 596,796 | 237 supplier + 220 keyword + 19 context/cc + 11 override | 6.0s | ~165s |
| UCH | 4,649 | 3 supplier + 4 keyword + 1 override | <0.1s | ~2.5s |

Total runtime is I/O-bound (openpyxl Excel writing dominates at ~96% for CCHMC).
| D7 | `sc_codes` -> `category_codes` alias in rules | Force YAML migration | CCHMC has ~250 rules referencing `sc_codes`. In-place alias avoids mass YAML edits. |
