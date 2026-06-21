Essential Paxos Claude Sonnet 4.5 — iteration 1 (early fail)
Timestamp: 2026-06-04T18:51:25

Generated spec:
- output/runtime_check/tla/essential_paxos/direct_call_claude/20260604185125/EssentialPaxos.tla
- output/runtime_check/tla/essential_paxos/direct_call_claude/20260604185125/EssentialPaxos.cfg

Results:
- compilation_check: PASS
- runtime_check: FAIL

TLC error:
  "The constant parameter Learners is not assigned a value by the configuration file."

Root cause (Table 1, Run 1): the generated .cfg omitted the Learners constant binding entirely.
The model declared Learners in CONSTANTS but did not assign it in the config file, so TLC
had no set of learner nodes to work with and exited with code 151.

This is the first of 8 iterations in the self-iteration phase (Experiment 1). The initial
prompts that produced this run were not separately archived; the final refined prompts after
all 8 iterations are in tla_eval/tasks/essential_paxos/prompts_claude/.

Archived contents:
- EssentialPaxos.tla: spec generated on iteration 1 (compiles but fails at runtime)
