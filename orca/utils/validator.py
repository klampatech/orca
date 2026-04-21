#!/usr/bin/env python3
"""
Orca Spec IR Validator
======================

Validates spec.ir.json (structured IR) before it enters the Orca
task decomposition pipeline. Uses Python stdlib only — no external dependencies.

Pass 1 (LLM): spec.md → spec.ir.json
Validator: Validates IR against spec-schema-v2.json + custom rules
If valid → pass to Orca decompose
If invalid → return specific errors to LLM for correction

Usage (CLI):
    python validator.py spec.ir.json
    python validator.py spec.ir.json --schema path/to/schema.json

Usage (import):
    from orca.utils.validator import SpecIRValidator
    validator = SpecIRValidator()
    valid, errors = validator.validate_file("spec.ir.json")
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


# --------------------------------------------------------------------
# Schema path resolution
# --------------------------------------------------------------------

def _get_default_schema_path() -> str:
    """Get path to bundled spec-schema-v2.json.
    
    Looks in (in order):
    1. Same directory as this module (orca/utils/)
    2. Parent data/ directory (orca/data/)
    3. Current working directory
    """
    module_dir = Path(__file__).parent.resolve()
    
    # Try: orca/utils/spec-schema-v2.json
    schema_path = module_dir / "spec-schema-v2.json"
    if schema_path.exists():
        return str(schema_path)
    
    # Try: orca/data/spec-schema-v2.json (one level up)
    schema_path = module_dir.parent / "data" / "spec-schema-v2.json"
    if schema_path.exists():
        return str(schema_path)
    
    # Fallback: cwd
    return "spec-schema-v2.json"


# --------------------------------------------------------------------
# Validation error representation
# --------------------------------------------------------------------

class ValidationError:
    """A single validation error with field path, message, and suggestion."""
    
    def __init__(self, field: str, message: str, suggestion: str = ""):
        self.field = field
        self.message = message
        self.suggestion = suggestion

    def __str__(self) -> str:
        result = f"  ✗ {self.field}: {self.message}"
        if self.suggestion:
            result += f"\n    → {self.suggestion}"
        return result


# --------------------------------------------------------------------
# Main validator class
# --------------------------------------------------------------------

class SpecIRValidator:
    """Validates a structured IR document against the Orca spec schema v2."""
    
    def __init__(self, schema_path: str | None = None):
        """Initialize validator with optional schema path.
        
        Args:
            schema_path: Path to JSON schema. Defaults to bundled spec-schema-v2.json.
        """
        if schema_path is None:
            schema_path = _get_default_schema_path()
        self.schema_path = schema_path
        self._schema: dict[str, Any] | None = None

    @property
    def schema(self) -> dict[str, Any]:
        """Lazy-load schema on first access."""
        if self._schema is None:
            with open(self.schema_path) as f:
                self._schema = json.load(f)
        return self._schema

    def validate(self, ir: dict[str, Any]) -> tuple[bool, list[ValidationError]]:
        """Run all validations. Returns (is_valid, errors).
        
        Args:
            ir: Parsed IR document (dict).
            
        Returns:
            Tuple of (valid: bool, errors: list[ValidationError]).
        """
        errors: list[ValidationError] = []
        errors.extend(self._validate_schema(ir))
        if errors:
            return False, errors
        errors.extend(self._validate_per_feature_acs(ir))
        errors.extend(self._validate_cross_references(ir))
        errors.extend(self._validate_feature_consistency(ir))
        errors.extend(self._validate_testing_coverage(ir))
        errors.extend(self._validate_enumerations(ir))
        return len(errors) == 0, errors

    def validate_file(self, ir_path: str | Path) -> tuple[bool, list[ValidationError]]:
        """Validate an IR file. Returns (valid, errors).
        
        Args:
            ir_path: Path to spec.ir.json file.
            
        Returns:
            Tuple of (valid: bool, errors: list[ValidationError]).
        """
        with open(ir_path) as f:
            ir = json.load(f)
        return self.validate(ir)

    def _validate_schema(self, ir: dict[str, Any]) -> list[ValidationError]:
        """Basic JSON Schema validation (manual implementation)."""
        errors: list[ValidationError] = []
        required_fields = self.schema.get("required", [])
        for field in required_fields:
            if field not in ir:
                errors.append(ValidationError(
                    field=f"root.{field}",
                    message=f"Required field missing",
                    suggestion=f"Add '{field}' to the IR"
                ))
        return errors

    def _validate_per_feature_acs(self, ir: dict[str, Any]) -> list[ValidationError]:
        """Validate per-feature acceptance criteria structure.

        Each feature must have an acceptanceCriteria object with at least
        one happyPath criterion. Each criterion must have id + criterion string
        in Given/When/Then format.
        """
        errors: list[ValidationError] = []
        features = ir.get("coreFeatures", {})
        
        for tier in ["mustHave", "shouldHave", "niceToHave"]:
            for feature in features.get(tier, []):
                feat_id = feature.get("id", "unknown")
                acs = feature.get("acceptanceCriteria", {})

                # Feature must have acceptanceCriteria object
                if not acs:
                    errors.append(ValidationError(
                        field=f"coreFeatures.{tier}.{feat_id}",
                        message="Feature has no acceptanceCriteria defined",
                        suggestion="Add an acceptanceCriteria object with happyPath criteria"
                    ))
                    continue

                # Must have at least one happy path criterion
                happy_path = acs.get("happyPath", [])
                if not happy_path:
                    errors.append(ValidationError(
                        field=f"coreFeatures.{tier}.{feat_id}.acceptanceCriteria",
                        message="Feature has no happyPath acceptance criteria",
                        suggestion="Add at least one happy path criterion: { id: 'FEAT-XXX/AC-001', criterion: 'Given...When...Then...' }"
                    ))

                # Validate each acceptance criterion
                for ac in happy_path:
                    self._validate_acceptance_criterion(errors, acs, tier, feat_id, ac, "happyPath")

                # Validate error handling criteria (if any)
                error_handling = acs.get("errorHandling", [])
                for ac in error_handling:
                    self._validate_acceptance_criterion(errors, acs, tier, feat_id, ac, "errorHandling")

        return errors

    def _validate_acceptance_criterion(
        self,
        errors: list[ValidationError],
        acs: dict[str, Any],
        tier: str,
        feat_id: str,
        ac: Any,
        ac_type: str
    ) -> None:
        """Validate a single acceptance criterion object."""
        if not isinstance(ac, dict):
            errors.append(ValidationError(
                field=f"coreFeatures.{tier}.{feat_id}.acceptanceCriteria.{ac_type}",
                message=f"Acceptance criterion must be an object with 'id' and 'criterion', got {type(ac).__name__}",
                suggestion="Use format: { id: 'FEAT-001/AC-001', criterion: 'Given...When...Then...' }"
            ))
            return

        # Validate ID presence and format
        # Accept both "FEAT-XXX/AC-YYY" (spec format) and "AC-YYY" (legacy)
        ac_id = ac.get("id", "")
        if not ac_id:
            errors.append(ValidationError(
                field=f"coreFeatures.{tier}.{feat_id}.acceptanceCriteria.{ac_type}",
                message="Acceptance criterion missing 'id' field",
                suggestion="Add an id: 'FEAT-XXX/AC-YYY'"
            ))
        elif not (re.match(r"^FEAT-[0-9]+/AC-[0-9]+$", ac_id) or re.match(r"^AC-[0-9]+$", ac_id)):
            errors.append(ValidationError(
                field=f"coreFeatures.{tier}.{feat_id}.acceptanceCriteria.{ac_type}.id",
                message=f"Invalid AC ID format: '{ac_id}'",
                suggestion="Use format: FEAT-XXX/AC-YYY (e.g., FEAT-001/AC-001)"
            ))

        # Validate criterion string format
        criterion = ac.get("criterion", "")
        if not criterion:
            errors.append(ValidationError(
                field=f"coreFeatures.{tier}.{feat_id}.acceptanceCriteria.{ac_type}.criterion",
                message="Acceptance criterion missing 'criterion' field",
                suggestion="Add a criterion: 'Given...When...Then...'"
            ))
        elif not (criterion.startswith("Given") and "When" in criterion and "Then" in criterion):
            errors.append(ValidationError(
                field=f"coreFeatures.{tier}.{feat_id}.acceptanceCriteria.{ac_type}.criterion",
                message=f"Criterion doesn't follow 'Given...When...Then...' format: {criterion[:50]}...",
                suggestion="Use format: 'Given <context> When <action> Then <result>'"
            ))

    def _validate_cross_references(self, ir: dict[str, Any]) -> list[ValidationError]:
        """Verify internal consistency across sections.

        Legacy check: validates project-level acceptance criteria (flat strings).
        Per-feature AC references are validated by _validate_per_feature_acs.
        """
        errors: list[ValidationError] = []
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
                        errors.append(ValidationError(
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
                            errors.append(ValidationError(
                                field=f"acceptanceCriteria.{ac_id}",
                                message=f"AC ID references '{feat_ref}' but no such feature exists",
                                suggestion=f"Either add feature {feat_ref} to coreFeatures or fix the ID"
                            ))

        return errors

    def _validate_feature_consistency(self, ir: dict[str, Any]) -> list[ValidationError]:
        """Features should have realistic edge case counts."""
        errors: list[ValidationError] = []
        features = ir.get("coreFeatures", {})
        
        for tier in ["mustHave", "shouldHave", "niceToHave"]:
            for feature in features.get(tier, []):
                desc = feature.get("description", "")
                edge_cases = feature.get("edgeCases", [])

                # Every feature should have at least one edge case
                if len(edge_cases) == 0:
                    errors.append(ValidationError(
                        field=f"coreFeatures.{tier}.{feature.get('id', 'unknown')}",
                        message="Feature has no edge cases specified",
                        suggestion="Consider: what could go wrong? what invalid inputs exist?"
                    ))

                # Description should be substantive
                if len(desc) < 20:
                    errors.append(ValidationError(
                        field=f"coreFeatures.{tier}.{feature.get('id', 'unknown')}.description",
                        message="Feature description is too short to be actionable",
                        suggestion="Describe WHAT the feature does and WHAT it produces"
                    ))

        return errors

    def _validate_testing_coverage(self, ir: dict[str, Any]) -> list[ValidationError]:
        """Ensure testing strategy matches project scope."""
        errors: list[ValidationError] = []
        testing = ir.get("testingStrategy", {})
        tech = ir.get("technicalApproach", {})

        # If it's a microservices or API project, should have integration tests
        arch = tech.get("architecture", "")
        if arch in ["microservices", "serverless"]:
            integ = testing.get("integrationTests", {})
            if not integ.get("covered", False):
                errors.append(ValidationError(
                    field="testingStrategy.integrationTests",
                    message="Microservice/serverless architecture requires integration tests",
                    suggestion="Set covered: true and specify approach (test-containers recommended)"
                ))

        # Anti-cheating measures should exist for non-trivial projects
        must_have_count = len(ir.get("coreFeatures", {}).get("mustHave", []))
        anti_cheating = testing.get("antiCheating", [])
        if must_have_count >= 3 and len(anti_cheating) == 0:
            errors.append(ValidationError(
                field="testingStrategy.antiCheating",
                message="Project has multiple features but no anti-cheating measures",
                suggestion="Add ways to verify tests aren't faked: coverage enforcement, mutation testing, property-based tests"
            ))
            
        return errors

    def _validate_enumerations(self, ir: dict[str, Any]) -> list[ValidationError]:
        """Validate that enum fields have valid values."""
        errors: list[ValidationError] = []
        tech = ir.get("technicalApproach", {})

        valid_languages = ["python", "typescript", "javascript", "go", "rust", "java",
                          "csharp", "cpp", "ruby", "php", "swift", "kotlin", "scala",
                          "bash", "unknown"]
        if tech.get("language") not in valid_languages:
            errors.append(ValidationError(
                field="technicalApproach.language",
                message=f"Unknown language: {tech.get('language')}",
                suggestion=f"Use one of: {', '.join(valid_languages)}"
            ))

        valid_arch = ["monolith", "microservices", "serverless", "library", "cli",
                      "daemon", "web", "mobile", "desktop", "embedded", "unknown"]
        if tech.get("architecture") not in valid_arch:
            errors.append(ValidationError(
                field="technicalApproach.architecture",
                message=f"Unknown architecture: {tech.get('architecture')}",
                suggestion=f"Use one of: {', '.join(valid_arch)}"
            ))
            
        return errors


# --------------------------------------------------------------------
# CLI interface
# --------------------------------------------------------------------

def format_errors(errors: list[ValidationError]) -> str:
    """Format validation errors for display."""
    lines = []
    for error in errors:
        lines.append(str(error))
    return "\n".join(lines)


def validate_file(ir_path: str, schema_path: str | None = None) -> bool:
    """Validate an IR file and print results. Returns exit code (0=valid, 1=invalid)."""
    validator = SpecIRValidator(schema_path)
    valid, errors = validator.validate_file(ir_path)

    print(f"\n{'='*60}")
    print(f"Validating: {Path(ir_path).name}")
    if validator.schema_path:
        print(f"Schema: {validator.schema_path}")
    print(f"{'='*60}")

    if valid:
        print("\n✓ IR is valid. Ready for Orca decompose.")
        return True
    else:
        print(f"\n✗ Found {len(errors)} validation error(s):\n")
        print(format_errors(errors))
        print(f"\n{'='*60}")
        print("Fix the above issues and re-validate before proceeding.")
        return False


def strip_markdown_json(text: str) -> str:
    """Strip markdown code blocks from LLM output to extract raw JSON.
    
    Handles:
    - ```json ... ``` 
    - ``` ... ```
    - Leading/trailing whitespace
    """
    text = text.strip()
    
    # Remove surrounding code blocks
    if text.startswith("```"):
        # Find the end of the opening fence
        lines = text.split("\n")
        if len(lines) > 1:
            # Remove first line (```json or ```)
            text = "\n".join(lines[1:])
            # Remove last line (closing ```)
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]
    
    return text.strip()


def main() -> int:
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Validate spec.ir.json against Orca schema",
        prog="orca-validate",
    )
    parser.add_argument("spec_file", help="Path to spec.ir.json")
    parser.add_argument(
        "--schema",
        help="Path to schema (default: bundled spec-schema-v2.json)",
    )
    
    args = parser.parse_args()
    ir_path = Path(args.spec_file)
    
    if not ir_path.exists():
        print(f"Error: File not found: {ir_path}")
        return 1

    valid = validate_file(str(ir_path), args.schema)
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())