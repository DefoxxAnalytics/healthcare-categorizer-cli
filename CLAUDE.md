# Healthcare Categorization CLI

## Project Overview

Config-driven transaction categorization engine for healthcare procurement data. Classifies transactions against Healthcare Taxonomy v2.9 using a 7-tier waterfall logic.

## Tech Stack

- **Python 3.7+**: Core language
- **pandas**: Data manipulation and Excel operations
- **pyyaml**: YAML rule file parsing
- **openpyxl**: Excel workbook output
- **pytest**: Testing framework

## Project Structure

```
healthcare-categorization-cli/
├── src/
│   └── categorize.py                    # Main engine (7-tier waterfall logic)
├── tests/
│   ├── conftest.py                      # Pytest fixtures with alias-aware config loading
│   └── test_rules.py                    # YAML validation, classification assertions, conflict detection
├── clients/
│   ├── cchmc/                           # Cincinnati Children's (Workday, CSV, SC codes)
│   │   ├── config.yaml                  # Column mappings, paths, classification params
│   │   ├── data/
│   │   │   ├── input/                   # Transaction CSV/XLSX files
│   │   │   └── reference/               # YAML rules (category_mapping, refinement_rules, keyword_rules)
│   │   └── test_assertions.yaml         # Optional: known mappings, min rule counts
│   └── uch/                             # University of Colorado (Oracle Fusion, XLSX, UNSPSC codes)
│       └── (same structure as cchmc)
└── shared/
    └── reference/
        └── Healthcare Taxonomy v2.9.xlsx # Universal taxonomy (5 levels)
```

## Key Architecture Concepts

### Config-Driven Design
Everything flows from `clients/{client}/config.yaml`:
- Column mappings (category_source, supplier, amount, optional: description, line_of_service, cost_center)
- File paths (input, output, taxonomy, rules)
- Classification parameters (regex patterns, confidence thresholds)
- Aggregation definitions

### Backward-Compatible Aliases
ALIASES dict in `categorize.py` maps deprecated keys to canonical names:
- `paths.sc_mapping` → `category_mapping`
- `columns.spend_category` → `category_source`
- `columns.line_memo` → `description`
- `classification.sc_code_pattern` → `category_code_pattern`

Applied automatically during config loading with deprecation warnings.

### Optional Columns
Three optional columns with feature flags:
- `description` (has_description)
- `line_of_service` (has_line_of_service)
- `cost_center` (has_cost_center)

If not in config, set to `None` and corresponding classification tiers are skipped.

### Rule Key Normalization
`_validate_and_compile_rules()` migrates `sc_codes` → `category_codes` in all YAML rule files:
- Supplier rules
- Context rules (line_of_service)
- Cost center rules

Tests use `_codes_key()` helper for compatibility with both formats.

## Commands

### Run Engine
```bash
python src/categorize.py --config clients/cchmc/config.yaml
python src/categorize.py --config clients/cchmc/config.yaml --input override.csv
python src/categorize.py --config clients/cchmc/config.yaml --output-dir /tmp
```

### Run Tests
```bash
python -m pytest tests/ --client-dir clients/cchmc -v
python -m pytest tests/test_rules.py::TestYAMLStructure -v
python -m pytest tests/ --client-dir clients/uch -v
```

## 7-Tier Waterfall Logic

Transactions are classified in this order (first match wins):
1. **Category code + supplier refinement**: Exact match on category_codes list + supplier regex
2. **Category code + context refinement**: Exact match + line_of_service regex (if has_line_of_service)
3. **Category code + cost center refinement**: Exact match + cost_center regex (if has_cost_center)
4. **Supplier override**: Supplier regex + override_from_l1 taxonomy filter
5. **Category mapping**: Extract code from category_source via regex, map to taxonomy key
6. **Keyword rules**: Description regex → taxonomy key (if has_description)
7. **Unclassified**: No match (flagged for manual review)

Confidence scores (HIGH/MEDIUM) determine final classification quality.

## Testing Conventions

### Fixture Design
- `conftest.py` applies aliases to config before passing to tests
- Fixtures provide `category_mapping`, `refinement`, `keyword_rules`, `taxonomy_keys`
- `has_context_rules` and `has_cost_center_rules` fixtures control optional test suites

### Rule Key Compatibility
- `_codes_key(rule)` helper checks for `category_codes` or falls back to `sc_codes`
- Tests validate both formats during migration period

### Client-Specific Assertions
- `test_assertions.yaml` (optional) defines known supplier→taxonomy mappings
- Allows regression testing without hardcoding in test files
- Skip if file doesn't exist (returns empty dict)

## Adding a New Client

1. Create directory structure:
   ```bash
   mkdir -p clients/{name}/data/{input,reference}
   ```

2. Write `clients/{name}/config.yaml`:
   - Map column names to canonical keys
   - Set paths to input file, rules, taxonomy
   - Define `category_code_pattern` regex (if applicable)

3. Create YAML rule files in `data/reference/`:
   - `category_mapping.yaml`: code → taxonomy key + ambiguous flag
   - `refinement_rules.yaml`: supplier_rules, context_rules, cost_center_rules, supplier_override_rules
   - `keyword_rules.yaml`: pattern → category (for description matching)

4. (Optional) Create `test_assertions.yaml`:
   - Known classifications for regression testing
   - Minimum rule counts per section

5. Run tests:
   ```bash
   python -m pytest tests/ --client-dir clients/{name} -v
   ```

6. Run engine:
   ```bash
   python src/categorize.py --config clients/{name}/config.yaml
   ```

## Code Style

- Self-documenting names over comments
- Match existing patterns: vectorized pandas operations, regex-compiled rules
- No commented-out code
- No type suppression (`@ts-ignore` equivalent)
