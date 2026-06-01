# essential_paxos Harness — Instrumentation & Run Notes

Collects traces from cocagne/paxos `essential.py` (single-decree Paxos:
1 proposer or 2, 3 acceptors, 1 learner) for TV action-window
validation.

## Where the code lives

- **Upstream clone**: `data/repositories/cocagne_paxos/` (read-only;
  no in-place patches).
- **System source**: `data/repositories/cocagne_paxos/paxos/essential.py` —
  `Proposer`, `Acceptor`, `Learner`, `ProposalID`, abstract `Messenger`.
- **Our harness** (no upstream patches required):
  - `scripts/harness/essential_paxos/run.py` — the harness. Implements
    `HarnessMessenger` (cocagne's abstract `Messenger` interface),
    drives Proposer/Acceptor/Learner through four scenarios, emits
    canonical NDJSON. Subclasses `essential.Learner` as `TracedLearner`
    to patch a Python-3 None-vs-tuple comparison bug.
  - `scripts/harness/essential_paxos/run.sh` — orchestrator. Verifies
    the clone exists, sets `TRACES_DIR`, invokes `run.py`, prints a
    summary.

No `parse_traces.py` is needed: the Python harness emits
SysMoBench-canonical events directly. Compare with raftkvs, where
`parse_traces.py` converts PGo-native traces — there the trace format
isn't ours to choose.

## Label → spec action mapping

Each role method in `essential.py` corresponds to exactly one TLA+
action. The harness emits one canonical trace event per method
invocation; the label is the method-qualified name.

| Method label                   | Spec action      |
| ------------------------------ | ---------------- |
| `Proposer.prepare`             | `Prepare`        |
| `Acceptor.recv_prepare`        | `HandlePrepare`  |
| `Proposer.recv_promise`        | `HandlePromise`  |
| `Acceptor.recv_accept_request` | `HandleAccept`   |
| `Learner.recv_accepted`        | `HandleAccepted` |

This mapping is also declared in `task.yaml`'s
`tv.harness.trace_action_map` and is the contract between the harness
and transition validation.

`Messenger.on_resolution` does not get its own event — it is invoked
by the Learner inside `recv_accepted` when a quorum has been collected,
and the consequent state change is captured by the `HandleAccepted`
event's `writes` (specifically, `final_proposal_id[l]` and
`final_value[l]` transition from null to concrete values).

## Event schema

Every line in a trace file is a single JSON object of the form:

```json
{"tag":"trace","event":{
  "seq":       <monotonic int>,
  "name":      <spec action>,
  "action":    <spec action>,
  "label":     <method-qualified label>,
  "pid":       <role uid>,
  "archetype": <"Proposer" | "Acceptor" | "Learner">,
  "reads":     { ... pre-state values incl. incoming msg fields ... },
  "writes":    { ... post-state delta incl. emitted messages ... }
}}
```

The `reads` dict captures the pre-action values of every variable the
action depends on, plus `msg.*` keys for fields read off the incoming
message (when applicable). The `writes` dict captures only entries that
_changed_ during the action; emitted messages appear under the special
`msgs+` key as a list of compact descriptions.

`ProposalID` values serialize as 2-element lists `[number, uid]`. The
sentinel `NEG_INF = ProposalID(-1, "")` (used for "no promise/acceptance
yet" so Python-3 comparisons succeed) serializes as `null`.

## Noise filter

None. The protocol is small enough that every method invocation
corresponds to a meaningful spec action. Compare with raftkvs, where
two tight-poll-loop labels each fire 30K+ times per run and must be
dropped.

## How to run

```bash
# from project root
bash scripts/harness/essential_paxos/run.sh
```

Writes four files into `artifacts/essential_paxos/traces/`:

| File                    | Scenario                                      |
| ----------------------- | --------------------------------------------- |
| `trace_01_happy.ndjson` | 1 proposer, 3 acceptors, 1 learner, no faults |
| `trace_02_duel.ndjson`  | 2 proposers race, p2 issues higher ballot     |
| `trace_03_loss.ndjson`  | Drops 1 Promise and 1 Accepted                |
| `trace_04_late.ndjson`  | First Promise reordered to end of queue       |

Each scenario terminates in a `HandleAccepted` event whose `writes`
populate the learner's `final_value` — i.e., consensus reached. If a
loss scenario is configured to drop messages such that quorum cannot
form, the trace will end without a `final_value`-writing event;
transition validation treats this as a legitimate quiescent terminal
state.

Typical event counts per scenario:

| Action           | happy | duel | loss | late |
| ---------------- | ----- | ---- | ---- | ---- |
| `Prepare`        | 1     | 2    | 1    | 1    |
| `HandlePrepare`  | 3     | 6    | 3    | 3    |
| `HandlePromise`  | 3     | 4-6  | 2-3  | 3    |
| `HandleAccept`   | 3     | 3    | 3    | 3    |
| `HandleAccepted` | 1     | 1    | 1-2  | 1    |
| **Total events** | ~11   | ~17  | ~10  | ~11  |

Runtime: well under a second total for all four scenarios.

### Environment overrides

| Var          | Default                                                  | Purpose             |
| ------------ | -------------------------------------------------------- | ------------------- |
| `TRACES_DIR` | `artifacts/essential_paxos/traces`                       | Output directory    |
| `REPO_PATH`  | `data/repositories/cocagne_paxos`                        | cocagne/paxos clone |
| `PYTHONPATH` | adds `$REPO_PATH` so `from paxos import essential` works | (set by run.sh)     |

## Known gaps

- **External instrumentation.** Unlike raftkvs, where the harness
  patches `bootstrap/server.go` and `bootstrap/client.go` in place,
  this harness wraps cocagne's `Messenger` interface externally. The
  upstream `essential.py` is read-only. This means atomic intermediate
  states _within_ a single `recv_*` call (e.g., between writing
  `promised_id` and sending the Promise) are not separately
  observable — only the action's pre/post snapshot is captured.
  Acceptable here because every spec action is intended to be atomic.

- **Python-3 sentinel patch.** `essential.py` was written for Python 2,
  where `None` compares against tuples without raising. The harness
  initializes every `ProposalID`-typed field to `NEG_INF =
ProposalID(-1, "")` so Python-3 comparisons succeed, and subclasses
  `Learner` as `TracedLearner` to fix one place (`recv_accepted`) where
  upstream depends on the dict-with-None-key shape. Protocol semantics
  unchanged.

- **Single process, no real network.** Loss / duplication / reordering
  are injected by `Network` rather than by an OS network stack. This
  matches the message-bag abstraction every canonical Paxos TLA+ spec
  uses, but loses any wall-clock-driven nondeterminism that a real
  distributed deployment would expose.

- **Four scenarios.** Coverage is intentional rather than exhaustive.
  A richer matrix (e.g., 3 concurrent proposers, partition oracles,
  acceptor crashes) would push transition validation harder but
  requires modeling crashes in the spec, which is out of the project's
  scope (essential.py has no persistence layer; durable.py is excluded).

- **No liveness check.** All four scenarios are designed to terminate
  in a resolution under their respective fault profiles. Paxos liveness
  requires fairness assumptions and a stable leader (out of scope).
