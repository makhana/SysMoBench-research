# Instrumentation Guide — essential_paxos

This document is for the Phase 3 (validation) agent. It describes where each
instrumentation point lives and how to adjust it if trace validation reveals
issues.

## System overview

- **Source**: `paxos/essential.py` in the cocagne/paxos clone
  (`data/repositories/cocagne_paxos`)
- **Language**: Python 3
- **Instrumentation style**: External interface implementation (Category A,
  standard single-file NDJSON). No source patching required.
- **Extension point**: `Messenger` abstract class. `HarnessMessenger` in
  `run.py` implements it and routes messages through an in-memory `Network`.

## Category

**Category A** (simulated distributed). Operations are not ns-level CAS ops;
no probe effect; standard single-file approach is correct.

## Files

| File | Role |
|------|------|
| `artifacts/essential_paxos_skill_compare/run.py` | Harness driver (trace emitter + scenarios) |
| `artifacts/essential_paxos_skill_compare/run.sh` | One-command orchestrator |
| `data/repositories/cocagne_paxos/paxos/essential.py` | **Read-only** source (never patched) |

## Instrumentation points (file:function)

All emit calls are in `run.py`. The actual protocol code runs inside each
emit function; the emit is the wrapper.

| Spec action     | Function in run.py         | Trigger point |
|-----------------|---------------------------|---------------|
| `Prepare`       | `emit_prepare`            | After `proposer.prepare()` returns |
| `HandlePrepare` | `emit_handle_prepare`     | After `acceptor.recv_prepare()` returns |
| `HandlePromise` | `emit_handle_promise`     | After `proposer.recv_promise()` returns |
| `HandleAccept`  | `emit_handle_accept`      | After `acceptor.recv_accept_request()` returns |
| `HandleAccepted`| `emit_handle_accepted`    | After `learner.recv_accepted()` (TracedLearner) returns |

All captures are **post-state** (state is read after the method returns).

## State capture levels

All actions use **Full** capture: the role object is fully accessible after
the method returns and all relevant fields are captured.

| Action           | Captured fields |
|------------------|----------------|
| `Prepare`        | `proposal_id`, `proposed_value`, `last_accepted_id`, `promises_rcvd` |
| `HandlePrepare`  | `promised_id`, `accepted_id`, `accepted_value` |
| `HandlePromise`  | `proposal_id`, `proposed_value`, `last_accepted_id`, `promises_rcvd` |
| `HandleAccept`   | `promised_id`, `accepted_id`, `accepted_value` |
| `HandleAccepted` | `final_proposal_id`, `final_value` |

## NDJSON schema

```
config line (first line per file):
  {"tag": "config", "ts": <epoch_ns>, "config": {
      "acceptors": ["a1","a2","a3"],
      "learners":  ["l1"],
      "quorum_size": 2
  }}

event line:
  {"tag": "trace", "ts": <epoch_ns>, "event": {
      "name":      "<SpecActionName>",
      "nid":       "<role_uid>",
      "archetype": "Proposer"|"Acceptor"|"Learner",
      "state":     {<post-state vars>},
      "msg":       {<inbound message fields>} | absent for Prepare
  }}
```

- `ts` is `time.time_ns()` (real epoch nanoseconds, never synthetic).
- `ProposalID(n, uid)` serializes to `[n, uid]`; `NEG_INF` serializes to `null`.

## How to add a new field to an event

1. Find the relevant `state_<role>()` function in `run.py`.
2. Add the field: `"new_field": obj.new_field`.
3. Re-run: `bash artifacts/essential_paxos_skill_compare/run.sh`

## How to move a capture point (post → pre)

Each `emit_*` function in `run.py` calls `role.method()` then reads state.
To capture pre-state: snapshot before the call and pass that snapshot to
`tw.emit(state=...)` instead.

## How to add a new event type

Copy the pattern of the closest existing `emit_*` function, add a new
function, insert a call in the `drain()` dispatch or at the scenario level,
and add the action name to `REQUIRED_ACTIONS` in `run.sh`.

## How to rebuild and re-run

No build step. Just:

```bash
TRACES_DIR=artifacts/essential_paxos/traces \
REPO_PATH=data/repositories/cocagne_paxos \
bash artifacts/essential_paxos_skill_compare/run.sh
```

## Known limitations / coverage gaps

- Single-process simulation. No real network stack; loss and reorder are
  injected by the harness `Network` class.
- Four scenarios (happy, duel, loss, late_promise). More concurrent-proposer
  races are possible but not currently exercised.
- `TracedLearner` overrides `Learner.recv_accepted` to fix a Py2-vs-Py3
  `None`-comparison bug in upstream `essential.py`. The protocol semantics
  are identical; only the sentinel value changes (`None` → `NEG_INF`).
- No crash/restart coverage. `essential.py` has no persistence (that lives
  in `durable.py`, which is out of scope for this task).
