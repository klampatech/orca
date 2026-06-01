# IR Generation & Schema Revision Plan

**Date:** 2026-04-25
**Status:** Draft
**Goal:** Fix degrading IR generation quality and schema limitations

---

## Problem Summary

### Root Causes Identified

1. **Schema Mismatch** — `spec-schema-v2.json` is designed for **application specs** (features → tasks), not **tool specs** (system prompts, protocols, file formats)
2. **No Validation Gate** — The `refine.py` loop keeps retrying without stopping when validation consistently fails
3. **Single-Pass Generation** — Tries to output complete IR in one response → truncation
4. **Content Loss** — System prompts, conversation protocols, delimiter formats not representable in schema

### Evidence from Logs

| Issue | Observation |
|-------|-------------|
| Schema mismatch | `socratic-spec-refiner.md` has 15 sections; schema only covers ~6 |
| No validation gate | 12 consecutive generation attempts, quality degrading |
| Truncation | All responses at 2000 tokens (limit), content progressively lost |
| Empty response | Run 6 returned 0 tokens — model "gave up" |

---

## Proposed Changes

### 1. Schema Evolution (spec-schema-v2.json)

**Problem:** Schema enforces Given/When/Then ACs and feature-centric structure that doesn't fit tool specs.

**Solution:** Add optional extension fields for tool specs while keeping core schema intact.

```json
{
  "project": { ... },           // existing
  "coreFeatures": { ... },      // existing, optional for tool specs
  "technicalApproach": { ... }, // existing
  
  // NEW: Extensions for tool specs
  "systemPrompts": {
    "type": "object",
    "description": "System prompt templates for multi-agent tools",
    "properties": {
      "interrogator": { "type": "string" },
      "respondee": { "type": "string" },
      "other": { "type": "object", "additionalProperties": { "type": "string" } }
    }
  },
  
  "conversationProtocol": {
    "type": "object",
    "description": "Protocol for multi-turn conversations",
    "properties": {
      "fileFormat": { "type": "string" },
      "delimiter": { "type": "string" },
      "turnTypes": { "type": "array", "items": { "type": "string" } },
      "outputSections": { "type": "array", "items": { "type": "string" } }
    }
  },
  
  "fileStructure": {
    "type": "array",
    "items": {
      "type": "object",
      "properties": {
        "path": { "type": "string" },
        "purpose": { "type": "string" }
      }
    }
  },
  
  // Existing sections remain...
  "testingStrategy": { ... },
  "acceptanceCriteria": { ... }
}
```

**Key changes:**
- `systemPrompts` can hold Interrogator/Respondee prompts as-is
- `conversationProtocol` captures file formats, delimiters, turn structure
- `fileStructure` captures directory layout (currently lost)
- `coreFeatures` remains but is now **optional** for tool specs (mustHave minItems: 0)

### 2. Validation Gate in Refine Loop

**Problem:** `refine.py` keeps retrying even when validation consistently fails.

**Solution:** Add "give up" logic after N consecutive failures with same errors.

```python
# In handle_refine():
if consecutive_validation_failures >= 3:
    # Check if errors are schema-related (can't fix with retry)
    schema_errors = [e for e in errors if is_schema_limitation(e)]
    if len(schema_errors) > len(errors) * 0.5:
        print("✗ Schema limitations prevent valid output")
        print("  Consider: schema updates, source spec format, alternative approach")
        break
```

**Pattern:** If >50% of errors are about schema limitations (missing fields, pattern mismatches), stop and suggest schema revision.

### 3. Incremental Generation (Two-Phase)

**Problem:** Single-pass generation truncates for large specs.

**Solution:** Generate in phases, validate after each.

**Phase 1: Core skeleton** — project, technicalApproach
**Phase 2: Features** — coreFeatures (can be multiple iterations)
**Phase 3: Validation & completion** — acceptanceCriteria, edge cases

**Implementation approach:**

Option A: **Chunk the schema** — Ask LLM to output in sections, merge
Option B: **Accept truncation** — Better to have partial valid IR than none
Option C: **Streaming JSON** — Use JSONL output mode for progressive parsing

**Recommendation:** Option B with better truncation handling — if output is truncated, treat it as partial and refine from there.

### 4. Update IR Skill Prompt

Update `SKILL.md` to:
- Handle tool specs (not just application specs)
- Preserve system prompts verbatim
- Handle `conversationProtocol` and `fileStructure` fields
- Accept "tool" as a valid project type

---

## Implementation Plan

### Phase 1: Schema Updates (Day 1)

1. Edit `/Users/kylelampa/Development/orca/orca/data/spec-schema-v2.json`
   - Add `systemPrompts` object
   - Add `conversationProtocol` object
   - Add `fileStructure` array
   - Make `coreFeatures.mustHave` have `minItems: 0` (optional for tools)
   - Add `"tool"` as valid architecture type

2. Edit `/Users/kylelampa/Development/orca/orca/utils/validator.py`
   - Update enumeration lists to include tool-related values
   - Add validation for new fields
   - Relax validation for tool specs (no AC requirements if systemPrompts exist)

### Phase 2: Validation Gate (Day 1)

1. Edit `/Users/kylelampa/Development/orca/orca/commands/refine.py`
   - Track consecutive validation failures
   - Detect schema-related vs content-related errors
   - Add "give up" logic with helpful message
   - Log when schema limitations cause failure

### Phase 3: IR Skill Update (Day 2)

1. Edit `/Users/kylelampa/.pi/agent/skills/ir/SKILL.md`
   - Add guidance for tool specs
   - Explain new fields (systemPrompts, conversationProtocol, fileStructure)
   - Provide examples for tool spec conversion

---

## Expected Outcomes

| Metric | Before | After |
|--------|--------|-------|
| Generation success rate | ~70% (degrading) | >90% (stable) |
| Content preservation | ~60% | >90% |
| Empty response rate | 8% (1/12) | 0% |
| Validation failures before giving up | unlimited | max 3 |
| Schema coverage for tool specs | 40% | 95% |

---

## Files to Modify

1. `/Users/kylelampa/Development/orca/orca/data/spec-schema-v2.json`
2. `/Users/kylelampa/Development/orca/orca/utils/validator.py`
3. `/Users/kylelampa/Development/orca/orca/commands/refine.py`
4. `/Users/kylelampa/.pi/agent/skills/ir/SKILL.md`

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Schema changes break existing valid IRs | Add migration helpers, version field |
| Validation relaxation allows bad IRs | Keep strict validation for application specs |
| Two-phase is slower | Cache intermediate results, allow resume |

---

## Open Questions

1. Should we version the schema? (`"schemaVersion": "2.1"`)
2. How to handle mixed specs (app + tool hybrid)?
3. Should tool specs have different acceptance criteria format?

---

## Next Steps

1. Review this plan with stakeholder
2. Implement Phase 1 (schema updates)
3. Test on `socratic-spec-refiner.md` specifically
4. Iterate based on results