# SysMoBench

SysMoBench is a benchmark for evaluating AI on formally modeling complex real-world systems. It targets TLA+, the de facto specification language for concurrent and distributed systems, and automates four kinds of evaluation: syntax checking with SANY, runtime model checking with TLC, transition validation against captured system traces, and verification of expert-written invariants. Eleven systems are included, ranging from kernel-level synchronization primitives in the Asterinas operating system to industrially deployed consensus implementations such as etcd Raft, Redis Raft, and Xline CURP.

The corresponding paper appears at ICLR 2026: ["SysMoBench: Evaluating AI on Formally Modeling Complex Real-World Systems"](https://openreview.net/forum?id=SAeaTz8YoM). Up-to-date scores are at [sysmobench.com](https://sysmobench.com).

## Highlights

- **End-to-end automation.** Generation, compilation, model checking, transition validation against real traces, and invariant verification all run as a single pipeline, with no human in the loop.
- **Real systems with real traces.** Each task is built around the upstream system's actual source code, paired with an instrumentation harness that emits NDJSON traces from a real execution and a hand-written invariant template.

## Setup

Required on the host:

- Python 3.8+
- Java 11+ (for SANY and TLC, downloaded by the setup script below)
- Docker (for the Asterinas-based harnesses: `spin`, `mutex`, `rwmutex`)
- Go 1.26+ (for the `etcd` harness)
- Maven and a JDK build chain (for the `zookeeper` and `redisraft` harnesses)
- A coding-agent CLI — either [`claude-code`](https://github.com/anthropics/claude-code) or [`codex`](https://github.com/openai/codex) — used by transition validation and by the agent-driven invariant translator

Then install (a virtual environment is recommended on Python 3.12+ hosts that enforce PEP 668):

```
git clone https://github.com/specula-org/SysMoBench.git
cd SysMoBench
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
sysmobench-setup
```

Add the models you intend to evaluate to `config/models.yaml` (the file ships with example entries) and export the corresponding API keys.

Alternatively, pull the prebuilt image (published per release tag):

```
docker pull ghcr.io/specula-org/sysmobench:latest
docker run --rm -it -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY ghcr.io/specula-org/sysmobench:latest
```

Or build it locally:

```
docker build -t sysmobench .
docker run --rm -it -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY sysmobench
```

The image bundles Python, Java, Maven, Go, and the `claude-code` CLI. Asterinas-based tasks (`spin`, `mutex`, `rwmutex`, `ringbuffer`) launch their own containers — pass `-v /var/run/docker.sock:/var/run/docker.sock` to forward the host Docker socket when running those.

## Running

A single (system, model, metric) cell:

```
sysmobench --task spin --method direct_call --model claude --metric compilation_check
```

A full sweep across all 11 systems:

```
python3 scripts/run_batch_experiment.py --all --model claude
```

See [`docs/Usage.md`](docs/Usage.md) for details.

## Project: Essential Paxos Extension

This fork adds a task for Cocagne's single-decree Essential Paxos implementation (`paxos/essential.py`, pinned at commit `cf3b5a2`). The task is intentionally scoped to the 202-line `essential.py` core: proposers, acceptors, learners, four Paxos message kinds, majority quorums, and single-decree consensus only.

Important project additions:

- `tla_eval/tasks/essential_paxos/task.yaml` declares the SysMoBench task.
- `tla_eval/tasks/essential_paxos/prompts/` contains the active prompt set.
- `scripts/harness/essential_paxos/` contains the Python trace harness and runner.
- `data/invariant_templates/essential_paxos/invariants.yaml` defines Agreement, Validity, Stability, and PromiseMonotonic templates.
- `artifacts/essential_paxos/traces/` contains generated NDJSON traces for happy path, dueling proposers, message loss, and late promise scenarios.

The harness leaves the upstream Paxos source unchanged. It uses an external messenger, deterministic trace scenarios, sentinel proposal-id initialization for Python 3 compatibility, and a `TracedLearner` wrapper to avoid Python 2-era `None` proposal comparisons while preserving the intended proposal-ordering semantics.

### Essential Paxos Experiment Commands

In this project we used two LLMs. OpenAIs Codex and GPT5 and Anthropics Claude Sonet 4.5 and Claude Code. To run the project activate the environment and export model keys before running experiments:

```
source .venv/bin/activate
export OPENAI_API_KEY="..."      # used for gpt-5
export ANTHROPIC_API_KEY="..."   # used for claude
```


Compile: generate `EssentialPaxos.tla`/`.cfg` and check that SANY accepts the specification.

```
sysmobench --task essential_paxos --method direct_call --model gpt5 --metric compilation_check
```

Runtime: run TLC on the generated specification and configuration, reporting whether model checking completes or reaches the timeout without violations.

```
sysmobench --task essential_paxos --method direct_call --model gpt5 \
  --metric runtime_check \
  --spec-file output/compilation_check/tla/essential_paxos/direct_call_gpt5/<timestamp>/EssentialPaxos.tla \
  --config-file output/compilation_check/tla/essential_paxos/direct_call_gpt5/<timestamp>/EssentialPaxos.cfg \
  --tlc-timeout 600
```

Transition validation: compare each captured Python trace window against the corresponding TLA+ action.

```
sysmobench --task essential_paxos --method direct_call --model gpt5 \
  --metric transition_validation \
  --spec-file output/compilation_check/tla/essential_paxos/direct_call_gpt5/<timestamp>/EssentialPaxos.tla \
  --config-file output/compilation_check/tla/essential_paxos/direct_call_gpt5/<timestamp>/EssentialPaxos.cfg \
  --tv-agent codex --tv-model gpt-5 --tv-budget 5 --tv-timeout 3600 --yes
```

Invariant verification: translate the four expert templates and check them with TLC.

```
sysmobench --task essential_paxos --method direct_call --model gpt5 \
  --metric invariant_verification \
  --spec-file output/compilation_check/tla/essential_paxos/direct_call_gpt5/<timestamp>/EssentialPaxos.tla \
  --config-file output/compilation_check/tla/essential_paxos/direct_call_gpt5/<timestamp>/EssentialPaxos.cfg \
  --inv-translator-type codex \
  --tlc-timeout 600
```

The report table columns map directly to these stages: `Compile` and `Runtime` come from each stage's `result.json`, `TV rate` is the passed-window fraction in `tv_results.json` or the TV final report, and `Invariants` is the number of the four templates that TLC verifies successfully.

Claude-oriented prompt experiments use the same `sysmobench` commands with `--model claude` when Anthropic credentials are configured. Cross-model prompt-transfer experiments were run by swapping the prompt directory before generation and then restoring it afterwards.

### Essential Paxos Results

Stable project archives are under `experiments/`:

- `experiments/06_06_incomplete_run2_gpt5/`: GPT-5 run that passed compilation/runtime/coverage but was not the final full pass.
- `experiments/06_08_imperfect_run3_gpt5/`: GPT-5 intermediate run with mixed transition validation and 3/4 invariants.
- `experiments/06_08_success_run4_gpt5/`: final GPT-5/Codex run; compilation, runtime, transition validation, and invariant verification passed, with 61/61 TV windows and 4/4 invariants.
- `experiments/06_09_claude_prompts_fail_run_gpt5/`: GPT-5 rerun using the then-current Claude-oriented prompts; compilation failed, documenting the prompt-transfer failure.

Raw timestamped SysMoBench outputs are written to `output/<metric>/tla/essential_paxos/direct_call_<model>/`. Transition-validation workspaces and reports are written to `tv-workspaces/`, with final summaries in `reports/final_report.md` and machine-readable scores in `reports/tv_results.json` when available. Large TLC `states/` directories are generated during model checking and may be deleted without losing the archived JSON summaries. Raw outputs, TV workspaces, cloned artifacts, and `states/` directories are ignored by git because they can grow to many gigabytes.

## Tasks

`sysmobench --list-tasks` enumerates the live set.

| System | Type |
|---|---|
| `spin`, `mutex`, `rwmutex` | Asterinas OS synchronization primitives |
| `ringbuffer` | Concurrent queue |
| `etcd`, `redisraft` | Raft consensus |
| `curp` | Xline CURP replication |
| `zookeeper` | Distributed coordination |
| `dqueue`, `locksvc`, `raftkvs` | PGo-compiled distributed systems |
| `essential_paxos` | Single-decree Paxos consensus (Team 3 extension) |

## Metrics

| Stage | What it measures |
|---|---|
| Syntax | The spec compiles (`compilation_check`, `action_decomposition`) |
| Runtime | TLC can execute it (`runtime_check`, `coverage`, `runtime_coverage`) |
| Transition validation | Per-action conformance to captured system traces (`transition_validation`) |
| Invariant verification | The spec satisfies expert invariants (`invariant_verification`) |

`sysmobench --list-metrics` gives the full catalog. Canonical aggregate weights are 0.15, 0.15, 0.35, and 0.35 for the four stages above.

## Leaderboard

Up-to-date scores live at [sysmobench.com](https://sysmobench.com).

## Adding a new system

See [`docs/add_new_system.md`](docs/add_new_system.md). A system is declared by `tla_eval/tasks/<name>/task.yaml`, paired with prompts, an instrumentation harness, and an invariant template; once those pieces are in place the rest of the pipeline picks the system up automatically.

## Citation

```bibtex
@inproceedings{cheng2026sysmobench,
  title     = {SysMoBench: Evaluating AI on Formally Modeling Complex Real-World Systems},
  author    = {Cheng, Qian and Tang, Ruize and Ma, Emilie and Hackett, Finn and
               He, Peiyang and Su, Yiming and Beschastnikh, Ivan and Huang, Yu and
               Ma, Xiaoxing and Xu, Tianyin},
  booktitle = {International Conference on Learning Representations (ICLR)},
  year      = {2026},
  url       = {https://arxiv.org/abs/2509.23130}
}
```

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
