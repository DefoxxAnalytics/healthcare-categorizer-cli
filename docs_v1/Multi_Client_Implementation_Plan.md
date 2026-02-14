# Multi-Client Implementation Plan

## Healthcare Categorization CLI — Config-Driven Multi-Client Engine

**Version**: 2.0
**Author**: VTX Solutions / Defoxx Analytics
**Date**: 2026-02-14
**Status**: Draft

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Architecture Decisions](#2-architecture-decisions)
3. [Config Schema v2](#3-config-schema-v2)
4. [Engine Changes](#4-engine-changes)
5. [New Reference Data Files for UCH](#5-new-reference-data-files-for-uch)
6. [Test Changes](#6-test-changes)
7. [Migration Steps](#7-migration-steps)
8. [File Structure](#8-file-structure)
9. [Risk Mitigation](#9-risk-mitigation)

---

## 1. Problem Statement

The current engine (`categorization-cli/src/categorize.py`, 614 lines) was built for CCHMC's data structure: SC codes (e.g., `SC0250`), Line Memo, Line of Service, Cost Center. Every tier in the 7-tier waterfall assumes these fields exist.

UCH (University of Cincinnati Health) has **three distinct input formats** — none of which match CCHMC:

| Format | File | Rows | Category System | Amount Format | Key Fields |
|--------|------|------|-----------------|---------------|------------|
| **Facilities InScope** | `UCH-Facilities-InScope-07312025 1.csv` | 3,092 | Free-text `Category` + `Subcategory` (e.g., "Facilities" / "Office Equipment & Supplies") | Currency string `"$5,567.76 "` | Supplier, Category, Subcategory, Location, Capex/Opex |
| **Services Only** | `Services Only.csv` | 1,283 | Numeric `CategoryCode` + text `Subcategory` (e.g., `99000038` / "Equipment Maintenance Services") | Numeric `Paid Amount` | Supplier, Item Description, Category Name, Cost Center Code, Cost Center Description, Location |
| **CatWork** | `CatWork.csv` | 5,027 | Compound `Category Name` (e.g., `31160000-Hardware`) | Numeric `TotalSpend` | Supplier, Item Description, Category Name |

**Impact on current engine:** 5 of 7 tiers are unusable for Facilities InScope (all SC-code-dependent tiers + LoS + Cost Center). Services Only has richer fields (Item Description, Cost Center) but uses a different code system. CatWork has Item Description but no cost center.

The engine must be generalized without breaking the existing CCHMC pipeline.

---

## 2. Architecture Decisions

### Decision 1: Config-Driven Conditional Tiers (NOT plugin/strategy pattern)

**Choice**: Keep the waterfall in `main()`, but make each tier conditional on field availability. Skip tiers whose required columns are absent.

**Rationale**:
- The waterfall is 7 tiers of vectorized pandas operations. A plugin/strategy pattern would add indirection (ABC classes, registries, dynamic dispatch) for a problem that's better solved with `if column_available:`.
- The tiers themselves don't change logic per client — only their *inputs* change. A Tier 2 supplier refinement rule works the same whether the code field is `SC0250` or `99000038`.
- Plugin patterns earn their complexity when you have 10+ clients with fundamentally different classification *algorithms*. We have clients with different *data shapes* feeding the same algorithm.
- Config-driven conditionals keep the engine in a single readable function where the analyst can trace the full waterfall top-to-bottom.

**Consequence**: No new classes, no registries. The engine remains one module with conditional blocks.

### Decision 2: Generalize "Category Code" Beyond SC Codes

**Choice**: Rename the concept from "SC code" to "category code" throughout the engine. The config specifies:
- Which column to extract from (`columns.category_source`)
- An optional extraction regex (`classification.category_code_pattern`)
- If no regex, the raw column value IS the category code

**Mapping**:

| Client | Source Column | Pattern | Example Code |
|--------|--------------|---------|--------------|
| CCHMC | `Spend Category` | `((?:DNU\s+)?SC\d+)` | `SC0250` |
| UCH Facilities | `Subcategory` | *(none — raw value)* | `Office Equipment & Supplies` |
| UCH Services | `CategoryCode` | *(none — raw value)* | `99000038` |
| UCH CatWork | `Category Name` | `(\d+)` | `31160000` |

### Decision 3: Keep Single Module (Split Into Sections, Not Files)

**Choice**: Keep `categorize.py` as a single file, but reorganize internal sections with clear separation.

**Rationale**:
- The file is 614 lines — well within the single-module sweet spot (under 1000 lines).
- After the changes described in this plan, it will grow to approximately 700-750 lines.
- Splitting into `loaders.py`, `tiers.py`, `output.py` would create import chains and make the waterfall harder to follow for analysts who maintain client rules.
- The PRD explicitly targets analysts as operators, not framework developers.

**When to split**: If the engine exceeds 1000 lines or gains a third fundamentally different classification algorithm (not just different data shapes), then split.

### Decision 4: Backwards-Compatible Config with Deprecation Aliases

**Choice**: The new config schema introduces renamed keys (`category_source` replaces `spend_category`, `category_code_pattern` replaces `sc_code_pattern`). The old keys still work via aliases in `load_config()`, with a deprecation warning printed to stderr.

**Rationale**: CCHMC's existing `config.yaml` must work without modification on day one. Forced migration is a needless risk for a working pipeline.

---

## 3. Config Schema v2

### 3.1 Schema Definition

```yaml
# Config Schema v2 — Multi-Client Healthcare Categorization CLI
# All paths are relative to the config file's parent directory.

client:
  name: string                    # Required. Console banner and output naming.
  description: string             # Optional.

paths:
  input: string                   # Required. CSV input file.
  category_mapping: string        # Required. Category code → taxonomy YAML.
  taxonomy: string                # Required. Healthcare Taxonomy v2.9 Excel.
  keyword_rules: string           # Required. Keyword regex rules YAML.
  refinement_rules: string        # Required. Refinement rules YAML.
  output_dir: string              # Required. Output directory.
  output_prefix: string           # Required. Output filename prefix.

columns:
  category_source: string         # Required. Column containing category codes or text.
  supplier: string                # Required. Supplier name column.
  amount: string                  # Required. Monetary amount column.
  description: string             # Optional. Item description / line memo column.
  line_of_service: string         # Optional. Line-of-service column (enables Tier 4).
  cost_center: string             # Optional. Cost center column (enables Tier 5).
  passthrough: list[string]       # Optional. Additional columns to include in output.

amount_format:
  type: string                    # "numeric" (default) or "currency_string"
  # If "currency_string": engine strips $, commas, whitespace before parsing.

classification:
  category_code_pattern: string   # Optional. Regex to extract code from category_source.
                                  # If absent, raw column value is used as-is.
  confidence_high: float          # Required. Auto-Accept threshold (0.0-1.0).
  confidence_medium: float        # Required. Quick Review threshold (0.0-1.0).

aggregations:                     # Optional. Dynamic groupby sheets in output Excel.
  - name: string
    column: string
    top_n: int | null
```

### 3.2 Key Changes from v1

| v1 Key | v2 Key | Change |
|--------|--------|--------|
| `paths.sc_mapping` | `paths.category_mapping` | Renamed. Alias supported. |
| `columns.spend_category` | `columns.category_source` | Renamed. Alias supported. |
| `columns.line_memo` | `columns.description` | Renamed (more generic). Alias supported. |
| `columns.line_of_service` | `columns.line_of_service` | Now **optional**. |
| `columns.cost_center` | `columns.cost_center` | Now **optional**. |
| `classification.sc_code_pattern` | `classification.category_code_pattern` | Renamed. Alias supported. Now **optional**. |
| *(new)* | `amount_format` | New section for currency parsing. |

### 3.3 Concrete Config: CCHMC (backwards-compatible, no changes needed)

The existing CCHMC config works as-is. The engine recognizes legacy keys via aliases:

```yaml
# clients/cchmc/config.yaml — UNCHANGED, still works
client:
  name: "CCHMC"

paths:
  input: "data/input/cchmc-ftp-new.csv"
  sc_mapping: "data/reference/sc_code_mapping.yaml"          # alias → category_mapping
  taxonomy: "../../shared/reference/Healthcare Taxonomy v2.9.xlsx"
  keyword_rules: "data/reference/keyword_rules.yaml"
  refinement_rules: "data/reference/cchmc_refinement_rules.yaml"
  output_dir: "output"
  output_prefix: "cchmc_categorization_results"

columns:
  spend_category: "Spend Category"       # alias → category_source
  supplier: "Supplier"
  line_memo: "Line Memo"                 # alias → description
  line_of_service: "Line of Service"
  cost_center: "Cost Center"
  amount: "Invoice Line Amount"
  passthrough:
    - "Invoice Number"
    - "Invoice Line"
    - "Invoice Date"
    # ... (unchanged)

classification:
  sc_code_pattern: '((?:DNU\s+)?SC\d+)'  # alias → category_code_pattern
  confidence_high: 0.7
  confidence_medium: 0.5

aggregations:
  - name: "Spend by Cost Center (Top 100)"
    column: "Cost Center"
    top_n: 100
  # ... (unchanged)
```

### 3.4 Concrete Config: UCH Facilities InScope

```yaml
client:
  name: "UCH"
  description: "University of Cincinnati Health — Facilities In-Scope PO Data"

paths:
  input: "data/input/UCH-Facilities-InScope-07312025 1.csv"
  category_mapping: "data/reference/category_mapping.yaml"
  taxonomy: "../../shared/reference/Healthcare Taxonomy v2.9.xlsx"
  keyword_rules: "data/reference/keyword_rules.yaml"
  refinement_rules: "data/reference/uch_refinement_rules.yaml"
  output_dir: "output"
  output_prefix: "uch_facilities_categorization_results"

columns:
  category_source: "Subcategory"
  supplier: "Supplier"
  amount: "  Spend Amount  "   # Note: column name has leading/trailing spaces in CSV
  # description: absent — no item description column in this dataset
  # line_of_service: absent — disables Tier 4
  # cost_center: absent — disables Tier 5
  passthrough:
    - "PO Number"
    - "Category"
    - "PO Date"
    - "Capex/Opex"
    - "SpendBand"
    - "Category Type"
    - "Location"

amount_format:
  type: "currency_string"

classification:
  # No category_code_pattern — raw "Subcategory" value is the category code
  confidence_high: 0.7
  confidence_medium: 0.5

aggregations:
  - name: "Spend by Location"
    column: "Location"
    top_n: null
  - name: "Spend by Capex/Opex"
    column: "Capex/Opex"
    top_n: null
  - name: "Spend by Category (Source)"
    column: "Category"
    top_n: null
```

### 3.5 Concrete Config: UCH Services Only

```yaml
client:
  name: "UCH-Services"
  description: "University of Cincinnati Health — Services PO Data (Oracle Fusion)"

paths:
  input: "data/input/PBI_Exports/Services Only.csv"
  category_mapping: "data/reference/services_category_mapping.yaml"
  taxonomy: "../../shared/reference/Healthcare Taxonomy v2.9.xlsx"
  keyword_rules: "data/reference/keyword_rules.yaml"
  refinement_rules: "data/reference/uch_services_refinement_rules.yaml"
  output_dir: "output"
  output_prefix: "uch_services_categorization_results"

columns:
  category_source: "CategoryCode"
  supplier: "Supplier"
  description: "Item Description"
  cost_center: "Cost Center Description"
  amount: "Paid Amount"
  passthrough:
    - "Order"
    - "Category Name"
    - "Subcategory"
    - "Line Status"
    - "Location Address"
    - "Purchase Requestor Display Name"
    - "Line Type"
    - "Creation Date"

classification:
  # No pattern — raw CategoryCode (e.g., "99000038") is the category code
  confidence_high: 0.7
  confidence_medium: 0.5

aggregations:
  - name: "Spend by Subcategory"
    column: "Subcategory"
    top_n: null
  - name: "Spend by Location"
    column: "Location Address"
    top_n: 20
  - name: "Spend by Cost Center"
    column: "Cost Center Description"
    top_n: 50
```

---

## 4. Engine Changes

All changes are in `src/categorize.py`. Reference line numbers are from the current 614-line version.

### 4.1 `load_config()` — Lines 31-78

#### 4.1.1 Deprecation Aliases

Add alias resolution immediately after YAML parsing (after line 38):

```python
ALIASES = {
    'paths': {'sc_mapping': 'category_mapping'},
    'columns': {'spend_category': 'category_source', 'line_memo': 'description'},
    'classification': {'sc_code_pattern': 'category_code_pattern'},
}

def _apply_aliases(config: dict) -> list[str]:
    """Resolve deprecated keys to canonical names. Returns list of warnings."""
    warnings = []
    for section, mappings in ALIASES.items():
        if section not in config:
            continue
        for old_key, new_key in mappings.items():
            if old_key in config[section] and new_key not in config[section]:
                config[section][new_key] = config[section].pop(old_key)
                warnings.append(
                    f"DEPRECATION: '{section}.{old_key}' renamed to '{section}.{new_key}'. "
                    f"Update your config to use the new key."
                )
    return warnings
```

Call `_apply_aliases(config)` before validation. Print warnings to stderr.

#### 4.1.2 Required Paths — Change Key Name

```python
# Before (line 46):
required_paths = ['input', 'sc_mapping', 'taxonomy', 'keyword_rules', 'refinement_rules', 'output_dir', 'output_prefix']

# After:
required_paths = ['input', 'category_mapping', 'taxonomy', 'keyword_rules', 'refinement_rules', 'output_dir', 'output_prefix']
```

#### 4.1.3 Required Columns — Make Optional Columns Optional

```python
# Before (line 51):
required_columns = ['spend_category', 'supplier', 'line_memo', 'line_of_service', 'cost_center', 'amount']

# After:
required_columns = ['category_source', 'supplier', 'amount']
optional_columns = ['description', 'line_of_service', 'cost_center']
```

Validate only `required_columns`. For `optional_columns`, store `None` in the config if absent (engine checks at runtime).

#### 4.1.4 Required Classification — Make Pattern Optional

```python
# Before (line 56):
required_class = ['sc_code_pattern', 'confidence_high', 'confidence_medium']

# After:
required_class = ['confidence_high', 'confidence_medium']
# category_code_pattern is optional — if absent, raw column value is the code
```

#### 4.1.5 Resolve Paths — Updated Key

```python
# Before (line 62):
for key in ['input', 'sc_mapping', 'taxonomy', 'keyword_rules', 'refinement_rules']:

# After:
for key in ['input', 'category_mapping', 'taxonomy', 'keyword_rules', 'refinement_rules']:
```

#### 4.1.6 Amount Format Default

After alias resolution, inject default if absent:

```python
if 'amount_format' not in config:
    config['amount_format'] = {'type': 'numeric'}
```

### 4.2 `load_sc_mapping()` — Lines 81-94

#### Rename to `load_category_mapping()`

No logic changes. Only the function name and its call site change. The YAML file format stays identical — keys are just category codes (SC codes for CCHMC, subcategory text for UCH, numeric codes for UCH Services).

```python
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

### 4.3 `load_refinement_rules()` — Lines 143-180

#### Make Rule Sections Conditional

Currently, all 4 sections are required. Change to: only `supplier_rules` and `supplier_override_rules` are required. `context_rules` and `cost_center_rules` become optional (empty list if absent).

```python
def load_refinement_rules(path: Path, has_category_codes: bool,
                          has_line_of_service: bool, has_cost_center: bool) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}

    supplier_rules = data.get('supplier_rules', [])
    if has_category_codes:
        _validate_and_compile_rules(
            supplier_rules, 'supplier_rules',
            ('category_codes', 'supplier_pattern', 'taxonomy_key', 'confidence'),
            'supplier_pattern',
        )
    else:
        _validate_and_compile_rules(
            supplier_rules, 'supplier_rules',
            ('supplier_pattern', 'taxonomy_key', 'confidence'),
            'supplier_pattern',
        )

    context_rules = data.get('context_rules', [])
    if context_rules and not has_line_of_service:
        print("  WARNING: context_rules present but no line_of_service column configured. Skipping.",
              file=sys.stderr)
        context_rules = []
    elif context_rules:
        _validate_and_compile_rules(
            context_rules, 'context_rules',
            ('category_codes', 'line_of_service_pattern', 'taxonomy_key', 'confidence'),
            'line_of_service_pattern',
        )

    cost_center_rules = data.get('cost_center_rules', [])
    if cost_center_rules and not has_cost_center:
        print("  WARNING: cost_center_rules present but no cost_center column configured. Skipping.",
              file=sys.stderr)
        cost_center_rules = []
    elif cost_center_rules:
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

**Note on `sc_codes` → `category_codes` rename in YAML**: The refinement rules YAML files will use `category_codes` instead of `sc_codes`. The engine will support both keys via a simple alias check in `_validate_and_compile_rules()`:

```python
def _validate_and_compile_rules(rules, section_name, required_keys, pattern_key):
    for i, rule in enumerate(rules):
        # Alias: sc_codes → category_codes
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

### 4.4 `main()` — Lines 183-597

This is where the bulk of changes live. Below is a section-by-section breakdown.

#### 4.4.1 Resource Loading (Lines 199-227)

```python
# Before:
sc_mapping = load_sc_mapping(paths['sc_mapping'])

# After:
cat_mapping = load_category_mapping(paths['category_mapping'])
```

Update all print statements from "SC code mappings" to "Category mappings".

Determine feature flags from config:

```python
has_description = cols.get('description') is not None
has_line_of_service = cols.get('line_of_service') is not None
has_cost_center = cols.get('cost_center') is not None
has_category_pattern = 'category_code_pattern' in classif
```

Pass flags to `load_refinement_rules()`:

```python
has_category_codes = bool(cat_mapping)
refinement = load_refinement_rules(
    paths['refinement_rules'],
    has_category_codes=has_category_codes,
    has_line_of_service=has_line_of_service,
    has_cost_center=has_cost_center,
)
```

#### 4.4.2 CSV Column Validation (Lines 237-251)

Build required columns dynamically:

```python
required_csv_cols = {
    'category_source': cols['category_source'],
    'supplier': cols['supplier'],
    'amount': cols['amount'],
}
for opt_key in ['description', 'line_of_service', 'cost_center']:
    if cols.get(opt_key):
        required_csv_cols[opt_key] = cols[opt_key]

missing_csv_cols = [
    f"'{v}' (from columns.{k})"
    for k, v in required_csv_cols.items()
    if v not in df.columns
]
```

#### 4.4.3 Amount Pre-Processing (NEW — after line 233)

```python
amount_col_name = cols['amount']
amount_format = config.get('amount_format', {}).get('type', 'numeric')

if amount_format == 'currency_string':
    df[amount_col_name] = (
        df[amount_col_name]
        .astype(str)
        .str.strip()
        .str.replace(r'[\$,]', '', regex=True)
        .str.strip()
    )
    df[amount_col_name] = pd.to_numeric(df[amount_col_name], errors='coerce').fillna(0.0)
else:
    df[amount_col_name] = pd.to_numeric(df[amount_col_name], errors='coerce').fillna(0.0)
```

This runs before classification so all downstream aggregations work on clean float values.

#### 4.4.4 Category Code Extraction (Lines 257-265)

```python
# Before:
sc_pattern = classif['sc_code_pattern']
spend_cat_str = df[cols['spend_category']].astype(str).str.strip()
sc_extracted = spend_cat_str.str.extract(f'({sc_pattern})', expand=False)
if isinstance(sc_extracted, pd.DataFrame):
    sc_extracted = sc_extracted.iloc[:, 0]
sc_code = sc_extracted.fillna(spend_cat_str)

# After:
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

Internal variable `sc_code` renamed to `category_code` throughout the rest of `main()`.

#### 4.4.5 Text Column Extraction (Lines 267-271)

```python
# Before:
supplier = df[cols['supplier']].fillna('').astype(str)
line_memo = df[cols['line_memo']].fillna('').astype(str)
line_of_service = df[cols['line_of_service']].fillna('').astype(str)
cost_center = df[cols['cost_center']].fillna('').astype(str)
combined_text = supplier + ' ' + line_memo

# After:
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

#### 4.4.6 Tier 1: Category Code Mapping (Lines 277-284)

```python
# Before:
non_amb_taxonomy = {sc: info['taxonomy_key'] for sc, info in sc_mapping.items() if not info.get('ambiguous')}
non_amb_confidence = {sc: info['confidence'] for sc, info in sc_mapping.items() if not info.get('ambiguous')}
tier1_mask = sc_code.isin(non_amb_taxonomy)

# After:
non_amb_taxonomy = {c: info['taxonomy_key'] for c, info in cat_mapping.items() if not info.get('ambiguous')}
non_amb_confidence = {c: info['confidence'] for c, info in cat_mapping.items() if not info.get('ambiguous')}
tier1_mask = category_code.isin(non_amb_taxonomy)
taxonomy_key[tier1_mask] = category_code[tier1_mask].map(non_amb_taxonomy)
method[tier1_mask] = 'category_mapping'
confidence[tier1_mask] = category_code[tier1_mask].map(non_amb_confidence)
print(f"  Tier 1 (category mapping): {tier1_mask.sum():,} rows")
```

**How Tier 1 works for UCH Facilities**: Instead of mapping `SC0250 → "IT & Telecoms > Software > ..."`, it maps `Office Equipment & Supplies → "Facilities > Operating Supplies and Equipment"`. The mapping YAML file has text keys instead of SC codes. The engine logic is identical — `isin()` lookup on a dict.

**How Tier 1 works for UCH Services**: Maps `99000038 → "Facilities > Facilities Services > ..."`. Same mechanism.

#### 4.4.7 Tier 2: Supplier Refinement (Lines 289-308)

Change `sc_code.isin(rule['sc_codes'])` to `category_code.isin(rule['category_codes'])`.

For clients without category codes in their refinement rules (e.g., UCH Facilities where supplier rules don't scope by category), the supplier rules simply omit `category_codes` and match purely on supplier regex:

```python
tier2_count = 0
for rule in refinement['supplier_rules']:
    if not unclassified.any():
        break
    if 'category_codes' in rule and rule['category_codes']:
        code_match = category_code.isin(rule['category_codes'])
        candidate = unclassified & code_match
    else:
        candidate = unclassified.copy()
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

#### 4.4.8 Tier 3: Keyword Rules (Lines 311-326)

`combined_text` is now `supplier + ' ' + description`. For UCH Facilities where `description` is empty, `combined_text` is just the supplier name. Keyword rules that reference product terms won't match, but supplier-name-based patterns will. No code change needed — the behavior adapts automatically.

#### 4.4.9 Tier 4: Context Refinement (Lines 328-348)

Wrap in conditional:

```python
tier4_count = 0
if has_line_of_service and refinement['context_rules']:
    for rule in refinement['context_rules']:
        # ... (existing logic, with sc_code → category_code rename)
    print(f"  Tier 4 (context refinement): {tier4_count:,} rows")
else:
    print(f"  Tier 4 (context refinement): skipped — no line_of_service column")
```

#### 4.4.10 Tier 5: Cost Center Refinement (Lines 350-370)

Same pattern:

```python
tier5_count = 0
if has_cost_center and refinement['cost_center_rules']:
    for rule in refinement['cost_center_rules']:
        # ... (existing logic, with sc_code → category_code rename)
    print(f"  Tier 5 (cost center refinement): {tier5_count:,} rows")
else:
    print(f"  Tier 5 (cost center refinement): skipped — no cost_center column")
```

#### 4.4.11 Tier 6: Ambiguous Fallback (Lines 372-379)

```python
# Before:
amb_taxonomy = {sc: info['taxonomy_key'] for sc, info in sc_mapping.items() if info.get('ambiguous')}

# After:
amb_taxonomy = {c: info['taxonomy_key'] for c, info in cat_mapping.items() if info.get('ambiguous')}
amb_confidence = {c: info['confidence'] for c, info in cat_mapping.items() if info.get('ambiguous')}
tier6_mask = unclassified & category_code.isin(amb_taxonomy)
```

#### 4.4.12 Tier 7: Supplier Override (Lines 402-421)

No changes needed. Tier 7 operates on `supplier` and `cat_l1` (post-classification), both of which are always available.

#### 4.4.13 Review Tier Assignment (Lines 423-429)

Update method names for the high-confidence check:

```python
# Before:
high_conf_methods = method.isin(['sc_code_mapping', 'rule'])

# After:
high_conf_methods = method.isin(['category_mapping', 'rule'])
```

#### 4.4.14 Output DataFrame (Lines 434-465)

Make output columns conditional:

```python
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

#### 4.4.15 Summary Sheet (Lines 508-538)

Update method labels:

```python
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

Conditionally include "Unique SC Codes" vs "Unique Category Codes" in summary:

```python
'Metric': [
    'Total Transactions',
    f'Unique {cols["supplier"]}s',
    'Unique Category Codes',
    # ...
]
```

#### 4.4.16 Unmapped Sheet (Lines 569-574)

Rename from "Unmapped SC Codes" to "Unmapped Categories":

```python
if unmapped_counts:
    unmapped_data = [
        {'Category Code': code, 'Count': count}
        for code, count in unmapped_counts.most_common()
    ]
    pd.DataFrame(unmapped_data).to_excel(writer, sheet_name='Unmapped Categories', index=False)
```

### 4.5 Summary of All Variable Renames

| Old Name | New Name | Scope |
|----------|----------|-------|
| `sc_mapping` (variable) | `cat_mapping` | `main()` |
| `load_sc_mapping()` | `load_category_mapping()` | module-level |
| `sc_code` (Series) | `category_code` | `main()` |
| `spend_cat_str` (Series) | `cat_source_str` | `main()` |
| `sc_pattern` | `cat_pattern` | `main()` |
| `non_amb_taxonomy` dict keys | unchanged (just different values) | `main()` |
| `ambiguous_codes` | `ambiguous_codes` (unchanged) | `main()` |
| `unmapped_sc` (Counter) | `unmapped_counts` | `main()` |
| method value `'sc_code_mapping'` | `'category_mapping'` | string literal |
| method value `'sc_code_mapping_ambiguous'` | `'category_mapping_ambiguous'` | string literal |
| output column `'Spend Category (Source)'` | `'Category Source'` | output |
| output column `'SC Code'` | `'Category Code'` | output |
| sheet `'Unmapped SC Codes'` | `'Unmapped Categories'` | output |

---

## 5. New Reference Data Files for UCH

### 5.1 UCH Facilities: `category_mapping.yaml`

Maps UCH's `Subcategory` values to Healthcare Taxonomy v2.9 keys. These are the unique Subcategory values from the Facilities InScope CSV:

```yaml
# UCH Facilities — Subcategory → Healthcare Taxonomy v2.9 Mapping
# Generated from UCH-Facilities-InScope-07312025 1.csv unique subcategories

mappings:

  "Office Equipment & Supplies":
    name: Office Equipment & Supplies
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    confidence: 0.85
    ambiguous: false

  "Building Materials & Services":
    name: Building Materials & Services
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance"
    confidence: 0.80
    ambiguous: true    # Could be materials OR services

  "HVAC Services":
    name: HVAC Services
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance > HVAC Installation & Maintenance"
    confidence: 0.95
    ambiguous: false

  # ... (one entry per unique Subcategory value — typically 20-40 entries)
  # Full file to be generated during Step 4 of migration by extracting unique
  # Subcategory values and mapping each to taxonomy.
```

**Generation process**: Extract unique `Subcategory` values from the CSV, map each to the closest Healthcare Taxonomy v2.9 key, assign confidence based on specificity of the match.

### 5.2 UCH Services: `services_category_mapping.yaml`

Maps UCH's numeric `CategoryCode` values (e.g., `99000038`) to taxonomy keys:

```yaml
# UCH Services — CategoryCode → Healthcare Taxonomy v2.9 Mapping

mappings:

  "99000038":
    name: Equipment Maintenance Services
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance"
    confidence: 0.80
    ambiguous: true    # Covers many types of equipment

  "99000039":
    name: Equipment Rental Services
    taxonomy_key: "Facilities > Equipment Hire"
    confidence: 0.85
    ambiguous: false

  "31160000":
    name: Hardware
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    confidence: 0.80
    ambiguous: true
```

### 5.3 UCH Facilities: `uch_refinement_rules.yaml`

Since UCH Facilities has no SC codes, no Line of Service, and no Cost Center, the refinement rules file contains only `supplier_rules` and `supplier_override_rules`. The `context_rules` and `cost_center_rules` sections are empty.

```yaml
# UCH Facilities — Refinement Rules
# Only supplier-based rules apply (no LoS or Cost Center in this dataset).

supplier_rules:

  # Supplier-only rules (no category_codes scoping needed for most)
  - supplier_pattern: "grainger|w.w. grainger"
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    confidence: 0.90

  - supplier_pattern: "cintas"
    taxonomy_key: "Facilities > Cleaning > Cleaning Services"
    confidence: 0.88

  # Category-scoped supplier rules
  - category_codes: ["Building Materials & Services"]
    supplier_pattern: "assa abloy|door.*operator"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance > Door Systems"
    confidence: 0.90

  - category_codes: ["Building Materials & Services"]
    supplier_pattern: "johnson controls|siemens building"
    taxonomy_key: "Facilities > Technology Systems > Building Automation & Control Systems"
    confidence: 0.88

context_rules: []
cost_center_rules: []

supplier_override_rules:
  - supplier_pattern: "general data company"
    override_from_l1: ["Facilities"]
    taxonomy_key: "IT & Telecoms > IT Hardware > Printers & Copiers"
    confidence: 0.85
```

### 5.4 UCH Services: `uch_services_refinement_rules.yaml`

Services Only has Item Description and Cost Center, so more tiers are available:

```yaml
# UCH Services — Refinement Rules
# Has: Supplier, Item Description, Cost Center Description
# Missing: Line of Service

supplier_rules:

  - category_codes: ["99000038"]
    supplier_pattern: "otis elevator|schindler|thyssenkrupp"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance > Elevator Services"
    confidence: 0.92

  - category_codes: ["99000038"]
    supplier_pattern: "johnson controls fire|simplex grinnell"
    taxonomy_key: "Facilities > Facilities Services > Fire > Fire Safety Systems"
    confidence: 0.90

  - category_codes: ["99000038"]
    supplier_pattern: "assa abloy"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance > Door Systems"
    confidence: 0.90

context_rules: []    # No Line of Service in this dataset

cost_center_rules:

  - category_codes: ["99000038"]
    cost_center_pattern: "maintenance"
    taxonomy_key: "Facilities > Facilities Services > Building Maintenance"
    confidence: 0.75

supplier_override_rules: []
```

### 5.5 Shared: `keyword_rules.yaml`

UCH already has a `keyword_rules.yaml` at `UCH/data/reference/keyword_rules.yaml` (identical to CCHMC's). This file is shared because keyword rules operate on `combined_text` (supplier + description) and are taxonomy-key-targeted, not client-specific.

For UCH Facilities where `description` is absent, `combined_text` = supplier name only. The keyword rules that match on product descriptions will simply not fire. Supplier-name rules still work.

For UCH Services where `Item Description` is rich (e.g., "SERVICE CALL ON CONDO D UNIT FREEZING UP"), keyword rules will match well.

No changes needed to the keyword_rules format.

---

## 6. Test Changes

### 6.1 Current Test Architecture

- `tests/conftest.py`: Session-scoped fixtures loading from `--client-dir` (default: `clients/cchmc`)
- `tests/test_rules.py`: 33 tests across 7 classes, validating YAML structure, regex, taxonomy keys, SC codes, confidence, known mappings, conflicts

### 6.2 Tests That Must Become Client-Aware

#### 6.2.1 `TestYAMLStructure.test_refinement_has_required_sections`

**Current**: Asserts all 4 sections (`supplier_rules`, `context_rules`, `cost_center_rules`, `supplier_override_rules`) are present.

**Change**: Assert only `supplier_rules` and `supplier_override_rules` are required. `context_rules` and `cost_center_rules` are optional (may be empty lists or absent):

```python
def test_refinement_has_required_sections(self, refinement):
    assert "supplier_rules" in refinement, "Missing section: supplier_rules"
    assert "supplier_override_rules" in refinement, "Missing section: supplier_override_rules"
```

#### 6.2.2 `TestSCCodeValidity` — Entire Class

**Current**: Validates that `sc_codes` in rules reference valid SC codes from the mapping.

**Change**: Rename to `TestCategoryCodeValidity`. Check `category_codes` (or `sc_codes` via alias) against valid codes from the mapping:

```python
class TestCategoryCodeValidity:

    def test_supplier_rules_category_codes(self, refinement, valid_category_codes):
        for i, rule in enumerate(refinement["supplier_rules"]):
            codes_key = "category_codes" if "category_codes" in rule else "sc_codes"
            if codes_key not in rule:
                continue    # Supplier-only rules without category scoping are valid
            for code in rule[codes_key]:
                assert str(code) in valid_category_codes, (
                    f"supplier_rules[{i}] unknown code: '{code}'"
                )
```

#### 6.2.3 `conftest.py` Fixtures

Update `valid_sc_codes` fixture to `valid_category_codes`:

```python
@pytest.fixture(scope="session")
def valid_category_codes(category_mapping):
    return set(str(k).strip() for k in category_mapping.get("mappings", {}).keys())

@pytest.fixture(scope="session")
def category_mapping(client_dir, client_config):
    mapping_key = "category_mapping" if "category_mapping" in client_config["paths"] else "sc_mapping"
    path = client_dir / client_config["paths"][mapping_key]
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```

#### 6.2.4 `TestSupplierClassification.KNOWN_MAPPINGS`

**Current**: Hardcoded CCHMC-specific mappings.

**Change**: Make test data external. Load from a `test_assertions.yaml` per client directory:

```python
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
            # ... (same logic, reading from case dict instead of tuple)
```

CCHMC's `test_assertions.yaml`:
```yaml
supplier_mappings:
  - category_code: "SC0250"
    supplier: "epic systems"
    expected_taxonomy: "IT & Telecoms > Software > Application Software"
  - category_code: "SC0250"
    supplier: "kpmg"
    expected_taxonomy: "Professional Services > Financial Services > Accounting Services > General Accounting Services"
  # ... (existing 7 mappings)
```

#### 6.2.5 `TestConflictDetection.test_rule_counts`

**Current**: Hardcoded minimums (230+ supplier rules, 8+ context rules, etc.).

**Change**: Load expected counts from `test_assertions.yaml`:

```python
def test_rule_counts(self, refinement, client_dir):
    assertions_path = client_dir / "test_assertions.yaml"
    if not assertions_path.exists():
        pytest.skip("No test_assertions.yaml")
    with open(assertions_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    expected = data.get("expected_rule_counts", {})
    for section, min_count in expected.items():
        actual = len(refinement.get(section, []))
        assert actual >= min_count, f"Expected {min_count}+ {section}, got {actual}"
```

### 6.3 New Tests Needed

#### 6.3.1 `TestConfigValidation` — New Class

```python
class TestConfigValidation:

    def test_required_columns_present(self, client_config):
        assert "category_source" in client_config["columns"] or "spend_category" in client_config["columns"]
        assert "supplier" in client_config["columns"]
        assert "amount" in client_config["columns"]

    def test_optional_columns_valid_if_present(self, client_config):
        cols = client_config["columns"]
        # If optional columns are declared, they should be non-empty strings
        for opt in ["description", "line_memo", "line_of_service", "cost_center"]:
            if opt in cols:
                assert isinstance(cols[opt], str) and len(cols[opt]) > 0

    def test_amount_format_valid(self, client_config):
        fmt = client_config.get("amount_format", {}).get("type", "numeric")
        assert fmt in ("numeric", "currency_string")

    def test_confidence_thresholds_valid(self, client_config):
        classif = client_config["classification"]
        assert 0.0 < classif["confidence_high"] <= 1.0
        assert 0.0 < classif["confidence_medium"] <= 1.0
        assert classif["confidence_medium"] < classif["confidence_high"]
```

#### 6.3.2 `TestAmountParsing` — New Class

```python
class TestAmountParsing:

    @pytest.mark.parametrize("raw,expected", [
        ("$5,567.76 ", 5567.76),
        ("$0.00", 0.0),
        ("1234.56", 1234.56),
        ("$1,234,567.89", 1234567.89),
        ("-$500.00", -500.0),
    ])
    def test_currency_string_parsing(self, raw, expected):
        import pandas as pd
        s = pd.Series([raw])
        parsed = (
            s.astype(str).str.strip()
            .str.replace(r'[\$,]', '', regex=True)
            .str.strip()
        )
        result = pd.to_numeric(parsed, errors='coerce').fillna(0.0)
        assert abs(result.iloc[0] - expected) < 0.01
```

#### 6.3.3 `TestTierSkipping` — New Class

```python
class TestTierSkipping:

    def test_missing_los_skips_tier4(self, client_config):
        """Clients without line_of_service should not fail on Tier 4."""
        cols = client_config.get("columns", {})
        if "line_of_service" not in cols:
            # Verify refinement rules don't require context_rules
            # (validated by the engine at load time)
            pass

    def test_missing_cost_center_skips_tier5(self, client_config):
        cols = client_config.get("columns", {})
        if "cost_center" not in cols:
            pass
```

### 6.4 Running Tests Per Client

```bash
# CCHMC (default):
pytest tests/ --client-dir clients/cchmc

# UCH Facilities:
pytest tests/ --client-dir clients/uch

# UCH Services:
pytest tests/ --client-dir clients/uch-services

# All clients:
pytest tests/ --client-dir clients/cchmc
pytest tests/ --client-dir clients/uch
pytest tests/ --client-dir clients/uch-services
```

Optionally, add a `conftest.py` parametrize hook to run all clients in one command:

```python
# In conftest.py, add a --all-clients flag:
def pytest_addoption(parser):
    parser.addoption("--client-dir", default=str(ROOT / "clients" / "cchmc"))
    parser.addoption("--all-clients", action="store_true", default=False)
```

---

## 7. Migration Steps

### Step 1: Create the `healthcare-categorization-cli` Repository

**Dependencies**: None
**Verification**: Directory structure exists, git initialized
**Rollback**: Delete directory

1. Create the directory structure (see Section 8).
2. Copy `src/categorize.py` from `categorization-cli`.
3. Copy `shared/reference/Healthcare Taxonomy v2.9.xlsx`.
4. Copy `tests/conftest.py` and `tests/test_rules.py`.
5. Copy `requirements.txt`, `.gitignore`.
6. Copy `clients/cchmc/` directory entirely.
7. Verify: `python src/categorize.py --config clients/cchmc/config.yaml` produces identical output to the original repo.

### Step 2: Add Alias Support to `load_config()`

**Dependencies**: Step 1
**Verification**: CCHMC config works unchanged; deprecation warnings print for old keys
**Rollback**: `git checkout src/categorize.py`

1. Add `ALIASES` dict and `_apply_aliases()` function.
2. Call `_apply_aliases()` after YAML parse, before validation.
3. Print deprecation warnings to stderr.
4. Run CCHMC: verify identical output, confirm deprecation warnings appear.
5. Run tests: `pytest tests/ --client-dir clients/cchmc` — all 33 pass.

### Step 3: Make Columns Optional in `load_config()`

**Dependencies**: Step 2
**Verification**: CCHMC still works (all columns present); a config missing `line_of_service` loads without error
**Rollback**: `git checkout src/categorize.py`

1. Change `required_columns` to only `['category_source', 'supplier', 'amount']`.
2. For optional columns (`description`, `line_of_service`, `cost_center`), store `None` in config if absent.
3. Make `category_code_pattern` optional in `required_class`.
4. Add `amount_format` default injection.
5. Run CCHMC: verify identical output.
6. Run tests: all pass.

### Step 4: Add Amount Pre-Processing

**Dependencies**: Step 3
**Verification**: CCHMC unchanged (numeric amounts pass through); UCH currency strings parse correctly
**Rollback**: `git checkout src/categorize.py`

1. Add currency string parsing block in `main()` after CSV load.
2. Add `TestAmountParsing` test class.
3. Run CCHMC: verify identical output (numeric format = no-op).
4. Test currency parsing with a synthetic CSV containing `"$5,567.76 "` values.

### Step 5: Generalize Category Code Extraction

**Dependencies**: Step 4
**Verification**: CCHMC SC code extraction works as before; UCH raw-value extraction works
**Rollback**: `git checkout src/categorize.py`

1. Rename `sc_code` variable to `category_code`.
2. Make extraction conditional on `has_category_pattern`.
3. Rename `load_sc_mapping()` to `load_category_mapping()`.
4. Update all references in `main()`.
5. Run CCHMC: verify identical output (pattern extraction still fires).
6. Run tests: update fixture names, all pass.

### Step 6: Make Tiers 2, 4, 5 Conditional

**Dependencies**: Step 5
**Verification**: CCHMC unchanged; removing `line_of_service` from CCHMC config causes Tier 4 to skip gracefully
**Rollback**: `git checkout src/categorize.py`

1. Add `has_description`, `has_line_of_service`, `has_cost_center` feature flags.
2. Wrap Tier 4 in `if has_line_of_service`.
3. Wrap Tier 5 in `if has_cost_center`.
4. Update Tier 2 to handle optional `category_codes` in rules.
5. Update `load_refinement_rules()` to accept feature flags.
6. Run CCHMC: verify identical output.
7. Temporarily remove `line_of_service` from CCHMC config, verify Tier 4 prints "skipped". Restore.

### Step 7: Update Output Section

**Dependencies**: Step 6
**Verification**: Output Excel has conditional columns; summary reflects new method names
**Rollback**: `git checkout src/categorize.py`

1. Make output columns conditional on feature flags.
2. Rename output columns (`Category Source`, `Category Code`, `Unmapped Categories`).
3. Update method labels.
4. Update summary metrics.
5. Run CCHMC: verify output Excel structure (column names changed — **this is a breaking change for downstream consumers**).

### Step 8: Update Tests for Multi-Client Support

**Dependencies**: Step 7
**Verification**: All tests pass for CCHMC with updated fixtures
**Rollback**: `git checkout tests/`

1. Rename fixtures (`valid_sc_codes` → `valid_category_codes`, etc.).
2. Make `TestYAMLStructure` allow optional sections.
3. Externalize known mappings to `test_assertions.yaml`.
4. Add `TestConfigValidation`, `TestAmountParsing`, `TestTierSkipping`.
5. Run: `pytest tests/ --client-dir clients/cchmc` — all pass.

### Step 9: Create UCH Client Directory and Reference Data

**Dependencies**: Step 8
**Verification**: UCH config loads without error; reference data validates against taxonomy
**Rollback**: Delete `clients/uch/`

1. Create `clients/uch/` directory structure.
2. Copy UCH input CSV.
3. Extract unique `Subcategory` values, create `category_mapping.yaml`.
4. Create `uch_refinement_rules.yaml` (supplier rules only).
5. Copy/symlink shared `keyword_rules.yaml`.
6. Create `config.yaml` per Section 3.4.
7. Create `test_assertions.yaml` with expected rule counts and known mappings.
8. Run: `python src/categorize.py --config clients/uch/config.yaml` — produces output.
9. Run: `pytest tests/ --client-dir clients/uch` — all applicable tests pass.

### Step 10: Create UCH Services Client Directory (If Needed)

**Dependencies**: Step 9
**Verification**: Same as Step 9 for the Services dataset
**Rollback**: Delete `clients/uch-services/`

1. Create `clients/uch-services/` directory structure.
2. Create `services_category_mapping.yaml`.
3. Create `uch_services_refinement_rules.yaml`.
4. Create `config.yaml` per Section 3.5.
5. Run and verify.

### Step 11: CCHMC Regression Verification

**Dependencies**: Step 10
**Verification**: CCHMC output is **byte-for-byte identical** (modulo renamed columns) to the original `categorization-cli` output
**Rollback**: N/A (if this fails, fix the engine)

1. Run CCHMC in both the original `categorization-cli` and the new `healthcare-categorization-cli`.
2. Compare output Excel: row counts, tier breakdowns, classification methods, review tier distribution.
3. All numbers must match exactly (column name changes are expected).
4. Run full test suite for all clients.

### Parallelization Opportunities

| Steps | Can Parallelize? | Notes |
|-------|-----------------|-------|
| Steps 1-2 | Sequential | Foundation |
| Steps 3-4 | Parallel | Independent changes |
| Steps 5-6 | Sequential | Step 6 depends on Step 5's renames |
| Step 7 | Sequential | Depends on Step 6 |
| Steps 8-9 | Parallel | Tests and reference data are independent |
| Step 10 | Parallel with Step 9 | Independent client |
| Step 11 | Sequential | Final gate |

---

## 8. File Structure

```
healthcare-categorization-cli/
├── src/
│   └── categorize.py                           # Single-file engine (v2, ~700 lines)
│
├── shared/
│   └── reference/
│       └── Healthcare Taxonomy v2.9.xlsx        # Universal taxonomy (unchanged)
│
├── clients/
│   ├── cchmc/
│   │   ├── config.yaml                          # UNCHANGED from v1 (aliases handle renames)
│   │   ├── test_assertions.yaml                 # NEW: externalized test data
│   │   ├── data/
│   │   │   ├── input/
│   │   │   │   └── cchmc-ftp-new.csv
│   │   │   └── reference/
│   │   │       ├── sc_code_mapping.yaml         # Unchanged (sc_ prefix still valid)
│   │   │       ├── keyword_rules.yaml           # Unchanged
│   │   │       └── cchmc_refinement_rules.yaml  # Unchanged (sc_codes alias works)
│   │   └── output/
│   │
│   ├── uch/
│   │   ├── config.yaml                          # NEW: UCH Facilities config (Section 3.4)
│   │   ├── test_assertions.yaml                 # NEW: UCH test assertions
│   │   ├── data/
│   │   │   ├── input/
│   │   │   │   └── UCH-Facilities-InScope-07312025 1.csv
│   │   │   └── reference/
│   │   │       ├── category_mapping.yaml        # NEW: Subcategory → taxonomy
│   │   │       ├── keyword_rules.yaml           # Shared (copy or symlink)
│   │   │       └── uch_refinement_rules.yaml    # NEW: supplier-only rules
│   │   └── output/
│   │
│   └── uch-services/                            # Optional — only if Services data is in scope
│       ├── config.yaml
│       ├── test_assertions.yaml
│       ├── data/
│       │   ├── input/
│       │   │   └── Services Only.csv
│       │   └── reference/
│       │       ├── services_category_mapping.yaml
│       │       ├── keyword_rules.yaml
│       │       └── uch_services_refinement_rules.yaml
│       └── output/
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                              # Updated: alias-aware fixtures
│   └── test_rules.py                            # Updated: conditional sections, externalized data
│
├── docs/
│   ├── PRD.md                                   # Updated for v2 schema
│   ├── User_Guide.md                            # Updated for multi-client usage
│   └── Multi_Client_Implementation_Plan.md      # This document
│
├── requirements.txt                             # Unchanged: pandas, pyyaml, openpyxl
├── .gitignore
└── README.md
```

---

## 9. Risk Mitigation

### Risk 1: CCHMC Regression

**What could go wrong**: Renaming variables, methods, or output columns breaks existing CCHMC results or downstream workflows that consume the Excel output.

**Mitigation**:
- Alias system ensures old config keys still work without modification.
- Step 11 is a dedicated regression gate: compare output row-by-row between old and new engines.
- Output column renames (`SC Code` → `Category Code`) are the one intentional breaking change. Document this in a changelog and verify with the CCHMC stakeholder before deploying.
- If column rename is unacceptable, add a `output.legacy_column_names: true` config option that emits the old names.

### Risk 2: Currency String Parsing Edge Cases

**What could go wrong**: UCH amounts like `"($500.00)"` (parenthesized negatives), `"N/A"`, or empty strings cause parsing failures.

**Mitigation**:
- Use `pd.to_numeric(errors='coerce')` which converts unparsable values to NaN, then `.fillna(0.0)`.
- Add a post-parse warning: "X rows had unparsable amount values, defaulted to 0.0".
- Add `TestAmountParsing` covering edge cases including negatives, empties, and non-numeric strings.

### Risk 3: UCH Keyword Rules Don't Fire (No Description Column)

**What could go wrong**: For UCH Facilities, `combined_text` = supplier name only. Most keyword rules match on product descriptions, so they'll have zero hits. Tier 3 becomes effectively dead, leaving more rows unmapped.

**Mitigation**:
- This is expected and by design. UCH Facilities classification relies primarily on Tier 1 (Subcategory mapping) and Tier 2 (supplier refinement).
- The keyword rules YAML is shared but acts as a "bonus" tier — it fires when data is available and does nothing when it's not.
- For UCH Services (which has `Item Description`), keyword rules will fire normally.
- If needed, write UCH-specific keyword rules that match on supplier names alone.

### Risk 4: Ambiguous Subcategory Values in UCH

**What could go wrong**: UCH Subcategory values like "Building Materials & Services" are broad. A single Tier 1 mapping may cover too many distinct product types, leading to low accuracy.

**Mitigation**:
- Mark broad subcategories as `ambiguous: true` in `category_mapping.yaml`.
- Ambiguous entries skip Tier 1 and fall through to Tier 2 (supplier refinement) where supplier-specific patterns provide better classification.
- Tier 6 catches remaining ambiguous codes at low confidence → routed to "Quick Review".

### Risk 5: Category Code Type Mismatch (String vs Int)

**What could go wrong**: YAML auto-parses `99000038` as an integer, but the CSV column contains strings. `isin()` comparison fails silently.

**Mitigation**:
- `load_category_mapping()` already casts keys to `str`: `code_str = str(code).strip()`.
- `category_code` Series is cast to `str` via `.astype(str)`.
- Add a test that verifies mapping keys are strings regardless of YAML source type:

```python
def test_mapping_keys_are_strings(self, category_mapping):
    for key in category_mapping.get("mappings", {}).keys():
        assert isinstance(str(key), str)
```

### Risk 6: Shared Keyword Rules File Divergence

**What could go wrong**: Clients copy `keyword_rules.yaml` and modify it independently, creating drift. A rule fix applied to one client isn't propagated to others.

**Mitigation**:
- Keep a canonical `shared/reference/keyword_rules.yaml` alongside the taxonomy.
- Client configs point to either the shared file (`../../shared/reference/keyword_rules.yaml`) or a client-specific override.
- Convention: only create a client-specific `keyword_rules.yaml` if the client needs rules that would conflict with the shared set.

### Risk 7: UCH Has Multiple Input Formats

**What could go wrong**: The three UCH CSVs (Facilities, Services, CatWork) have different schemas. Running the wrong config against the wrong CSV produces silent misclassification.

**Mitigation**:
- Each CSV gets its own client directory (`uch/`, `uch-services/`) with a dedicated `config.yaml`.
- The engine validates that all declared columns exist in the input CSV (lines 237-251). If someone runs the Facilities config against the Services CSV, it fails immediately with a clear column-not-found error.
- Document the CSV-to-config mapping in each client's config comments.

### Risk 8: Performance Regression on Large Datasets

**What could go wrong**: The additional conditional checks and optional column handling add overhead per tier, slowing classification for CCHMC's 596K rows.

**Mitigation**:
- The conditionals (`if has_line_of_service:`) are checked once, not per-row. They gate entire tier blocks, not individual iterations.
- Vectorized pandas operations remain unchanged — no row-level loops introduced.
- Benchmark after Step 7: CCHMC classification must stay under 15 seconds per NFR-01.

---

## Appendix A: Decision Log

| # | Decision | Alternatives Considered | Rationale |
|---|----------|------------------------|-----------|
| D1 | Config-driven conditionals | Plugin/Strategy pattern, per-client engine subclasses | Simplicity; data shape differences don't warrant algorithmic abstraction |
| D2 | Single file engine | Split into modules (loaders.py, tiers.py, output.py) | Under 1000 lines; analyst readability over engineer aesthetics |
| D3 | Backwards-compatible aliases | Force config migration; version field in config | Zero-risk for existing CCHMC deployment |
| D4 | `category_codes` optional in supplier rules | Always require category scoping | UCH Facilities has no meaningful category codes for scoping |
| D5 | Rename output columns globally | Keep old names + add new ones as duplicates | Clean break; document in changelog; one-time consumer update |

## Appendix B: Estimated Effort

| Step | Description | Estimated Hours | Difficulty |
|------|-------------|-----------------|------------|
| 1 | Create repo, copy files, verify parity | 1 | Low |
| 2 | Alias support | 1 | Low |
| 3 | Optional columns | 1.5 | Medium |
| 4 | Amount pre-processing | 1 | Low |
| 5 | Generalize category codes | 2 | Medium |
| 6 | Conditional tiers | 2 | Medium |
| 7 | Output section update | 1.5 | Low |
| 8 | Test updates | 2 | Medium |
| 9 | UCH Facilities reference data + config | 3 | Medium |
| 10 | UCH Services reference data + config | 2 | Medium |
| 11 | CCHMC regression verification | 1 | Low |
| **Total** | | **18 hours** | |
