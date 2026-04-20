---
name: ir
description: Converts a raw markdown spec into a structured spec.ir.json conforming to the Orca spec-schema-v2.json. Use when transforming any format spec (PRD, brain dump, notes) into a validated IR for Orca task decomposition.
---

# IR Spec Generator Skill

Converts raw markdown specs into validated `spec.ir.json` files conforming to `spec-schema-v2.json`.

## Usage

```
/ir <spec.md>
```

The skill will output a complete `spec.ir.json` file to stdout that you should save to the same directory as the input spec.

## Schema Reference

The output must conform to `spec-schema-v2.json` at `orca/data/spec-schema-v2.json` (resolved from the project root).

### Required Top-Level Fields

```json
{
  "project": { ... },
  "coreFeatures": { ... },
  "technicalApproach": { ... },
  "testingStrategy": { ... },
  "acceptanceCriteria": { ... }
}
```

### Project Object

| Field | Pattern/Type | Notes |
|-------|--------------|-------|
| name | `^[A-Z][a-zA-Z0-9 ]+$` | PascalCase |
| vision | minLength: 20 | 2-3 sentences |
| targetUsers | minLength: 10 | |
| problemStatement | minLength: 20 | |
| successCriteria | minLength: 20 | |

### Core Features

Three tiers: `mustHave` (required, min 1), `shouldHave` (optional), `niceToHave` (optional).

Each feature requires:
- `id`: Pattern `^FEAT-[0-9]+$` (e.g., FEAT-001)
- `description`: minLength: 10
- `edgeCases`: array of strings (default: [])
- `acceptanceCriteria`: object with `happyPath` and/or `errorHandling` arrays

### Acceptance Criteria Format

Each criterion object requires a feature-scoped ID in `FEAT-XXX/AC-YYY` format:
```json
{
  "id": "FEAT-001/AC-001",
  "criterion": "^Given.*When.*Then.*$"
}
```

The AC counter resets per feature (e.g., FEAT-001/AC-001, FEAT-001/AC-002, FEAT-002/AC-001, etc.).

Example: `"Given a user submits a valid email When the form is validated Then the email is accepted"`

### Technical Approach

| Field | Allowed Values |
|-------|----------------|
| language | python, typescript, javascript, go, rust, java, csharp, cpp, ruby, php, swift, kotlin, scala, bash, unknown |
| architecture | monolith, microservices, serverless, library, cli, daemon, web, mobile, desktop, embedded, unknown |
| apiStyle | rest, graphql, grpc, websocket, cli-only, none, unknown |
| deployment | local, docker, kubernetes, cloud-functions, vm, serverless, static, unknown |

### Testing Strategy

```json
{
  "unitTests": { "covered": boolean, "framework": string, "coverageTarget": 0-100 },
  "integrationTests": { "covered": boolean, "approach": "real-instances|mocks|test-containers|none" },
  "e2eTests": { "covered": boolean, "tool": string, "keyJourneys": array },
  "antiCheating": array of strings
}
```

## Output Format

When invoked, analyze the provided markdown spec and output a COMPLETE, VALID `spec.ir.json` object. Do not truncate, summarize, or leave placeholders.

### Output Structure Example

```json
{
  "project": {
    "name": "ProjectName",
    "vision": "...",
    "targetUsers": "...",
    "problemStatement": "...",
    "successCriteria": "..."
  },
  "coreFeatures": {
    "mustHave": [
      {
        "id": "FEAT-001",
        "description": "Feature description...",
        "edgeCases": ["Edge case 1", "Edge case 2"],
        "acceptanceCriteria": {
          "happyPath": [
            { "id": "FEAT-001/AC-001", "criterion": "Given... When... Then..." }
          ],
          "errorHandling": [
            { "id": "FEAT-001/AC-002", "criterion": "Given... When... Then..." }
          ]
        }
      }
    ],
    "shouldHave": [],
    "niceToHave": []
  },
  "technicalApproach": {
    "language": "python",
    "architecture": "cli",
    "framework": "none",
    "apiStyle": "cli-only",
    "database": "none",
    "deployment": "local",
    "constraints": []
  },
  "testingStrategy": {
    "unitTests": { "covered": true, "framework": "pytest", "coverageTarget": 80 },
    "integrationTests": { "covered": false, "approach": "none" },
    "e2eTests": { "covered": false },
    "antiCheating": []
  },
  "acceptanceCriteria": {
    "happyPath": ["Given... When... Then..."],
    "errorHandling": [],
    "performance": [],
    "security": []
  },
  "outOfScope": [],
  "metadata": {
    "version": "1.0",
    "created": "2026-04-20"
  }
}
```

## Tips for Good IR Generation

1. **Extract concrete features** - Don't just copy text; identify discrete, testable features
2. **Specific edge cases** - List actual edge cases, not generic ones
3. **Given/When/Then criteria** - Write specific, testable acceptance criteria
4. **Tier appropriately** - Features that break the core functionality are `mustHave`
5. **Consistent IDs** - Use `FEAT-XXX/AC-YYY` format for ACs, scoped per feature. FEAT IDs are global, but AC counters reset per feature.
6. **Anti-cheating measures** - Consider how to verify tests aren't trivial/fake

## Validation After Generation

After outputting `spec.ir.json`, validate against the schema:
- Required fields present
- Patterns match (PascalCase names, `FEAT-[0-9]+` and `FEAT-XXX/AC-[0-9]+` IDs, Given/When/Then)
- Enum values valid
- Arrays have correct item types

If validation fails, fix and re-output the complete corrected object.

## Save the Output

After generating a valid `spec.ir.json`, write it to the same directory as the input spec:
```
spec.ir.json
```
