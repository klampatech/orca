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
        """Should fail if required project field is missing."""
        del valid_ir["project"]

        valid, errors = validator.validate(valid_ir)

        assert valid is False
        assert len(errors) > 0

    def test_validate_missing_required_core_features(self, validator, valid_ir):
        """Should fail if required coreFeatures field is missing."""
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

    def test_validate_language_with_version(self, validator):
        """Should accept language with version like Python 3.11+."""
        ir = {
            "project": {
                "name": "Test",
                "vision": "Test project with versioned language that needs at least 50 chars",
                "targetUsers": "developers",
                "problemStatement": "testing",
                "successCriteria": "pass"
            },
            "coreFeatures": {
                "mustHave": [
                    {
                        "id": "FEAT-001",
                        "description": "Feature with versioned language",
                        "edgeCases": ["test"],
                        "acceptanceCriteria": {
                            "happyPath": [{"id": "FEAT-001/AC-001", "criterion": "Given test When action Then result"}]
                        }
                    },
                    {
                        "id": "FEAT-002",
                        "description": "Second feature for completeness",
                        "edgeCases": ["test"],
                        "acceptanceCriteria": {
                            "happyPath": [{"id": "FEAT-002/AC-001", "criterion": "Given test2 When action2 Then result2"}]
                        }
                    },
                    {
                        "id": "FEAT-003",
                        "description": "Third feature for completeness check",
                        "edgeCases": ["test"],
                        "acceptanceCriteria": {
                            "happyPath": [{"id": "FEAT-003/AC-001", "criterion": "Given test3 When action3 Then result3"}]
                        }
                    }
                ]
            },
            "technicalApproach": {
                "language": "Python 3.11+",
                "architecture": "monolith"
            },
            "testingStrategy": {
                "unitTests": {"covered": True},
                "integrationTests": {"covered": True},
                "antiCheating": ["test"]
            },
            "acceptanceCriteria": {"happyPath": [], "errorHandling": []}
        }
        valid, errors = validator.validate(ir)
        assert valid is True

    def test_validate_architecture_descriptive(self, validator):
        """Should accept descriptive architecture strings."""
        ir = {
            "project": {
                "name": "Test",
                "vision": "Test project with descriptive architecture string for validation",
                "targetUsers": "developers",
                "problemStatement": "testing",
                "successCriteria": "pass"
            },
            "coreFeatures": {
                "mustHave": [
                    {
                        "id": "FEAT-001",
                        "description": "Feature with descriptive architecture",
                        "edgeCases": ["test"],
                        "acceptanceCriteria": {
                            "happyPath": [{"id": "FEAT-001/AC-001", "criterion": "Given test When action Then result"}]
                        }
                    },
                    {
                        "id": "FEAT-002",
                        "description": "Second feature for completeness",
                        "edgeCases": ["test"],
                        "acceptanceCriteria": {
                            "happyPath": [{"id": "FEAT-002/AC-001", "criterion": "Given test2 When action2 Then result2"}]
                        }
                    },
                    {
                        "id": "FEAT-003",
                        "description": "Third feature for completeness check",
                        "edgeCases": ["test"],
                        "acceptanceCriteria": {
                            "happyPath": [{"id": "FEAT-003/AC-001", "criterion": "Given test3 When action3 Then result3"}]
                        }
                    }
                ]
            },
            "technicalApproach": {
                "language": "python",
                "architecture": "Single-process orchestration with shell-pipe architecture to pi CLI"
            },
            "testingStrategy": {
                "unitTests": {"covered": True},
                "integrationTests": {"covered": True},
                "antiCheating": ["test"]
            },
            "acceptanceCriteria": {"happyPath": [], "errorHandling": []}
        }
        valid, errors = validator.validate(ir)
        assert valid is True

    def test_validate_architecture_pipeline(self, validator):
        """Should accept pipeline-like architectures."""
        ir = {
            "project": {
                "name": "Test",
                "vision": "Test project with pipeline architecture string for validation",
                "targetUsers": "developers",
                "problemStatement": "testing",
                "successCriteria": "pass"
            },
            "coreFeatures": {
                "mustHave": [
                    {
                        "id": "FEAT-001",
                        "description": "Feature with pipeline architecture",
                        "edgeCases": ["test"],
                        "acceptanceCriteria": {
                            "happyPath": [{"id": "FEAT-001/AC-001", "criterion": "Given test When action Then result"}]
                        }
                    },
                    {
                        "id": "FEAT-002",
                        "description": "Second feature for completeness",
                        "edgeCases": ["test"],
                        "acceptanceCriteria": {
                            "happyPath": [{"id": "FEAT-002/AC-001", "criterion": "Given test2 When action2 Then result2"}]
                        }
                    },
                    {
                        "id": "FEAT-003",
                        "description": "Third feature for completeness check",
                        "edgeCases": ["test"],
                        "acceptanceCriteria": {
                            "happyPath": [{"id": "FEAT-003/AC-001", "criterion": "Given test3 When action3 Then result3"}]
                        }
                    }
                ]
            },
            "technicalApproach": {
                "language": "python",
                "architecture": "Sequential pipeline orchestrating pi CLI invocations"
            },
            "testingStrategy": {
                "unitTests": {"covered": True},
                "integrationTests": {"covered": True},
                "antiCheating": ["test"]
            },
            "acceptanceCriteria": {"happyPath": [], "errorHandling": []}
        }
        valid, errors = validator.validate(ir)
        assert valid is True

    def test_validate_anti_cheating_missing(self, validator):
        """Should warn when anti-cheating measures are missing for multi-feature projects."""
        ir = {
            "project": {
                "name": "Test",
                "vision": "Test project",
                "targetUsers": "developers",
                "problemStatement": "testing",
                "successCriteria": "pass"
            },
            "coreFeatures": {
                "mustHave": [
                    {
                        "id": "FEAT-001",
                        "description": "First feature",
                        "edgeCases": ["test"],
                        "acceptanceCriteria": {
                            "happyPath": [{"id": "FEAT-001/AC-001", "criterion": "Given test When action Then result"}]
                        }
                    },
                    {
                        "id": "FEAT-002",
                        "description": "Second feature",
                        "edgeCases": ["test"],
                        "acceptanceCriteria": {
                            "happyPath": [{"id": "FEAT-002/AC-001", "criterion": "Given test2 When action2 Then result2"}]
                        }
                    },
                    {
                        "id": "FEAT-003",
                        "description": "Third feature",
                        "edgeCases": ["test"],
                        "acceptanceCriteria": {
                            "happyPath": [{"id": "FEAT-003/AC-001", "criterion": "Given test3 When action3 Then result3"}]
                        }
                    }
                ]
            },
            "technicalApproach": {
                "language": "python",
                "architecture": "monolith"
            },
            "testingStrategy": {
                "unitTests": {"covered": True},
                "integrationTests": {"covered": True},
                "e2eTests": {"covered": True}
            },
            "acceptanceCriteria": {"happyPath": [], "errorHandling": []}
        }
        valid, errors = validator.validate(ir)
        # Should have anti-cheating warning
        error_fields = [e.field for e in errors]
        assert "testingStrategy.antiCheating" in error_fields