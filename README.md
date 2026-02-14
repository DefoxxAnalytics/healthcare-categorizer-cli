# Healthcare Categorization CLI

Config-driven healthcare procurement categorization engine using 7-tier waterfall classification against Healthcare Taxonomy v2.9.

## Overview

This CLI tool processes healthcare procurement transactions and categorizes them using a multi-tier waterfall approach. It supports multiple healthcare organizations with distinct ERP systems (Workday, Oracle Fusion), procurement code standards (SC codes, UNSPSC), and input formats (CSV, XLSX). The engine applies a 7-tier classification waterfall to maximize categorization accuracy while maintaining auditability and confidence scoring.

Currently supporting two active clients: CCHMC (596K rows, Workday AP) and UCH (4.6K rows, Oracle Fusion).

## Quick Start

```bash
# Clone repository
git clone <repository-url>
cd healthcare-categorization-cli

# Install dependencies
pip install -r requirements.txt

# Run categorization for CCHMC
python src/categorize.py --config clients/cchmc/config.yaml

# Run categorization for UCH
python src/categorize.py --config clients/uch/config.yaml
```

## Architecture - 7-Tier Waterfall

The engine applies classification rules in strict waterfall order. Once a tier matches, classification stops and confidence is assigned.

| Tier | Method | Description |
|------|--------|-------------|
| **Tier 1** | Category Code Mapping | Non-ambiguous procurement codes (SC/UNSPSC) mapped directly to taxonomy keys. Highest confidence (0.85). |
| **Tier 2** | Supplier Refinement | Code + supplier regex patterns resolve ambiguous codes or add precision. Confidence: 0.80. |
| **Tier 3** | Keyword Rules | Supplier + description regex patterns for transactions lacking valid codes. Confidence: 0.75. |
| **Tier 4** | Context Refinement | Code + line of service regex patterns (e.g., "Pharmacy" → Rx-specific category). Optional. Confidence: 0.80. |
| **Tier 5** | Cost Center Refinement | Code + cost center regex patterns (e.g., "Radiology" → imaging equipment). Optional. Confidence: 0.80. |
| **Tier 6** | Ambiguous Fallback | Ambiguous procurement codes map to taxonomy with reduced confidence (0.50). |
| **Tier 7** | Supplier Override | Post-classification override based on supplier + L1 category patterns (e.g., "Medline" in "Services" → "Medical Supplies"). Applied after Tiers 1-6. |

**Unmapped transactions** fall through all tiers and are flagged for manual review.

## Multi-Client Support

The engine is fully config-driven. Each client has an isolated directory under `clients/`:

```
clients/
├── cchmc/                      # Cincinnati Children's Hospital Medical Center
│   ├── config.yaml             # Client-specific configuration
│   ├── data/
│   │   ├── input/              # Transaction files (CSV/XLSX)
│   │   └── reference/          # Category mappings, keyword rules, refinement rules
│   └── test_assertions.yaml    # Unit test expectations
│
└── uch/                        # University of Cincinnati Health
    ├── config.yaml
    ├── data/
    │   ├── input/
    │   └── reference/
    └── test_assertions.yaml
```

**Backward-compatible aliases** ensure legacy config keys (e.g., `spend_category`, `sc_code_pattern`) map to canonical names (`category_source`, `category_code_pattern`) without breaking existing deployments.

## Directory Structure

```
healthcare-categorization-cli/
├── src/
│   └── categorize.py           # Main classification engine (~700 lines)
├── tests/
│   ├── conftest.py             # Pytest fixtures and client-aware test setup
│   ├── test_rules.py           # Rule-based unit tests (client-specific)
│   └── __init__.py
├── clients/
│   ├── cchmc/                  # CCHMC client config and data
│   └── uch/                    # UCH client config and data
├── shared/
│   └── reference/
│       └── Healthcare Taxonomy v2.9.xlsx  # Shared L1-L5 taxonomy
├── docs/
│   ├── Multi_Client_PRD.md     # Product requirements document
│   ├── Multi_Client_Implementation_Plan.md
│   └── Multi_Client_Critical_Review.md
├── requirements.txt
└── README.md
```

## Configuration Reference

Each client's `config.yaml` defines:

| Section | Purpose | Example Keys |
|---------|---------|--------------|
| `client` | Client metadata | `name`, `description` |
| `paths` | File paths (input, reference files, output) | `input`, `category_mapping`, `taxonomy`, `keyword_rules`, `refinement_rules`, `output_dir`, `output_prefix` |
| `columns` | Input column mappings | `category_source`, `supplier`, `description`, `line_of_service`, `cost_center`, `amount`, `passthrough` (list) |
| `classification` | Classification parameters | `category_code_pattern` (regex), `confidence_high` (threshold) |
| `aggregations` | Custom spend aggregations | `name`, `column`, `top_n` |
| `input_format` | Input file settings | `sheet_name` (for XLSX files) |

**Optional columns**: `description`, `line_of_service`, `cost_center`. If omitted from config, corresponding classification tiers are skipped.

**Example config snippet** (CCHMC):

```yaml
client:
  name: "CCHMC"
  description: "Cincinnati Children's Hospital Medical Center — Workday AP/Procurement"

paths:
  input: "data/input/cchmc-ftp-new.csv"
  category_mapping: "data/reference/sc_code_mapping.yaml"
  taxonomy: "../../shared/reference/Healthcare Taxonomy v2.9.xlsx"
  keyword_rules: "data/reference/keyword_rules.yaml"
  refinement_rules: "data/reference/cchmc_refinement_rules.yaml"
  output_dir: "output"
  output_prefix: "cchmc_categorization_results"

columns:
  category_source: "Spend Category"
  supplier: "Supplier"
  description: "Line Memo"
  line_of_service: "Line of Service"
  cost_center: "Cost Center"
  amount: "Invoice Line Amount"
  passthrough:
    - "Invoice Number"
    - "Invoice Date"
    - "PO Type"

classification:
  category_code_pattern: '((?:DNU\s+)?SC\d+)'
  confidence_high: 0.7
```

## Testing

The test suite uses a client-aware pytest setup. Tests are isolated per client using the `--client-dir` flag.

**Run CCHMC tests:**
```bash
pytest --client-dir clients/cchmc
```

**Run UCH tests:**
```bash
pytest --client-dir clients/uch
```

**Test results (current):**
- CCHMC: 29 passed, 1 skipped
- UCH: 23 passed, 7 skipped

Each client defines expected outcomes in [`test_assertions.yaml`](clients/cchmc/test_assertions.yaml). Tests validate:
- Code extraction (Tier 1)
- Supplier refinement rules (Tier 2)
- Keyword matching (Tier 3)
- Context/cost center refinement (Tiers 4-5)
- Ambiguous fallback (Tier 6)
- Supplier override (Tier 7)

## Output

The engine generates a timestamped Excel workbook (`{output_prefix}_{timestamp}.xlsx`) containing:

| Sheet | Contents |
|-------|----------|
| **All Results** | Full dataset with matched taxonomy (CategoryLevel1-5), confidence scores, tier metadata |
| **Manual Review** | Unmapped transactions (no tier matched) |
| **Quick Review** | Low-confidence matches (confidence < `confidence_high` threshold) |
| **Summary** | Classification statistics by tier, confidence distribution, unmapped rate |
| **Spend by Category L1** | Total spend aggregated by top-level taxonomy category |
| **Spend by Category L2** | Total spend aggregated by second-level taxonomy category |
| **Custom Aggregations** | User-defined spend aggregations (e.g., by Line of Service + L1) |
| **Unmapped Categories** | Frequency analysis of unmapped procurement codes and suppliers |

**Passthrough columns** (e.g., Invoice Number, Invoice Date, PO Type) are preserved in output for audit trail.

## CLI Options

```bash
python src/categorize.py --config <path_to_config.yaml> [options]

Options:
  --config PATH            Path to client config.yaml (required)
  --input PATH             Override input file path from config
  --output-dir PATH        Override output directory from config
```

**Example - Override input file:**
```bash
python src/categorize.py \
  --config clients/cchmc/config.yaml \
  --input clients/cchmc/data/input/monthly_extract_jan2025.csv
```

## Performance

The classification engine is fully vectorized with pandas and uses several optimizations for large datasets:

- **Pre-compiled regex**: All rule patterns are compiled once at load time and reused across all tier evaluations
- **Code-to-row index map**: Category codes are grouped into a lookup map, replacing per-rule `isin()` scans on the full dataset
- **Single-pass taxonomy join**: Taxonomy level resolution uses one DataFrame join instead of separate lookups per level
- **Tier 7 L1 pre-filter**: Supplier override regex runs only on rows matching the target L1 category

**Benchmarks (Windows 11, Python 3.13):**

| Client | Rows | Rules | Classification | Total (incl. I/O) |
|--------|------|-------|----------------|---------------------|
| CCHMC | 596,796 | 237 supplier + 220 keyword | 6.0s | ~165s |
| UCH | 4,649 | 3 supplier + 4 keyword | <0.1s | ~2.5s |

Total runtime is dominated by Excel I/O (openpyxl writing). Classification throughput is ~100K rows/sec.

## Dependencies

- **pandas** >= 1.5 — Data manipulation and Excel I/O
- **pyyaml** >= 6.0 — Configuration file parsing
- **openpyxl** >= 3.0 — Excel workbook generation
- **pytest** >= 7.0 — Testing framework

Install via:
```bash
pip install -r requirements.txt
```

## Client Profiles

**CCHMC (Cincinnati Children's Hospital Medical Center)**
- ERP: Workday AP/Procurement
- Procurement Codes: Spend Category (SC codes, e.g., SC123, DNU SC456)
- Input Format: CSV
- Volume: 596,000 rows
- Optional Columns: Description (Line Memo), Line of Service, Cost Center
- Code Pattern: `((?:DNU\s+)?SC\d+)`

**UCH (University of Cincinnati Health)**
- ERP: Oracle Fusion
- Procurement Codes: UNSPSC (e.g., 42142100, 10101500)
- Input Format: XLSX
- Volume: 4,600 rows
- Optional Columns: Description, Cost Center (no Line of Service)
- Code Pattern: `^(\d+)-`

## File References

- **Engine**: [`src/categorize.py`](src/categorize.py)
- **Test Setup**: [`tests/conftest.py`](tests/conftest.py)
- **Rule Tests**: [`tests/test_rules.py`](tests/test_rules.py)
- **Shared Taxonomy**: [`shared/reference/Healthcare Taxonomy v2.9.xlsx`](shared/reference/Healthcare%20Taxonomy%20v2.9.xlsx)
- **CCHMC Config**: [`clients/cchmc/config.yaml`](clients/cchmc/config.yaml)
- **UCH Config**: [`clients/uch/config.yaml`](clients/uch/config.yaml)
- **Documentation**: [`docs/Multi_Client_PRD.md`](docs/Multi_Client_PRD.md)
