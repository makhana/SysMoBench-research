Essential Paxos Claude Sonnet 4.5 — final success snapshot
Timestamp: 2026-06-08T18:04:11

Generated spec:
- output/runtime_check/tla/essential_paxos/direct_call_claude/20260608180411/EssentialPaxos.tla
- output/runtime_check/tla/essential_paxos/direct_call_claude/20260608180411/EssentialPaxos.cfg

Passing results:
- compilation_check: PASS
- runtime_check: PASS (1,502,755 states explored, ~26 s)
- transition_validation: PASS, 48/61 windows (78.7%)
- invariant_verification: PASS, 4/4 invariants (Agreement, Validity, Stability, PromiseMonotonic)

This is the final output after 8 iterative refinement rounds (Experiment 1, Table 1).
TV workspace: tv-workspaces/20260608_181119_20260608180411/

Archived contents:
- EssentialPaxos.tla: final passing specification
- prompts/: Claude-tuned prompt files after all 8 iterations
  - direct_call.txt          (spec generation)
  - phase2_config.txt        (TLC .cfg generation)
  - phase3_invariant_implementation.txt  (invariant module generation)
