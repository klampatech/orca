"""Tests for the SpecIRValidator utility module."""

from __future__ import annotations

from pathlib import Path

import pytest

from orca.utils.validator import SpecIRValidator, ValidationError


class TestValidationError:
    """Tests for ValidationError class."""

    def test_str_without_suggestion(self):
        """Should format message without suggestion."""
        err = ValidationError("field.path", "Test message")
        result = str(err)

        assert "field.path" in result
        assert "Test message" in result
        assert "→" not in result

    def test_str_with_suggestion(self):
        """Should include suggestion when provided."""
        err = ValidationError("field.path", "Test message", "Add the field")
        result = str(err)

        assert "field.path" in result
        assert "Test message" in result
        assert "→" in result
        assert "Add the field" in result


class TestSpecIRValidator:
    """Tests for SpecIRValidator class."""

    @pytest.fixture
    def validator(self):
        """Create a validator instance."""
        return SpecIRValidator()

    @pytest.fixture
    def valid_ir(self):
        """Complete valid IR structure matching the schema.

        Required fields per schema: project, coreFeatures, technicalApproach,
        testingStrategy, acceptanceCriteria.
        """
        return {
            "project": {
                "name": "TestProject",
                "vision": "A comprehensive test project with multiple features that demonstrate the validator works correctly.",
                "targetUsers": "Test users and developers",
                "problemStatement": "Testing the IR validation system",
                "successCriteria": "All tests pass",
            },
            "coreFeatures": {
                "mustHave": [
                    {
                        "id": "FEAT-001",
                        "description": "First test feature with multiple edge cases and acceptance criteria.",
                        "edgeCases": ["edge case 1", "edge case 2"],
                        "acceptanceCriteria": {
                            "happyPath": [
                                {"id": "FEAT-001/AC-001", "criterion": "Given a test When action Then result"}
                            ],
                            "errorHandling": [],
                        },
                    },
                    {
                        "id": "FEAT-002",
                        "description": "Second test feature with complete description and edge cases for validation.",
                        "edgeCases": ["edge case 1", "edge case 2"],
                        "acceptanceCriteria": {
                            "happyPath": [
                                {"id": "FEAT-002/AC-001", "criterion": "Given another test When action Then result"}
                            ],
                            "errorHandling": [],
                        },
                    },
                    {
                        "id": "FEAT-003",
                        "description": "Third test feature to ensure completeness check passes for realistic IRs.",
                        "edgeCases": ["edge case 1"],
                        "acceptanceCriteria": {
                            "happyPath": [
                                {"id": "FEAT-003/AC-001", "criterion": "Given third test When action Then result"}
                            ],
                            "errorHandling": [],
                        },
                    },
                ],
                "shouldHave": [],
                "niceToHave": [],
            },
            "technicalApproach": {
                "language": "python",
                "architecture": "monolith",
            },
            "testingStrategy": {
                "unitTests": {"covered": True, "framework": "pytest", "coverageTarget": 80},
                "integrationTests": {"covered": False, "approach": "none"},
                "antiCheating": ["Coverage reports must exceed threshold to pass CI"],
            },
            "acceptanceCriteria": {
                "happyPath": ["Given a test When action Then result"],
                "errorHandling": [],
            },
        }

    def test_validate_with_valid_ir(self, validator, valid_ir):
        """Should pass with valid IR."""
        valid, errors = validator.validate(valid_ir)

        assert valid is True
        assert errors == []

    def test_validate_missing_required_project(self, validator, valid_ir):
        """Should fail if required 'project' field is missing."""
        del valid_ir["project"]

        valid, errors = validator.validate(valid_ir)

        assert valid is False
        assert len(errors) > 0

    def test_validate_missing_required_core_features(self, validator, valid_ir):
        """Should fail if required 'coreFeatures' field is missing."""
        del valid_ir["coreFeatures"]

        valid, errors = validator.validate(valid_ir)

        assert valid is False
        assert len(errors) > 0

    def test_validate_file_not_found(self, validator, temp_dir):
        """Should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            validator.validate_file(temp_dir / "nonexistent.json")

    def test_validate_file(self, validator, temp_dir, valid_ir):
        """Should validate a file path correctly."""
        import json

        ir_file = temp_dir / "test.ir.json"
        ir_file.write_text(json.dumps(valid_ir))

        valid, errors = validator.validate_file(ir_file)

        assert valid is True
        assert errors == []
