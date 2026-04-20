#!/usr/bin/env python3
"""
Orca Spec IR Validator
======================

Validates a spec.ir.json (structured IR) before it enters the Orca
task decomposition pipeline.

Pass 1 (LLM): spec.md → spec.ir.json
Validator: Validates IR against spec-schema-v2.json + custom rules
If valid → pass to Orca decompose
If invalid → return specific errors to LLM for correction

Usage:
    python validator.py spec.ir.json
    python validator.py spec.ir.json spec-schema-v2.json
"""

import json
import re
import sys
from pathlib import Path
from typing import Any


class ValidationError:
    def __init__(self, field: str, message: str, suggestion: str = ""):
        self.field = field
        self.message = message
        self.suggestion = suggestion

    def __str__(self):
        result = f"  ✗ {self.field}: {self.message}"
        if self.suggestion:
            result += f"\n    → {self.suggestion}"
        return result


class SpecIRValidator:
    def __init__(self, schema_path: str):
        with open(schema_path) as f:
            self.schema = json.load(f)
        self.errors: list[ValidationError] = []

    def validate(self, ir: dict) -> bool:
        """Run all validations. Returns True if valid."""
        self.errors = []
        self._validate_schema(ir)
        if self.errors:
            return False
        self._validate_per_feature_acs(ir)
        self._validate_cross_references(ir)
        self._validate_feature_consistency(ir)
        self._validate_testing_coverage(ir)
        self._validate_enumerations(ir)
        return len(self.errors) == 0

    def _validate_schema(self, ir: dict) -> None:
        """Basic JSON Schema validation (manual implementation)."""
        required_fields = self.schema.get("required", [])
        for field in required_fields:
            if field not in ir:
                self.errors.append(ValidationError(
                    field=f"root.{field}",
                    message=f"Required field missing",
                    suggestion=f"Add '{field}' to the IR"
                ))

    def _validate_per_feature_acs(self, ir: dict) -> None:
        """Validate per-feature acceptance criteria structure.

        Each feature must have an acceptanceCriteria object with at least
        one happyPath criterion. Each criterion must have id + criterion string
        in Given/When/Then format.
        """
        features = ir.get("coreFeatures", {})
        for tier in ["mustHave", "shouldHave", "niceToHave"]:
            for feature in features.get(tier, []):
                feat_id = feature.get("id", "unknown")
                acs = feature.get("acceptanceCriteria", {})

                # Feature must have acceptanceCriteria object
                if not acs:
                    self.errors.append(ValidationError(
                        field=f"coreFeatures.{tier}.{feat_id}",
                        message="Feature has no acceptanceCriteria defined",
                        suggestion="Add an acceptanceCriteria object with happyPath criteria"
                    ))
                    continue

                # Must have at least one happy path criterion
                happy_path = acs.get("happyPath", [])
                if not happy_path:
                    self.errors.append(ValidationError(
                        field=f"coreFeatures.{tier}.{feat_id}.acceptanceCriteria",
                        message="Feature has no happyPath acceptance criteria",
                        suggestion="Add at least one happy path criterion: { id: 'FEAT-XXX/AC-001', criterion: 'Given...When...Then...' }"
                    ))

                # Validate each acceptance criterion
                for ac in happy_path:
                    self._validate_acceptance_criterion(acs, tier, feat_id, ac, "happyPath")

                # Validate error handling criteria (if any)
                error_handling = acs.get("errorHandling", [])
                for ac in error_handling:
                    self._validate_acceptance_criterion(acs, tier, feat_id, ac, "errorHandling")

    def _validate_acceptance_criterion(self, acs: dict, tier: str, feat_id: str, ac: Any, ac_type: str) -> None:
        """Validate a single acceptance criterion object."""
        if not isinstance(ac, dict):
            self.errors.append(ValidationError(
                field=f"coreFeatures.{tier}.{feat_id}.acceptanceCriteria.{ac_type}",
                message=f"Acceptance criterion must be an object with 'id' and 'criterion', got {type(ac).__name__}",
                suggestion="Use format: { id: 'FEAT-001/AC-001', criterion: 'Given...When...Then...' }"
            ))
            return

        # Validate ID presence and format
        ac_id = ac.get("id", "")
        if not ac_id:
            self.errors.append(ValidationError(
                field=f"coreFeatures.{tier}.{feat_id}.acceptanceCriteria.{ac_type}",
                message="Acceptance criterion missing 'id' field",
                suggestion="Add an id: 'FEAT-XXX/AC-YYY'"
            ))
        elif not re.match(r"^FEAT-[0-9]+/AC-[0-9]+$", ac_id):
            self.errors.append(ValidationError(
                field=f"coreFeatures.{tier}.{feat_id}.acceptanceCriteria.{ac_type}.id",
                message=f"Invalid AC ID format: '{ac_id}'",
                suggestion="Use format: FEAT-XXX/AC-YYY (e.g., FEAT-001/AC-001)"
            ))

        # Validate criterion string format
        criterion = ac.get("criterion", "")
        if not criterion:
            self.errors.append(ValidationError(
                field=f"coreFeatures.{tier}.{feat_id}.acceptanceCriteria.{ac_type}.criterion",
                message="Acceptance criterion missing 'criterion' field",
                suggestion="Add a criterion: 'Given...When...Then...'"
            ))
        elif not (criterion.startswith("Given") and "When" in criterion and "Then" in criterion):
            self.errors.append(ValidationError(
                field=f"coreFeatures.{tier}.{feat_id}.acceptanceCriteria.{ac_type}.criterion",
                message=f"Criterion doesn't follow 'Given...When...Then...' format: {criterion[:50]}...",
                suggestion="Use format: 'Given <context> When <action> Then <result>'"
            ))

    def _validate_cross_references(self, ir: dict) -> None:
        """Verify internal consistency across sections.

        Legacy check: validates project-level acceptance criteria (flat strings).
        Per-feature AC references are validated by _validate_per_feature_acs.
        """
        features = ir.get("coreFeatures", {})
        must_have = features.get("mustHave", [])
        should_have = features.get("shouldHave", [])
        nice_have = features.get("niceToHave", [])

        # Collect all feature IDs
        all_features = must_have + should_have + nice_have
        feature_ids = {f["id"] for f in all_features if "id" in f}

        # Check project-level acceptance criteria references (legacy)
        acceptance = ir.get("acceptanceCriteria", {})
        all_criteria = (
            acceptance.get("happyPath", []) +
            acceptance.get("errorHandling", []) +
            acceptance.get("performance", []) +
            acceptance.get("security", [])
        )

        # Handle both string and object formats (backward compat)
        for criterion in all_criteria:
            # String format (legacy): "Given...FEAT-001...When..."
            if isinstance(criterion, str):
                refs = re.findall(r"FEAT-\d+", criterion)
                for ref in refs:
                    if ref not in feature_ids:
                        self.errors.append(ValidationError(
                            field="acceptanceCriteria",
                            message=f"Criterion references '{ref}' but no such feature exists",
                            suggestion=f"Either add feature {ref} to coreFeatures or fix the reference"
                        ))
            # Object format: { id: "FEAT-001/AC-001", criterion: "Given..." }
            elif isinstance(criterion, dict):
                # Extract feature ID from AC ID
                ac_id = criterion.get("id", "")
                if ac_id:
                    match = re.match(r"(FEAT-\d+)/AC-\d+", ac_id)
                    if match:
                        feat_ref = match.group(1)
                        if feat_ref not in feature_ids:
                            self.errors.append(ValidationError(
                                field=f"acceptanceCriteria.{ac_id}",
                                message=f"AC ID references '{feat_ref}' but no such feature exists",
                                suggestion=f"Either add feature {feat_ref} to coreFeatures or fix the ID"
                            ))

    def _validate_feature_consistency(self, ir: dict) -> None:
        """Features should have realistic edge case counts."""
        features = ir.get("coreFeatures", {})
        for tier in ["mustHave", "shouldHave", "niceToHave"]:
            for feature in features.get(tier, []):
                desc = feature.get("description", "")
                edge_cases = feature.get("edgeCases", [])

                # Every feature should have at least one edge case
                if len(edge_cases) == 0:
                    self.errors.append(ValidationError(
                        field=f"coreFeatures.{tier}.{feature.get('id', 'unknown')}",
                        message="Feature has no edge cases specified",
                        suggestion="Consider: what could go wrong? what invalid inputs exist?"
                    ))

                # Description should be substantive
                if len(desc) < 20:
                    self.errors.append(ValidationError(
                        field=f"coreFeatures.{tier}.{feature.get('id', 'unknown')}.description",
                        message="Feature description is too short to be actionable",
                        suggestion="Describe WHAT the feature does and WHAT it produces"
                    ))

    def _validate_testing_coverage(self, ir: dict) -> None:
        """Ensure testing strategy matches project scope."""
        testing = ir.get("testingStrategy", {})
        tech = ir.get("technicalApproach", {})

        # If it's a microservices or API project, should have integration tests
        arch = tech.get("architecture", "")
        if arch in ["microservices", "serverless"]:
            integ = testing.get("integrationTests", {})
            if not integ.get("covered", False):
                self.errors.append(ValidationError(
                    field="testingStrategy.integrationTests",
                    message="Microservice/serverless architecture requires integration tests",
                    suggestion="Set covered: true and specify approach (test-containers recommended)"
                ))

        # Anti-cheating measures should exist for non-trivial projects
        must_have_count = len(ir.get("coreFeatures", {}).get("mustHave", []))
        anti_cheating = testing.get("antiCheating", [])
        if must_have_count >= 3 and len(anti_cheating) == 0:
            self.errors.append(ValidationError(
                field="testingStrategy.antiCheating",
                message="Project has multiple features but no anti-cheating measures",
                suggestion="Add ways to verify tests aren't faked: coverage enforcement, mutation testing, property-based tests"
            ))

    def _validate_enumerations(self, ir: dict) -> None:
        """Validate that enum fields have valid values."""
        tech = ir.get("technicalApproach", {})

        valid_languages = ["python", "typescript", "javascript", "go", "rust", "java",
                          "csharp", "cpp", "ruby", "php", "swift", "kotlin", "scala",
                          "bash", "unknown"]
        if tech.get("language") not in valid_languages:
            self.errors.append(ValidationError(
                field="technicalApproach.language",
                message=f"Unknown language: {tech.get('language')}",
                suggestion=f"Use one of: {', '.join(valid_languages)}"
            ))

        valid_arch = ["monolith", "microservices", "serverless", "library", "cli",
                      "daemon", "web", "mobile", "desktop", "embedded", "unknown"]
        if tech.get("architecture") not in valid_arch:
            self.errors.append(ValidationError(
                field="technicalApproach.architecture",
                message=f"Unknown architecture: {tech.get('architecture')}",
                suggestion=f"Use one of: {', '.join(valid_arch)}"
            ))

    def get_errors(self) -> list[ValidationError]:
        return self.errors


def validate_file(ir_path: str, schema_path: str) -> bool:
    """Validate an IR file and print results."""
    with open(ir_path) as f:
        ir = json.load(f)

    validator = SpecIRValidator(schema_path)
    valid = validator.validate(ir)

    print(f"\n{'='*60}")
    print(f"Validating: {Path(ir_path).name}")
    print(f"{'='*60}")

    if valid:
        print("\n✓ IR is valid. Ready for Orca decompose.")
        return True
    else:
        print(f"\n✗ Found {len(validator.get_errors())} validation error(s):\n")
        for error in validator.get_errors():
            print(error)
        print(f"\n{'='*60}")
        print("Fix the above issues and re-validate before proceeding.")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: validator.py <spec-ir.json> [schema.json]")
        print("       validator.py spec.ir.json")
        sys.exit(1)

    ir_path = sys.argv[1]
    schema_path = sys.argv[2] if len(sys.argv) > 2 else str(
        Path(__file__).parent / "spec-schema-v2.json"
    )

    if not Path(ir_path).exists():
        print(f"Error: File not found: {ir_path}")
        sys.exit(1)

    valid = validate_file(ir_path, schema_path)
    sys.exit(0 if valid else 1)


if __name__ == "__main__":
    main()
