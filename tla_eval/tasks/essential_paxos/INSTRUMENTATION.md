# essential_paxos Harness Instrumentation

Category A single-decree Paxos trace harness for `cocagne/paxos` at upstream
commit `cf3b5a2bf6ece39d2432b7ebfe1efb2e232bc2df`.

## Layout

- Upstream copy: `artifacts/essential_paxos/paxos/`
- Source patch: `scripts/harness/essential_paxos/instrumentation.patch`
- Trace overlay: `scripts/harness/essential_paxos/tla_trace.py`
- Scenario driver: `scripts/harness/essential_paxos/run.py`
- Structural validator: `scripts/harness/essential_paxos/validate_traces.py`
- Orchestrator: `scripts/harness/essential_paxos/run.sh`

`apply.sh` copies `tla_trace.py` into the upstream package and applies the
source patch idempotently. It also mirrors this guide and an artifact-level
wrapper into `artifacts/essential_paxos/`.

## Source Instrumentation

After `apply.sh`, trace scopes are inside the actual role methods:

| Source location | Event | Capture point |
| --- | --- | --- |
| `paxos/essential.py:81` | `Prepare` | Around `Proposer.prepare` mutations and Prepare broadcast |
| `paxos/essential.py:98` | `HandlePromise` | Around `Proposer.recv_promise`, including ignored messages |
| `paxos/essential.py:135` | `HandlePrepare` | Around `Acceptor.recv_prepare`, including stale and duplicate messages |
| `paxos/essential.py:152` | `HandleAccept` | Around `Acceptor.recv_accept_request`, including rejected messages |
| `paxos/essential.py:184` | `HandleAccepted` | Around `Learner.recv_accepted`, including ignored messages |

The same patch makes Python-2-era comparisons against `None` explicit so the
upstream semantics run under Python 3. The old external `TracedLearner`
reimplementation is no longer used.

## Trace Schema

Every event is one mutex-protected NDJSON line flushed at emit time:

```json
{"tag":"trace","ts":123456789,"event":{"name":"Prepare","nid":"p1","state":{},"msg":{},"reads":{},"writes":{}}}
```

`ts` is from `time.monotonic_ns()`. `state` is the full role post-state.
`reads` is the role pre-state plus incoming `msg.*` fields. `writes` is the
post-state delta plus emitted messages under `msgs+`. `ProposalID` serializes
as `[number, uid]`.

Captured role state:

| Role | Fields |
| --- | --- |
| Proposer | `proposal_id`, `proposed_value`, `last_accepted_id`, `next_proposal_number`, `promises_rcvd` |
| Acceptor | `promised_id`, `accepted_id`, `accepted_value` |
| Learner | latest accepted proposal per acceptor, tracked proposal counts, `final_proposal_id`, `final_value` |

## Scenarios

| File | Scenario |
| --- | --- |
| `trace_01_happy.ndjson` | Normal one-proposer resolution |
| `trace_02_duel.ndjson` | Two proposers interleave ballots |
| `trace_03_loss.ndjson` | Drops one Promise and one Accepted message |
| `trace_04_late.ndjson` | Reorders the first Promise |
| `trace_05_duplicate.ndjson` | Re-delivers the first Prepare |

The upstream implementation is networking-agnostic, so the driver supplies a
deterministic in-memory `Messenger`. Protocol state transitions still execute
inside the real patched `Proposer`, `Acceptor`, and `Learner` methods.

## Run

From the project root:

```bash
bash scripts/harness/essential_paxos/run.sh
```

Or from the artifact directory after one apply:

```bash
cd artifacts/essential_paxos
bash run.sh
```

The run removes old `trace_*.ndjson` files, emits five fresh traces, validates
every NDJSON line, checks real monotonic timestamps, and requires all five TV
actions to appear.

## Adjust Instrumentation

- Add or remove captured state in `tla_trace.py`'s `proposer_state`,
  `acceptor_state`, or `learner_state`.
- Add an event by wrapping the real upstream method body with
  `tla_trace.action(...)` in a clean checkout, then regenerate
  `instrumentation.patch`.
- Move a capture point by moving the corresponding `with tla_trace.action`
  block in the patched source and regenerating the patch.
- Re-run with `bash scripts/harness/essential_paxos/run.sh`.

## Known Limits

- `SetProposal` is intentionally not traced: the prompt declares it auxiliary
  and outside the five TV actions. Its value is visible in the next `Prepare`
  pre-state.
- The queue injects loss, duplication, and reordering without an OS network.
- Crash recovery and durability are out of scope for `essential.py`.
- This task does not ship a task-local `Trace.tla`/`Trace.cfg`, so
  `validate_traces.py` performs the harness-level structural smoke. A TV pass
  against a concrete generated spec remains downstream work.
