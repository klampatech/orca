# Schema Gap Analysis: `goal-schema.json` → `spec-schema-v2.json`

**Date:** 2026-04-20  
**Purpose:** Document structural changes needed to support Orca task decomposition from IR  

---

## Overview

The original `goal-schema.json` (from `agate-ir-validator`) was designed to validate well-formed GOAL IR. The `spec-schema-v2.json` extends it to support Orca's task decomposition, which requires **per-feature acceptance criteria** to create granular, independently claimable tasks.

---

## Gap Summary

| Gap | Original Schema | Needed for Decompose |
|-----|-----------------|----------------------|
| Per-feature ACs | ❌ Flat project-level arrays | ✅ Embedded in each feature |
| AC ID tracking | ❌ No ID on criteria | ✅ `AC-XXX` ID per criterion |
| AC format | ❌ Plain strings | ✅ `{ id, criterion }` objects |
| Decompose instructions | ❌ None | ✅ In schema description fields |

---

## Detailed Gap: `acceptanceCriteria` Placement

### Original: Project-Level Only

```json
"acceptanceCriteria": {
  "happyPath": [
    "Given valid credentials When POST /login Then returns 200 with JWT..."
  ],
  "errorHandling": [...]
}
```

Validator regex-scanned for `FEAT-XXX` in strings to associate criteria with features — unreliable.

### New: Per-Feature + Project-Level

```json
"coreFeatures": {
  "mustHave": [
    {
      "id": "FEAT-001",
      "description": "POST /login endpoint...",
      "edgeCases": [...],
      "acceptanceCriteria": {
        "happyPath": [
          {
            "id": "FEAT-001/AC-001",
            "criterion": "Given valid credentials When POST /login Then returns 200 with JWT access + refresh token"
          }
        ],
        "errorHandling": [
          {
            "id": "FEAT-001/AC-002",
            "criterion": "Given invalid credentials When POST /login Then returns 401 and no token"
          }
        ]
      }
    }
  ]
}
```

**Why ID per criterion?** Task descriptions will embed `FEAT-001/AC-001/edge-002` for traceability. The ID format is: `FEAT-XXX/AC-YYY` for acceptance criteria, `FEAT-XXX/EC-YYY` for edge cases.

---

## Task Hierarchy (How Schema Maps to Tasks)

Given this IR structure:

```
FEAT-001 (mustHave, P10)
├── edgeCases: ["invalid credentials", "rate limiting"]
├── acceptanceCriteria.happyPath: [AC-001, AC-002]
└── acceptanceCriteria.errorHandling: [AC-003]
```

Decompose creates:

```
FEAT-001 [parent task, P10]
├── FEAT-001/AC-001 [child, P8] — happy path scenario
│   ├── FEAT-001/AC-001/EC-001 [grandchild, P6] — edge: invalid credentials
│   └── FEAT-001/AC-001/EC-002 [grandchild, P6] — edge: rate limiting
├── FEAT-001/AC-002 [child, P8] — happy path scenario
├── FEAT-001/AC-003 [child, P8] — error handling scenario
```

---

## Edge Case Handling

Edge cases are still plain strings (no structural change needed):

```json
"edgeCases": [
  "invalid credentials returns 401",
  "account locked returns 423"
]
```

They generate grandchild tasks under their parent acceptance criterion. Edge cases don't get their own ID format — they're referenced by their zero-indexed position in the edgeCases array if needed.

---

## Project-Level `acceptanceCriteria`

Retained for holistic validation purposes (e.g., end-to-end scenarios that span multiple features) but annotated as **not used for task decomposition**. The decompose command reads only from `coreFeatures[].acceptanceCriteria`.

```json
"acceptanceCriteria": {
  "description": "Project-level acceptance criteria — holistic validation, NOT used for task decomposition.",
  "happyPath": [...],
  "errorHandling": [...]
}
```

---

## What the pi Skill Must Emit

The IR generation skill must produce JSON conforming to `spec-schema-v2.json`, specifically:

1. **`coreFeatures.mustHave[].acceptanceCriteria`** — required, must have at least one happy path AC per feature
2. **`coreFeatures[].acceptanceCriteria[].id`** — format `FEAT-XXX/AC-YYY`
3. **`coreFeatures[].acceptanceCriteria[].criterion`** — must match `Given...When...Then...` pattern

---

## Validator Changes Needed

The existing `validator.py` validates against the old schema. For v2, it needs:

1. **Schema update** — replace `goal-schema.json` with `spec-schema-v2.json`
2. **Per-feature AC validation** — check that each feature in `mustHave`/`shouldHave`/`niceToHave` has an `acceptanceCriteria` object
3. **AC ID format validation** — `FEAT-XXX/AC-YYY` pattern
4. **Given/When/Then format** — on `criterion` field within AC objects

The validator's existing cross-reference check (scanning flat project-level AC arrays for FEAT-XXX) can be deprecated in favor of the per-feature structure.

---

## Files

| File | Changes |
|------|---------|
| `spec-schema-v2.json` | New schema with per-feature ACs |
| `goal-schema.json` | Original, to be replaced |
| `validator.py` | Update to validate new schema fields |
| `sample-goal.ir.json` | Update example to use new per-feature AC structure |

---

## Example: Valid spec.ir.json (v2 format)

```json
{
  "project": {
    "name": "BenfordFingerprint",
    "vision": "A web service and API that detects fake numerical claims in articles using Benford's Law statistical analysis.",
    "targetUsers": "Journalists, editors, AI content moderation pipelines",
    "problemStatement": "AI-generated content often includes plausible-sounding but fabricated statistics that pass human review.",
    "successCriteria": "Statistical anomalies in numerical data are flagged with >80% accuracy on datasets >100 numbers."
  },
  "coreFeatures": {
    "mustHave": [
      {
        "id": "FEAT-001",
        "description": "Number extraction from raw text — extract all significant numerical values",
        "edgeCases": [
          "No numbers in text returns empty list",
          "Currency symbols with spaces parsed correctly",
          "Scientific notation handled"
        ],
        "acceptanceCriteria": {
          "happyPath": [
            {
              "id": "FEAT-001/AC-001",
              "criterion": "Given 'The company has 1,234 employees' When extract_numbers is called Then returns [1234]"
            },
            {
              "id": "FEAT-001/AC-002",
              "criterion": "Given '$4.2 million' When extract_numbers is called Then returns [4200000]"
            }
          ],
          "errorHandling": [
            {
              "id": "FEAT-001/AC-003",
              "criterion": "Given empty string When extract_numbers is called Then returns empty list without error"
            }
          ]
        }
      },
      {
        "id": "FEAT-002",
        "description": "Benford distribution analysis — compute chi-squared and MAD against expected distribution",
        "edgeCases": [
          "Fewer than 30 numbers returns warning",
          "All same digit (e.g. all 1s) produces extreme MAD"
        ],
        "acceptanceCriteria": {
          "happyPath": [
            {
              "id": "FEAT-002/AC-001",
              "criterion": "Given US census county populations (known Benford dataset) When analyze is called Then p-value > 0.05"
            }
          ],
          "errorHandling": [
            {
              "id": "FEAT-002/AC-002",
              "criterion": "Given fewer than 30 numbers When analyze is called Then returns warning in result"
            }
          ]
        }
      }
    ]
  },
  "technicalApproach": {
    "language": "python",
    "architecture": "web",
    "framework": "fastapi",
    "apiStyle": "rest",
    "database": "none",
    "deployment": "docker"
  },
  "testingStrategy": {
    "unitTests": { "covered": true, "framework": "pytest", "coverageTarget": 85 },
    "integrationTests": { "covered": false }
  },
  "outOfScope": ["Second-digit analysis", "PDF parsing"],
  "metadata": { "version": "1.0.0", "created": "2026-04-20" }
}
```
