---
name: ir
description: Converts a raw markdown spec into a structured spec.ir.json conforming to the Orca spec-schema-v2.json. Use when transforming any format spec (PRD, brain dump, notes) into a validated IR for Orca task decomposition.
---

# IR Spec Generator Skill

Converts raw markdown specs into validated `spec.ir.json` files conforming to `spec-schema-v2.json`.

## Core Principle: **NEVER DROP CONTENT**

Every piece of information in the source spec MUST appear in the output. The schema fields are a **semantic skeleton** for task decomposition — they are NOT a filter. Content that doesn't fit a specific field must be "stuffed" into appropriate fields.

```
┌─────────────────────────────────────────────────────────────┐
│                     SOURCE SPEC (any format)                │
│  Sections 1-15, prose, tables, code, examples, prompts    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    SCHEMA SKELETON                          │
│  project, coreFeatures, technicalApproach, testing, etc.    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼ [STUFF EXTRA CONTENT INTO FIELDS]
┌─────────────────────────────────────────────────────────────┐
│                   COMPLETE SPEC.IR.JSON                     │
│  All source content preserved, no information loss         │
└─────────────────────────────────────────────────────────────┘
```

## Translation Guide: Where Extra Content Goes

| Source Content Type | Where to Store |
|---------------------|----------------|
| Architecture/file structure | `technicalApproach.constraints` (list of constraints) OR feature description |
| CLI flags/interfaces | `technicalApproach.constraints` OR edge cases |
| Error handling tables | Edge cases per feature OR `outOfScope` (if truly out of scope) |
| Prompt templates | Feature descriptions (include actual prompt text) |
| Error scenarios | `edgeCases` array per feature |
| Examples/demos | Feature descriptions OR acceptance criteria text |
| Implementation tasks/checklists | `edgeCases` (as strings describing the task) |
| Dependencies | `technicalApproach.constraints` |
| Protocol descriptions | Feature descriptions with full detail |
| Configuration options | `technicalApproach.constraints` |
| Session/log file formats | Feature descriptions with example syntax |

**Rule:** If content doesn't map to a schema field, add it to the most relevant feature's description or edgeCases. Do NOT leave it out.

## Step-by-Step Process

### Step 1: Parse the Source Spec

Read the entire spec and identify all content sections. Create a mental inventory:
- [ ] Concept/Vision section
- [ ] Design principles/constraints
- [ ] Architecture description
- [ ] File structure (if any)
- [ ] CLI/API interface
- [ ] Error handling
- [ ] Prompt templates / message formats
- [ ] Data formats / schemas
- [ ] Examples / walkthroughs
- [ ] Testing/validation approach
- [ ] Dependencies / requirements

### Step 2: Extract Semantic Skeleton

Map to schema fields:
- `project.name` ← Title/filename
- `project.vision` ← Concept & Vision section
- `project.problemStatement` ← Problem the project solves
- `project.targetUsers` ← Who uses this
- `project.successCriteria` ← What "done" looks like
- `technicalApproach` ← Architecture, language, framework
- `coreFeatures` ← Main features (extract from prose)
- `testingStrategy` ← Testing approach
- `acceptanceCriteria` ← Project-level acceptance criteria

### Step 3: Stuff Extra Content

For each content section NOT captured in Step 2:
1. Identify the most relevant feature
2. Add to feature's `description` (for prose/detail)
3. Add to feature's `edgeCases` (for discrete items like tasks, errors)
4. Add to `technicalApproach.constraints` (for architectural items)

### Step 4: Verify Completeness (CRITICAL)

Run through this checklist before outputting:

```
COMPLETENESS CHECKLIST:
☐ All major sections from source spec are represented
☐ File structure/architecture details preserved
☐ CLI flags or interface details preserved
☐ Error handling scenarios preserved
☐ Prompt templates or message formats preserved
☐ Examples or walkthroughs preserved
☐ Implementation tasks/checklists preserved
☐ Dependencies preserved
☐ Any "Table" data converted to edge cases or constraints
☐ Any "Code" or "Example" blocks preserved in descriptions
```

**If ANY item is NOT represented, the output is incomplete. Fix it.**

### Step 5: Validate Against Schema

After generation, check:
- Required fields present: `project`, `coreFeatures.mustHave`, `technicalApproach`, `testingStrategy`, `acceptanceCriteria`
- `project.name` matches pattern `^[A-Z][a-zA-Z0-9 ]+$`
- Feature IDs match pattern `^FEAT-[0-9]+$`
- AC IDs match pattern `^FEAT-XXX/AC-[0-9]+$`
- AC criteria match pattern `^Given.*When.*Then.*$`
- Enum values are valid
- Required arrays have items

If validation fails, fix and re-output COMPLETE object (not just the fix).

## Schema Reference

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
- `description`: minLength: 10 — INCLUDE DETAIL HERE
- `edgeCases`: array of strings — PUT TASKS/ERRORS HERE
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
| constraints | array of strings — PUT ARCHITECTURAL DETAILS HERE |

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

### Completeness Example

If the source spec contains:
```
## 4. Architecture

The project has the following file structure:
├── orchestrator.py    # Main loop
├── templates/
│   ├── interrogator.txt
│   └── respondee.txt
└── README.md
```

Your output MUST include something like:
```json
{
  "coreFeatures": [{
    "id": "FEAT-001",
    "description": "Single-process orchestration with file-backed state. File structure: orchestrator.py (main loop), templates/interrogator.txt, templates/respondee.txt, README.md. Manages sequential Interrogator and Respondee pi processes.",
    ...
  }]
}
```

OR in constraints:
```json
{
  "technicalApproach": {
    "constraints": [
      "File structure: orchestrator.py, templates/interrogator.txt, templates/respondee.txt, README.md"
    ]
  }
}
```

## Anti-Drift Rules

1. **Never summarize prose** — include actual text
2. **Preserve file paths** — as constraint or in feature descriptions
3. **Preserve error tables** — as edge cases
4. **Preserve examples** — in acceptance criteria or descriptions
5. **Preserve prompts/tokens** — include actual template text
6. **Count source sections** — ensure output has comparable coverage

## Common Mistakes to Avoid

❌ **Dropping content because "it doesn't fit"**
   → ALWAYS fit it somewhere (descriptions, edgeCases, constraints)

❌ **Summarizing prose into generic statements**
   → Include the actual prose

❌ **Leaving edgeCases empty when source has error handling**
   → Convert error table to edge case strings

❌ **Skipping implementation tasks section**
   → Add as edge cases: "Task: write orchestrator.py", etc.

❌ **Truncating descriptions at 60 characters**
   → Full detail required

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