Essential Paxos GPT-5 snapshot
Timestamp: 2026-06-08 18:31:07 Europe/Amsterdam

Purpose:
- Preserve the current prompt versions before another prompt-improvement pass.
- Preserve the current GPT-5 result artifacts, including the latest transition validation
  and invariant verification attempts.

Prompts:
- prompts/direct_call.txt
- prompts/phase2_config.txt
- prompts/phase3_invariant_implementation.txt

Result artifacts:
- results/compilation_check_20260606125903
- results/runtime_check_20260606125921
- results/runtime_coverage_20260606131002
- results/action_decomposition_20260606131238
- results/transition_validation_20260608_173711_20260606125903
- results/invariant_verification_20260608175253

Known status before this prompt-improvement pass:
- compilation_check: pass
- runtime_check: pass
- runtime_coverage: pass
- action_decomposition: 25/26
- transition_validation: SysMoBench metric failed because the harness wrote tv_summary.json
  instead of the expected tv_results.json/tlc_results.json; raw TV scores were mixed.
- invariant_verification: 3/4 invariants passed; Validity failed.
