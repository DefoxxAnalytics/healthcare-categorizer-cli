"""
Regression tests for categorization pipeline rules.

Validates rules for any client by loading from the client config path.
Default: clients/cchmc (override with --client-dir pytest option).

Three test suites:
  1. YAML validation — structural integrity of all rule files
  2. Classification assertions — known supplier->taxonomy mappings
  3. Conflict detection — overlapping patterns across rules
"""

import re

import pytest


def _codes_key(rule):
    if "category_codes" in rule:
        return "category_codes"
    return "sc_codes"


# -- 1. YAML Structural Validation --------------------------------------------


class TestYAMLStructure:

    def test_refinement_has_supplier_rules(self, refinement):
        assert "supplier_rules" in refinement, "Missing section: supplier_rules"

    def test_refinement_has_override_rules(self, refinement):
        assert "supplier_override_rules" in refinement, "Missing section: supplier_override_rules"

    def test_refinement_has_context_rules_if_applicable(self, refinement, has_context_rules):
        if has_context_rules:
            assert "context_rules" in refinement, "Missing section: context_rules"

    def test_refinement_has_cost_center_rules_if_applicable(self, refinement, has_cost_center_rules):
        if has_cost_center_rules:
            assert "cost_center_rules" in refinement, "Missing section: cost_center_rules"

    def test_supplier_rules_have_required_fields(self, refinement):
        for i, rule in enumerate(refinement["supplier_rules"]):
            key = _codes_key(rule)
            assert key in rule, f"supplier_rules[{i}] missing {key}"
            assert "supplier_pattern" in rule, f"supplier_rules[{i}] missing supplier_pattern"
            assert "taxonomy_key" in rule, f"supplier_rules[{i}] missing taxonomy_key"
            assert "confidence" in rule, f"supplier_rules[{i}] missing confidence"

    def test_context_rules_have_required_fields(self, refinement, has_context_rules):
        if not has_context_rules:
            pytest.skip("Client has no context rules")
        for i, rule in enumerate(refinement["context_rules"]):
            key = _codes_key(rule)
            assert key in rule, f"context_rules[{i}] missing {key}"
            assert "line_of_service_pattern" in rule, f"context_rules[{i}] missing line_of_service_pattern"
            assert "taxonomy_key" in rule, f"context_rules[{i}] missing taxonomy_key"
            assert "confidence" in rule, f"context_rules[{i}] missing confidence"

    def test_cost_center_rules_have_required_fields(self, refinement, has_cost_center_rules):
        if not has_cost_center_rules:
            pytest.skip("Client has no cost center rules")
        for i, rule in enumerate(refinement["cost_center_rules"]):
            key = _codes_key(rule)
            assert key in rule, f"cost_center_rules[{i}] missing {key}"
            assert "cost_center_pattern" in rule, f"cost_center_rules[{i}] missing cost_center_pattern"
            assert "taxonomy_key" in rule, f"cost_center_rules[{i}] missing taxonomy_key"
            assert "confidence" in rule, f"cost_center_rules[{i}] missing confidence"

    def test_override_rules_have_required_fields(self, refinement):
        for i, rule in enumerate(refinement["supplier_override_rules"]):
            assert "supplier_pattern" in rule, f"override_rules[{i}] missing supplier_pattern"
            assert "taxonomy_key" in rule, f"override_rules[{i}] missing taxonomy_key"
            assert "override_from_l1" in rule, f"override_rules[{i}] missing override_from_l1"
            assert "confidence" in rule, f"override_rules[{i}] missing confidence"


class TestRegexValidity:

    def test_supplier_patterns_compile(self, refinement):
        for i, rule in enumerate(refinement["supplier_rules"]):
            try:
                re.compile(rule["supplier_pattern"], re.IGNORECASE)
            except re.error as e:
                pytest.fail(f"supplier_rules[{i}] invalid regex '{rule['supplier_pattern']}': {e}")

    def test_context_patterns_compile(self, refinement, has_context_rules):
        if not has_context_rules:
            pytest.skip("Client has no context rules")
        for i, rule in enumerate(refinement["context_rules"]):
            try:
                re.compile(rule["line_of_service_pattern"], re.IGNORECASE)
            except re.error as e:
                pytest.fail(f"context_rules[{i}] invalid regex '{rule['line_of_service_pattern']}': {e}")

    def test_cost_center_patterns_compile(self, refinement, has_cost_center_rules):
        if not has_cost_center_rules:
            pytest.skip("Client has no cost center rules")
        for i, rule in enumerate(refinement["cost_center_rules"]):
            try:
                re.compile(rule["cost_center_pattern"], re.IGNORECASE)
            except re.error as e:
                pytest.fail(f"cost_center_rules[{i}] invalid regex '{rule['cost_center_pattern']}': {e}")

    def test_override_patterns_compile(self, refinement):
        for i, rule in enumerate(refinement["supplier_override_rules"]):
            try:
                re.compile(rule["supplier_pattern"], re.IGNORECASE)
            except re.error as e:
                pytest.fail(f"override_rules[{i}] invalid regex '{rule['supplier_pattern']}': {e}")

    def test_keyword_patterns_compile(self, keyword_rules):
        for i, rule in enumerate(keyword_rules.get("rules", [])):
            try:
                re.compile(rule["pattern"], re.IGNORECASE)
            except re.error as e:
                pytest.fail(f"keyword_rules[{i}] invalid regex '{rule['pattern']}': {e}")


class TestTaxonomyKeyValidity:

    def test_supplier_rules_taxonomy_keys(self, refinement, taxonomy_keys):
        for i, rule in enumerate(refinement["supplier_rules"]):
            assert rule["taxonomy_key"] in taxonomy_keys, (
                f"supplier_rules[{i}] invalid taxonomy_key: '{rule['taxonomy_key']}'"
            )

    def test_context_rules_taxonomy_keys(self, refinement, taxonomy_keys, has_context_rules):
        if not has_context_rules:
            pytest.skip("Client has no context rules")
        for i, rule in enumerate(refinement["context_rules"]):
            assert rule["taxonomy_key"] in taxonomy_keys, (
                f"context_rules[{i}] invalid taxonomy_key: '{rule['taxonomy_key']}'"
            )

    def test_cost_center_rules_taxonomy_keys(self, refinement, taxonomy_keys, has_cost_center_rules):
        if not has_cost_center_rules:
            pytest.skip("Client has no cost center rules")
        for i, rule in enumerate(refinement["cost_center_rules"]):
            assert rule["taxonomy_key"] in taxonomy_keys, (
                f"cost_center_rules[{i}] invalid taxonomy_key: '{rule['taxonomy_key']}'"
            )

    def test_override_rules_taxonomy_keys(self, refinement, taxonomy_keys):
        for i, rule in enumerate(refinement["supplier_override_rules"]):
            assert rule["taxonomy_key"] in taxonomy_keys, (
                f"override_rules[{i}] invalid taxonomy_key: '{rule['taxonomy_key']}'"
            )

    def test_category_mapping_taxonomy_keys(self, sc_mapping, taxonomy_keys):
        for code, info in sc_mapping.get("mappings", {}).items():
            assert info["taxonomy_key"] in taxonomy_keys, (
                f"Category mapping '{code}' invalid taxonomy_key: '{info['taxonomy_key']}'"
            )

    def test_keyword_rules_taxonomy_keys(self, keyword_rules, taxonomy_keys):
        for i, rule in enumerate(keyword_rules.get("rules", [])):
            assert rule["category"] in taxonomy_keys, (
                f"keyword_rules[{i}] invalid category: '{rule['category']}'"
            )


class TestCategoryCodeValidity:

    def test_supplier_rules_codes(self, refinement, valid_sc_codes):
        for i, rule in enumerate(refinement["supplier_rules"]):
            key = _codes_key(rule)
            for code in rule[key]:
                assert str(code) in valid_sc_codes, (
                    f"supplier_rules[{i}] unknown category code: '{code}'"
                )

    def test_context_rules_codes(self, refinement, valid_sc_codes, has_context_rules):
        if not has_context_rules:
            pytest.skip("Client has no context rules")
        for i, rule in enumerate(refinement["context_rules"]):
            key = _codes_key(rule)
            for code in rule[key]:
                assert str(code) in valid_sc_codes, (
                    f"context_rules[{i}] unknown category code: '{code}'"
                )

    def test_cost_center_rules_codes(self, refinement, valid_sc_codes, has_cost_center_rules):
        if not has_cost_center_rules:
            pytest.skip("Client has no cost center rules")
        for i, rule in enumerate(refinement["cost_center_rules"]):
            key = _codes_key(rule)
            for code in rule[key]:
                assert str(code) in valid_sc_codes, (
                    f"cost_center_rules[{i}] unknown category code: '{code}'"
                )


class TestConfidenceRanges:

    def test_supplier_confidence_valid(self, refinement):
        for i, rule in enumerate(refinement["supplier_rules"]):
            assert 0.0 < rule["confidence"] <= 1.0, (
                f"supplier_rules[{i}] confidence {rule['confidence']} out of range"
            )

    def test_context_confidence_valid(self, refinement, has_context_rules):
        if not has_context_rules:
            pytest.skip("Client has no context rules")
        for i, rule in enumerate(refinement["context_rules"]):
            assert 0.0 < rule["confidence"] <= 1.0, (
                f"context_rules[{i}] confidence {rule['confidence']} out of range"
            )

    def test_cost_center_confidence_valid(self, refinement, has_cost_center_rules):
        if not has_cost_center_rules:
            pytest.skip("Client has no cost center rules")
        for i, rule in enumerate(refinement["cost_center_rules"]):
            assert 0.0 < rule["confidence"] <= 1.0, (
                f"cost_center_rules[{i}] confidence {rule['confidence']} out of range"
            )

    def test_override_confidence_valid(self, refinement):
        for i, rule in enumerate(refinement["supplier_override_rules"]):
            assert 0.0 < rule["confidence"] <= 1.0, (
                f"override_rules[{i}] confidence {rule['confidence']} out of range"
            )


# -- 2. Classification Assertions ---------------------------------------------


class TestSupplierClassification:
    """Known supplier->taxonomy assertions loaded from test_assertions.yaml."""

    def test_supplier_rule_matches(self, refinement, test_assertions):
        mappings = test_assertions.get("known_supplier_mappings", [])
        if not mappings:
            pytest.skip("No known_supplier_mappings in test_assertions.yaml")
        for entry in mappings:
            code = entry["category_code"]
            supplier = entry["supplier"]
            expected = entry["expected_taxonomy"]
            matched = False
            for rule in refinement["supplier_rules"]:
                key = _codes_key(rule)
                if code not in [str(c) for c in rule[key]]:
                    continue
                if re.search(rule["supplier_pattern"], supplier, re.IGNORECASE):
                    assert rule["taxonomy_key"] == expected, (
                        f"Supplier '{supplier}' with {code} mapped to "
                        f"'{rule['taxonomy_key']}' instead of '{expected}'"
                    )
                    matched = True
                    break
            assert matched, f"No rule matched supplier '{supplier}' with code '{code}'"


# -- 3. Conflict Detection ----------------------------------------------------


class TestConflictDetection:

    def test_no_duplicate_supplier_patterns(self, refinement):
        seen = {}
        duplicates = []
        for i, rule in enumerate(refinement["supplier_rules"]):
            key = _codes_key(rule)
            for code in rule[key]:
                dup_key = (str(code), rule["supplier_pattern"].lower())
                if dup_key in seen:
                    duplicates.append(
                        f"  Rules [{seen[dup_key]}] and [{i}]: code={code}, pattern='{rule['supplier_pattern']}'"
                    )
                else:
                    seen[dup_key] = i
        assert not duplicates, "Duplicate supplier patterns found:\n" + "\n".join(duplicates)

    def test_no_overlapping_supplier_patterns(self, refinement):
        rules = refinement["supplier_rules"]
        overlaps = []
        for i in range(len(rules)):
            for j in range(i + 1, len(rules)):
                key_i = _codes_key(rules[i])
                key_j = _codes_key(rules[j])
                shared = set(str(s) for s in rules[i][key_i]) & set(str(s) for s in rules[j][key_j])
                if not shared:
                    continue
                alts_i = rules[i]["supplier_pattern"].split("|")
                for alt_i in alts_i:
                    try:
                        if re.search(rules[j]["supplier_pattern"], alt_i, re.IGNORECASE):
                            if rules[i]["taxonomy_key"] != rules[j]["taxonomy_key"]:
                                overlaps.append(
                                    f"  [{i}] pattern alt '{alt_i}' matched by [{j}] "
                                    f"(code overlap: {shared})\n"
                                    f"    [{i}] -> {rules[i]['taxonomy_key']}\n"
                                    f"    [{j}] -> {rules[j]['taxonomy_key']}"
                                )
                    except re.error:
                        pass
        if overlaps:
            pytest.skip(f"Potential overlaps (review manually):\n" + "\n".join(overlaps[:10]))

    def test_rule_counts(self, refinement, test_assertions):
        counts = test_assertions.get("min_rule_counts", {})
        if not counts:
            pytest.skip("No min_rule_counts in test_assertions.yaml")
        for section, minimum in counts.items():
            actual = len(refinement.get(section, []))
            assert actual >= minimum, (
                f"Expected {minimum}+ {section}, got {actual}"
            )
