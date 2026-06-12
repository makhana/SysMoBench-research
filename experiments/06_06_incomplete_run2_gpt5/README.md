# Essential Paxos GPT-5 Run Archive

Archived at: 2026-06-06 13:13:50 Europe/Amsterdam

This folder preserves the prompt versions and SysMoBench outputs for the best GPT-5 Essential Paxos run so far.

## Model / Task

- Task: `essential_paxos`
- Method: `direct_call`
- Model: `gpt5`
- Generated spec timestamp: `20260606125903`

## Result Summary

- Compilation check: PASS
  - Output: `outputs/compilation_check_20260606125903`
  - Syntax errors: 0
  - Semantic errors: 0

- Runtime check: PASS
  - Output: `outputs/runtime_check_20260606125921`
  - TLC timed out after 600s with no violations and no deadlock

- Runtime coverage: PASS
  - Output: `outputs/runtime_coverage_20260606131002`
  - Runtime coverage score: 100.00%
  - Error actions: 0

- Action decomposition: PASS
  - Output: `outputs/action_decomposition_20260606131238`
  - Action success rate: 25/26 (96.2%)
  - Failed decomposed action: `Messages`

## Contents

- `prompts/`
  - Snapshot of current Essential Paxos prompt files.

- `outputs/`
  - Copied SysMoBench result directories for the GPT-5 generated spec.

- `logs/`
  - Terminal output pasted during the successful runtime and action-decomposition runs.

## Notes

- Generated TLA/CFG files were not manually edited.
- Prompt changes were used to guide regeneration until GPT-5 produced a spec that passed compilation, runtime check, and runtime coverage.
