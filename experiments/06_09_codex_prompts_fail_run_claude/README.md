Essential Paxos Claude Sonnet 4.5 with Codex prompt (PromptX) — compilation fail
Timestamp: 2026-06-11T13:30:02

Generated spec:
- output/compilation_check/tla/essential_paxos/direct_call_claude/20260611133002/EssentialPaxos.tla
- output/compilation_check/tla/essential_paxos/direct_call_claude/20260611133002/EssentialPaxos.cfg

Results:
- compilation_check: FAIL

SANY errors:
  line 19, col 26 to col 35 of module EssentialPaxos: Unknown operator `proposalId'
  line 19, col 77 to col 86 of module EssentialPaxos: Unknown operator `proposalId'

Root cause (Experiment 2, Table 3): PromptX (Codex-tuned) defines the NextProposalNum helper
before the VARIABLES block, referencing proposalId as a forward reference. SANY rejects this.
PromptX implicitly relied on GPT-5's generation order without constraining helper placement,
so Claude consistently emitted the helper early and hit the forward-reference restriction.

This run documents the Claude + PromptX cross-model prompt-transfer failure in Experiment 2.
The symmetric failure (GPT-5 + PromptC) is documented in experiments/06_09_claude_prompts_fail_run_gpt5/.

Archived contents:
- EssentialPaxos.tla: generated (non-compiling) spec
- prompts/: Codex-tuned prompt files (PromptX) used in this run
  - direct_call.txt          (spec generation)
  - phase2_config.txt        (TLC .cfg generation)
  - phase3_invariant_implementation.txt  (invariant module generation)
