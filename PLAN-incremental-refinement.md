# Plan: Incremental Refinement for orca refine

## Problem
The current refine command regenerates the entire spec.ir.json every iteration, which:
- Requires perfect JSON syntax every time (high failure rate)
- Causes "garbage in garbage out" when API degrades
- Leads to truncated strings and JSON validation errors
- Wastes iterations regenerating content that was already correct

## Solution
Two-phase approach:
1. **Generation phase** (first stable valid IR): Full generation from source spec
2. **Refinement phase** (iterations after): Incremental surgical changes only

## Changes Needed

### 1. orca/commands/refine.py

#### State variable addition:
```python
is_generation_phase = True  # True until first stable valid IR
```

#### Prompt builder changes:
- Add `mode` parameter: "generate" or "refine"
- **generate mode**: Full generation prompt (existing behavior, simplified)
- **refine mode**: "Copy base IR, make ONLY targeted changes"

#### Prompt changes for refine mode:
```
You are refining a structured IR with INCREMENTAL CHANGES ONLY.

CRITICAL RULES:
1. Copy the base IR below COMPLETELY - do not omit any fields
2. Make ONLY the targeted changes specified below
3. Preserve all other content VERBATIM - do not regenerate or rewrite
4. Output the COMPLETE modified IR (not a patch or diff)

## BASE IR (copy completely, modify only specified sections)
[base_ir here]

## VALIDATION ERRORS TO FIX
[errors]

## CONTENT GAPS TO ADDRESS
[gaps]

Output ONLY the complete JSON IR with your changes incorporated.
```

#### Phase transition:
- After first stable valid IR → set `is_generation_phase = False`
- Subsequent iterations use refine mode with `last_good_ir` as base

### 2. Both ir SKILL.md files
- Local: .pi/skills/ir/SKILL.md
- Global: /Users/kylelampa/.pi/agent/skills/ir/SKILL.md

Add new section for incremental refinement:

```markdown
## Incremental Refinement Mode

When refining an existing spec.ir.json:

1. **COPY** the base IR completely
2. **IDENTIFY** only the sections that need changes
3. **MODIFY** only those specific sections
4. **PRESERVE** all other content verbatim
5. **OUTPUT** the complete IR (not a patch or diff)

Do NOT regenerate sections that don't need changes. The goal is surgical
edits, not full regeneration.

### Example

Base IR (partial):
```json
{
  "coreFeatures": {
    "mustHave": [
      {"id": "FEAT-001", "description": "Feature A", "edgeCases": []}
    ]
  }
}
```

Changes needed: Add edgeCases to FEAT-001

Output should include ALL features from base IR, with only edgeCases modified:
```json
{
  "coreFeatures": {
    "mustHave": [
      {"id": "FEAT-001", "description": "Feature A", "edgeCases": ["timeout handling"]}
    ]
  }
}
```
```

### 3. Keep existing safety features:
- `last_good_ir` backup (preserves last valid IR)
- Exponential backoff on retries
- Audit graceful degradation
- Last good IR restoration on max iterations

## Files to Modify
1. orca/commands/refine.py
2. .pi/skills/ir/SKILL.md
3. /Users/kylelampa/.pi/agent/skills/ir/SKILL.md

## Testing
- Run refine on a spec, verify:
  - Iteration 1 does full generation
  - Iterations 2+ do incremental changes
  - Last good IR is preserved across failures
  - Final output is complete and valid
