# Healthcare Categorization CLI - User Guide

## Introduction

The Healthcare Categorization CLI is a config-driven transaction categorization engine for healthcare procurement data. It classifies purchasing transactions against the Healthcare Taxonomy v2.9 using a 7-tier waterfall methodology, combining direct category code mappings, supplier refinement rules, keyword patterns, contextual rules, and fallback strategies.

**Who it's for:** Finance analysts, procurement teams, and data engineers working with healthcare purchasing data from ERP systems like Workday, Oracle Fusion, or SAP.

**What it does:**
- Classifies thousands of procurement transactions in seconds
- Maps vendor category codes (Spend Categories, UNSPSC) to standardized Healthcare Taxonomy
- Uses supplier names, descriptions, line of service, and cost centers to refine ambiguous classifications
- Assigns confidence scores and review tiers (Auto-Accept, Quick Review, Manual Review)
- Produces Excel workbooks with detailed results, aggregations, and unmapped item reports

## Prerequisites

**System Requirements:**
- Python 3.7 or higher
- pip package manager

**Installation:**

```bash
# Clone the repository
cd healthcare-categorization-cli

# Install dependencies
pip install -r requirements.txt
```

**Required dependencies:**
- pandas
- openpyxl
- PyYAML

## Running the Engine

### Basic Usage

```bash
python src/categorize.py --config clients/cchmc/config.yaml
```

The engine auto-detects input file format (CSV or XLSX) based on file extension.

### Command-line Options

**Override input file:**
```bash
python src/categorize.py --config clients/cchmc/config.yaml --input /path/to/new_data.csv
```

**Override output directory:**
```bash
python src/categorize.py --config clients/uch/config.yaml --output-dir /tmp/results
```

**All options:**
- `--config` (required): Path to client configuration YAML file
- `--input` (optional): Override input file path specified in config
- `--output-dir` (optional): Override output directory specified in config

### What Happens When You Run

1. **Loads resources**: Category mappings, taxonomy, keyword rules, refinement rules
2. **Validates configuration**: Checks all required sections, paths, and column mappings
3. **Reads input data**: CSV or XLSX file (auto-detected by extension)
4. **Classifies transactions**: 7-tier waterfall (vectorized for performance)
5. **Assigns review tiers**: Auto-Accept, Quick Review, Manual Review based on confidence
6. **Generates Excel output**: Multiple sheets with results, summaries, and aggregations

**Output file naming:**
```
{output_prefix}_{YYYYMMDD_HHMMSS}.xlsx
```

Example: `cchmc_categorization_results_20260214_153042.xlsx`

## Understanding the Output Excel

The engine produces a multi-sheet Excel workbook with the following structure:

### All Results Sheet

Every transaction with complete classification details:

| Column | Description |
|--------|-------------|
| Supplier | Original supplier name from input |
| Passthrough columns | All columns listed in `columns.passthrough` config (Invoice Number, PO Type, etc.) |
| Description | Item description (if configured) |
| Category Source | Original category field from ERP system |
| Category Code | Extracted category code (e.g., "SC0250", "39101612") |
| Cost Center | Cost center (if configured) |
| Line of Service | Line of service (if configured) |
| Amount | Transaction amount |
| CategoryLevel1-5 | Taxonomy hierarchy levels |
| TaxonomyKey | Final taxonomy key (e.g., "Medical > Medical Consumables > Medical Gas") |
| ClassificationMethod | Which tier matched (category_mapping, supplier_refinement, rule, etc.) |
| Confidence | Confidence score (0.0-1.0) |
| ReviewTier | Auto-Accept, Quick Review, or Manual Review |

### Manual Review Sheet

Subset of rows requiring manual review (low confidence or unmapped).

**Typical reasons:**
- Confidence < 0.5 (medium threshold)
- Ambiguous category codes without supplier refinement match
- Unmapped category codes

### Quick Review Sheet

Subset of rows with medium confidence (0.5 ≤ confidence < 0.7).

**Typical reasons:**
- Confidence between medium and high thresholds
- Ambiguous category fallback matches
- Some supplier refinement matches

### Summary Sheet

High-level metrics and counts:

**Metrics included:**
- Total Transactions
- Unique Suppliers
- Unique Category Codes
- Classification method breakdown (counts and percentages)
- Review tier breakdown (Auto-Accept, Quick Review, Manual Review)
- Financial totals (Total Amount, Average Amount)

### Spend by Category L1 / L2 Sheets

Aggregated spend by taxonomy hierarchy levels:

**Spend by Category L1:**
- Top-level categories (e.g., "Medical", "Facilities", "IT & Telecoms")
- Transaction count, total spend, unique suppliers, average confidence

**Spend by Category L2:**
- Second-level breakdown (e.g., "Medical > Medical Consumables")
- Transaction count, total spend, unique suppliers

### Custom Aggregation Sheets

Client-specific aggregations defined in `config.yaml` under `aggregations` section.

**Example (CCHMC):**
- "Spend by Cost Center (Top 100)"
- "Spend by Line of Service"
- "Spend by Fund (Top 30)"

**Example (UCH):**
- "Spend by Cost Center"
- "Spend by Category (Top 30)"

### Unmapped Categories Sheet

Category codes that didn't match any mapping, sorted by frequency.

**Use this to:**
- Identify missing category code mappings
- Prioritize which codes to add to `category_mapping.yaml`
- Detect data quality issues (invalid codes, typos)

**Columns:**
- Category Code: The unmapped code from input data
- Count: Number of transactions with this code

## Review Tiers Explained

The engine assigns each transaction to one of three review tiers based on confidence scores and classification methods:

### Auto-Accept (High Confidence)

**Criteria:**
- Confidence ≥ 0.7 (high threshold), OR
- High-confidence methods (category_mapping, rule) AND confidence ≥ 0.9

**Typical characteristics:**
- Direct category code mapping (non-ambiguous)
- High-confidence keyword rule match
- Supplier override rule match

**Action:** No review needed—these classifications are reliable.

### Quick Review (Medium Confidence)

**Criteria:**
- 0.5 ≤ Confidence < 0.7

**Typical characteristics:**
- Supplier refinement rule match with moderate confidence
- Ambiguous category code with supplier refinement
- Keyword rules with lower confidence settings

**Action:** Spot-check a sample to verify accuracy. Focus on high-spend items.

### Manual Review (Low Confidence)

**Criteria:**
- Confidence < 0.5 (medium threshold)
- Unmapped category codes (confidence = 0.0)

**Typical characteristics:**
- Ambiguous category fallback without supplier match
- Unmapped category codes
- Context or cost center rules with low confidence

**Action:** Review and correct misclassifications. Add new mappings/rules to prevent recurrence.

## Configuration Reference

All client-specific settings are stored in `config.yaml` files. Configuration is required for:
- Client metadata
- File paths
- Input data column mappings
- Classification thresholds
- Custom aggregations

### client Section

```yaml
client:
  name: "CCHMC"
  description: "Cincinnati Children's Hospital Medical Center — Workday AP/Procurement"
```

**Fields:**
- `name` (required): Short client identifier (used in console output)
- `description` (optional): Detailed description

### paths Section

```yaml
paths:
  input: "data/input/cchmc-ftp-new.csv"
  category_mapping: "data/reference/sc_code_mapping.yaml"
  taxonomy: "../../shared/reference/Healthcare Taxonomy v2.9.xlsx"
  keyword_rules: "data/reference/keyword_rules.yaml"
  refinement_rules: "data/reference/cchmc_refinement_rules.yaml"
  output_dir: "output"
  output_prefix: "cchmc_categorization_results"
```

**All paths are relative to the config file location.**

**Required paths:**
- `input`: CSV or XLSX file with transaction data
- `category_mapping`: YAML file mapping category codes to taxonomy keys
- `taxonomy`: Excel file with Healthcare Taxonomy v2.9
- `keyword_rules`: YAML file with text pattern matching rules
- `refinement_rules`: YAML file with supplier/context/cost center rules
- `output_dir`: Directory for output Excel files
- `output_prefix`: Prefix for output file names

### input_format Section (XLSX only)

```yaml
input_format:
  sheet_name: "Org Data Pull"
```

**Fields:**
- `sheet_name` (optional): Name or 0-based index of Excel sheet to read. Default: 0 (first sheet).

### columns Section

```yaml
columns:
  category_source: "Spend Category"
  supplier: "Supplier"
  description: "Line Memo"
  line_of_service: "Line of Service"
  cost_center: "Cost Center"
  amount: "Invoice Line Amount"
  passthrough:
    - "Invoice Number"
    - "Invoice Line"
    - "Invoice Date"
```

**Required columns:**
- `category_source`: Column with category codes or names (e.g., "SC0250", "39101612-Incandescent Lamps")
- `supplier`: Column with supplier/vendor names
- `amount`: Column with transaction amounts

**Optional columns:**
- `description`: Item description text (enables keyword rule matching)
- `line_of_service`: Line of service field (enables context refinement rules)
- `cost_center`: Cost center field (enables cost center refinement rules)

**Passthrough columns:**
- `passthrough`: List of additional columns to include in output (preserves original data)

**Important:** Column names are case-sensitive and must match exactly as they appear in the input file.

### classification Section

```yaml
classification:
  category_code_pattern: '((?:DNU\s+)?SC\d+)'
  confidence_high: 0.7
  confidence_medium: 0.5
```

**Fields:**
- `category_code_pattern` (optional): Regex with capture group to extract category code from `category_source` field
  - Example (CCHMC): `'((?:DNU\s+)?SC\d+)'` extracts "SC0250" from "DNU SC0250 - Professional Services"
  - Example (UCH): `'^(\d+)-'` extracts "39101612" from "39101612-Incandescent Lamps"
  - If omitted, entire `category_source` value is used as category code
- `confidence_high` (required): Threshold for Auto-Accept tier (typically 0.7)
- `confidence_medium` (required): Threshold for Quick Review tier (typically 0.5)

### aggregations Section

```yaml
aggregations:
  - name: "Spend by Cost Center (Top 100)"
    column: "Cost Center"
    top_n: 100
  - name: "Spend by Line of Service"
    column: "Line of Service"
    top_n: null
```

**Fields:**
- `name` (required): Excel sheet name for this aggregation
- `column` (required): Column to group by (must exist in output)
- `top_n` (optional): Limit to top N rows by spend. Use `null` for all rows.

**Default aggregations** (always created):
- Spend by Category L1
- Spend by Category L2

## Reference File Formats

### category_mapping.yaml

Maps category codes from input data to taxonomy keys.

```yaml
mappings:
  "39101612":
    name: "Incandescent Lamps"
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    ambiguous: true
    confidence: 0.60
  "99000038":
    name: "Equipment Maintenance Services"
    taxonomy_key: "Facilities > Equipment & Machinery > Service & Maintenance"
    ambiguous: false
    confidence: 0.85
```

**Structure:**
- Top-level key: `mappings`
- Each category code (as string, quoted if numeric)
  - `name` (optional): Human-readable category name
  - `taxonomy_key` (required): Full taxonomy path (must exist in Healthcare Taxonomy v2.9)
  - `ambiguous` (optional, default: false): If true, this mapping is only used as fallback (Tier 6)
  - `confidence` (optional, default: 0.85): Confidence score for this mapping

**Ambiguous flag:**
- `false` (default): Used in Tier 1 (high priority, non-ambiguous)
- `true`: Used only in Tier 6 (fallback after all refinement rules fail)

**Use ambiguous=true for:**
- Broad category codes that span multiple taxonomy areas
- Codes requiring supplier/context to refine (e.g., "Professional Services", "Operating Supplies")

### refinement_rules.yaml

Refines ambiguous category codes using supplier names, line of service, cost centers, or cross-category overrides.

#### supplier_rules (Tier 2)

```yaml
supplier_rules:
  - category_codes: ["39101612"]
    supplier_pattern: "grainger"
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    confidence: 0.85
  - category_codes: ["SC0250"]
    supplier_pattern: "epic systems"
    taxonomy_key: "IT & Telecoms > Software > Application Software"
    confidence: 0.90
```

**Fields:**
- `category_codes` (required): List of category codes this rule applies to
- `supplier_pattern` (required): Case-insensitive regex to match supplier name
- `taxonomy_key` (required): Taxonomy key to assign if match
- `confidence` (required): Confidence score (0.0-1.0)

#### context_rules (Tier 4)

```yaml
context_rules:
  - category_codes: ["SC0250"]
    line_of_service_pattern: "pharmacy"
    taxonomy_key: "Medical > Pharmaceuticals > Prescription Drugs"
    confidence: 0.75
```

**Fields:**
- `category_codes` (required): List of category codes this rule applies to
- `line_of_service_pattern` (required): Case-insensitive regex to match line of service
- `taxonomy_key` (required): Taxonomy key to assign if match
- `confidence` (required): Confidence score (0.0-1.0)

**Requires:** `columns.line_of_service` configured in config.yaml

#### cost_center_rules (Tier 5)

```yaml
cost_center_rules:
  - category_codes: ["SC0207"]
    cost_center_pattern: "surgical services"
    taxonomy_key: "Medical > Medical Consumables > Surgical Supplies"
    confidence: 0.70
```

**Fields:**
- `category_codes` (required): List of category codes this rule applies to
- `cost_center_pattern` (required): Case-insensitive regex to match cost center
- `taxonomy_key` (required): Taxonomy key to assign if match
- `confidence` (required): Confidence score (0.0-1.0)

**Requires:** `columns.cost_center` configured in config.yaml

#### supplier_override_rules (Tier 7, post-classification)

```yaml
supplier_override_rules:
  - supplier_pattern: "grainger"
    override_from_l1: ["Facilities"]
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    confidence: 0.90
```

**Fields:**
- `supplier_pattern` (required): Case-insensitive regex to match supplier name
- `override_from_l1` (required): List of CategoryLevel1 values to override
- `taxonomy_key` (required): Taxonomy key to assign if match
- `confidence` (required): Confidence score (0.0-1.0)

**Purpose:** Override classifications after all other tiers complete. Used for supplier-specific global rules (e.g., "All Grainger items in Facilities should be Operating Supplies").

### keyword_rules.yaml

Pattern-based rules for description and supplier text matching (Tier 3).

```yaml
rules:
  - pattern: '\b(IV|intravenous)\b'
    category: "Medical > Medical Consumables > IV Supplies"
    confidence: 0.95
  - pattern: 'hvac|air conditioning'
    category: "Facilities > Equipment & Machinery > HVAC"
    confidence: 0.90
```

**Fields:**
- `pattern` (required): Case-insensitive regex to match against `supplier + description` combined text
- `category` (required): Taxonomy key to assign if match
- `confidence` (optional, default: 0.95): Confidence score (0.0-1.0)

**Matching strategy:**
- Searches in `supplier` + space + `description` concatenated text
- Only applies to unclassified rows (Tier 3, after category mapping and supplier refinement)

### test_assertions.yaml

Regression testing file to validate known supplier mappings and rule counts.

```yaml
known_supplier_mappings:
  - category_code: "SC0250"
    supplier: "epic systems"
    expected_taxonomy: "IT & Telecoms > Software > Application Software"
  - category_code: "SC0207"
    supplier: "grainger"
    expected_taxonomy: "Facilities > Operating Supplies and Equipment"

min_rule_counts:
  supplier_rules: 230
  context_rules: 8
  cost_center_rules: 10
  supplier_override_rules: 11
```

**Purpose:** Validate rule file integrity and prevent accidental deletions.

**Sections:**
- `known_supplier_mappings`: Expected taxonomy for specific category code + supplier combinations
- `min_rule_counts`: Minimum expected rule counts by type

## Onboarding a New Client

Follow these steps to configure the engine for a new healthcare organization.

### Step 1: Analyze Input Data

**Questions to answer:**
1. What is the file format? (CSV or XLSX)
2. If XLSX, which sheet contains transaction data?
3. What columns are available?
   - Category field (required)
   - Supplier field (required)
   - Amount field (required)
   - Description field (optional but recommended)
   - Line of service field (optional)
   - Cost center field (optional)
4. What category system is used? (Spend Categories, UNSPSC, custom codes)
5. Are category codes embedded in text or standalone? (e.g., "SC0250" vs "SC0250 - Professional Services")

**Example (UCH):**
- Format: XLSX, sheet "Org Data Pull"
- Columns: Category Name, Supplier, Item Description, Cost Center Description, Paid Amount
- Category system: UNSPSC codes like "39101612-Incandescent Lamps"
- Category code pattern: Numeric code before hyphen

### Step 2: Create Directory Structure

```bash
mkdir -p clients/{client_name}/data/input
mkdir -p clients/{client_name}/data/reference
mkdir -p clients/{client_name}/output
```

**Copy input data:**
```bash
cp /path/to/client_data.xlsx clients/{client_name}/data/input/
```

### Step 3: Write config.yaml

Start with this minimal template:

```yaml
client:
  name: "{CLIENT_NAME}"
  description: "{Organization Name} — {ERP System}"

paths:
  input: "data/input/{filename}.csv"
  category_mapping: "data/reference/{client}_category_mapping.yaml"
  taxonomy: "../../shared/reference/Healthcare Taxonomy v2.9.xlsx"
  keyword_rules: "data/reference/keyword_rules.yaml"
  refinement_rules: "data/reference/{client}_refinement_rules.yaml"
  output_dir: "output"
  output_prefix: "{client}_categorization_results"

input_format:
  sheet_name: "Sheet1"  # Only if XLSX

columns:
  category_source: "Category Column Name"
  supplier: "Supplier Column Name"
  description: "Description Column Name"  # Optional
  amount: "Amount Column Name"
  passthrough:
    - "Invoice Number"
    - "PO Number"

classification:
  category_code_pattern: '^(\d+)'  # Optional, adjust regex
  confidence_high: 0.7
  confidence_medium: 0.5

aggregations:
  - name: "Spend by Cost Center"
    column: "Cost Center"
    top_n: null
```

**Save to:** `clients/{client_name}/config.yaml`

### Step 4: Create category_mapping.yaml

Identify all unique category codes in the input data:

```bash
python src/categorize.py --config clients/{client_name}/config.yaml
# Will fail initially, but shows unique category codes in error output
```

Map each code to a taxonomy key in `data/reference/{client}_category_mapping.yaml`:

```yaml
mappings:
  "39101612":
    name: "Incandescent Lamps"
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    ambiguous: true
  "99000038":
    name: "Equipment Maintenance"
    taxonomy_key: "Facilities > Equipment & Machinery > Service & Maintenance"
    ambiguous: false
```

**Start with:**
- Non-ambiguous mappings first (straightforward 1-to-1)
- Mark broad/vague codes as `ambiguous: true` (will add refinement rules later)

### Step 5: Create refinement_rules.yaml

For ambiguous category codes, add supplier-specific refinement rules:

```yaml
supplier_rules:
  - category_codes: ["39101612"]
    supplier_pattern: "grainger"
    taxonomy_key: "Facilities > Operating Supplies and Equipment"
    confidence: 0.85

context_rules: []
cost_center_rules: []
supplier_override_rules: []
```

**Iterative process:**
1. Run engine, review Manual Review sheet
2. Identify patterns (e.g., "All Grainger items in code 39101612 are facilities supplies")
3. Add rule to appropriate section
4. Re-run and verify

### Step 6: Create keyword_rules.yaml

Add text pattern rules for description-based matching:

```yaml
rules:
  - pattern: '\b(IV|intravenous)\b'
    category: "Medical > Medical Consumables > IV Supplies"
    confidence: 0.95
  - pattern: 'surgical gown|sterile drape'
    category: "Medical > Medical Consumables > Surgical Supplies"
    confidence: 0.90
```

**Shared across clients:** Consider symlinking to `shared/reference/keyword_rules.yaml` if rules are generic.

### Step 7: Run the Engine and Iterate

```bash
python src/categorize.py --config clients/{client_name}/config.yaml
```

**Review output:**
1. Check Summary sheet for classification method distribution
2. Review Manual Review sheet for patterns
3. Check Unmapped Categories sheet for missing mappings
4. Verify high-spend items in All Results sheet

**Iterate:**
- Add missing category code mappings
- Refine ambiguous code rules
- Adjust confidence thresholds if needed
- Add keyword rules for common patterns

**Goal:** Achieve >80% Auto-Accept rate with <5% Unmapped rate.

### Step 8: Create test_assertions.yaml (Optional)

Document known-good classifications for regression testing:

```yaml
known_supplier_mappings:
  - category_code: "{CODE}"
    supplier: "{known_supplier}"
    expected_taxonomy: "{expected_category}"

min_rule_counts:
  supplier_rules: 50
  context_rules: 0
  cost_center_rules: 0
  supplier_override_rules: 0
```

**Save to:** `clients/{client_name}/test_assertions.yaml`

## Backward Compatibility

The engine automatically handles deprecated configuration keys and rule formats.

### Deprecated Config Keys

Legacy keys are automatically aliased to current names:

| Section | Legacy Key | Current Key |
|---------|-----------|-------------|
| paths | `sc_mapping` | `category_mapping` |
| columns | `spend_category` | `category_source` |
| columns | `line_memo` | `description` |
| classification | `sc_code_pattern` | `category_code_pattern` |

**Behavior:**
- If only legacy key is present, it is automatically renamed to current key
- Deprecation warning is printed to stderr
- If both keys are present, current key takes precedence

**Example deprecation warning:**
```
DEPRECATION: 'paths.sc_mapping' renamed to 'paths.category_mapping'. Update your config.
```

### Deprecated Rule Keys

Legacy rule keys in refinement_rules.yaml are automatically converted:

| Legacy Key | Current Key |
|-----------|-------------|
| `sc_codes` | `category_codes` |

**Behavior:**
- Conversion happens at load time
- No warning is printed (silent migration)

**Migration recommendation:** Update config files to use current keys during next maintenance cycle.

## Troubleshooting

### ConfigError: Missing required column mapping

**Error:**
```
ConfigError: Missing required column mapping: 'columns.category_source'
```

**Cause:** Required column mapping is missing from `columns` section in config.yaml.

**Fix:** Add all three required column mappings:
```yaml
columns:
  category_source: "YourCategoryColumnName"
  supplier: "YourSupplierColumnName"
  amount: "YourAmountColumnName"
```

### ConfigError: File not found

**Error:**
```
ConfigError: File not found: /full/path/to/file.yaml (from paths.category_mapping)
```

**Cause:** A file specified in `paths` section doesn't exist.

**Fix:**
1. Verify file exists at the path specified
2. Check that path is correct relative to config.yaml location
3. Create missing reference files (see Reference File Formats section)

**Remember:** All paths in config.yaml are relative to the config file location, not the current working directory.

### Columns not found in input

**Error:**
```
ConfigError: Columns not found in input: 'Spend Category' (from columns.category_source), 'Line Memo' (from columns.description)
```

**Cause:** Column names in config.yaml don't match actual column names in input file.

**Fix:**
1. Open input CSV/XLSX file and verify exact column names (case-sensitive)
2. Update config.yaml column mappings to match exactly
3. Check for leading/trailing spaces in column names

**Example:**
```yaml
# Input file has "Supplier Name" (not "Supplier")
columns:
  supplier: "Supplier Name"  # Must match exactly
```

### Many Unmapped Rows

**Symptom:** High percentage of rows in Manual Review sheet with method "unmapped".

**Causes:**
1. Missing category code mappings in category_mapping.yaml
2. Category codes not being extracted correctly (wrong `category_code_pattern`)
3. Input data has new category codes not seen before

**Diagnosis:**
1. Check Unmapped Categories sheet for most common unmapped codes
2. Verify `category_code_pattern` extracts correctly (test with sample values)
3. Review Manual Review sheet to see which codes are unmapped

**Fix:**
1. Add missing codes to category_mapping.yaml:
   ```yaml
   mappings:
     "NEW_CODE":
       taxonomy_key: "Appropriate > Taxonomy > Path"
       ambiguous: false
   ```
2. Fix category_code_pattern regex if extraction is failing
3. For broad codes, mark as ambiguous and add refinement rules

### Low Auto-Accept Rate

**Symptom:** Most rows in Quick Review or Manual Review tiers.

**Causes:**
1. Too many ambiguous category codes without refinement rules
2. Confidence thresholds too high
3. Missing supplier refinement rules for common patterns

**Fix:**
1. Review Manual Review sheet for patterns
2. Add supplier_rules for common supplier + category code combinations
3. Consider lowering `confidence_high` threshold from 0.7 to 0.65 (if classifications are accurate)
4. Add keyword rules for common description patterns

### Performance Issues (Large Datasets)

**Symptom:** Classification takes >5 minutes for 100K+ rows.

**Causes:**
1. Too many refinement rules (thousands of rules)
2. Complex regex patterns in rules
3. Large number of keyword rules

**Fix:**
1. Optimize regex patterns (avoid greedy quantifiers like `.*`)
2. Reduce number of keyword rules (consolidate similar patterns)
3. Mark more codes as non-ambiguous (reduces refinement rule evaluations)
4. Consider upgrading to pandas 2.x for performance improvements

**Note:** The engine uses vectorized pandas operations and should process 100K rows in 10-30 seconds on modern hardware.
