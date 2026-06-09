#!/usr/bin/env python3
"""
Deterministic TLC-based transition-validation runner for Essential Paxos.

This is the deterministic alternative to the agent-based TV scoring path.
The agent path (launch_tv_eval.sh) generates traces from the real system and
windows them, but its TLC-scoring step proved unreliable (timeouts). This
runner consumes already-generated `windows/*.ndjson` and scores each
(pre-state, action, post-state) window by building a per-window TLA+ module,
constraining Init to the pre-state, taking one step of the target action, and
asserting the post-state via an inverted invariant (NeverPost). TLC exit 12
(invariant violated == post-state reached) => PASS.

Usage:
  python3 scripts/tv_runner_tlc.py --workspace <dir> [--lib <tla2tools.jar>]

The workspace must contain:
  spec/EssentialPaxos.tla (+ .cfg)   the spec under evaluation
  windows/<Action>.ndjson            one window per line
Results are written to reports/tv_results.json: {action: {passes,total,rate}}.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Bound in main() from --workspace; declared as globals so the generation/run
# helpers below can reference them unchanged.
WORKSPACE = None
TV_DIR    = None
SPEC_DIR  = None
WIN_DIR   = None
REP_DIR   = None
LIB       = _PROJECT_ROOT / "lib" / "tla2tools.jar"

ACCEPTORS = ["a1", "a2", "a3"]
PROPOSERS = ["p1", "p2"]
LEARNERS  = ["l1"]
VALUES    = ["foo", "bar"]  # values seen in traces

ACTIONS = ["Prepare", "HandlePrepare", "HandlePromise", "HandleAccept", "HandleAccepted"]

# Which schema variables each action can change (used in PostReached)
ACTION_CHANGED_VARS = {
    "Prepare":         ["proposerProposalId", "proposerPromisesRcvd", "proposerNextProposalNumber"],
    "HandlePrepare":   ["acceptorPromisedId"],
    "HandlePromise":   ["proposerPromisesRcvd", "proposerLastAcceptedId", "proposerProposedValue"],
    "HandleAccept":    ["acceptorPromisedId", "acceptorAcceptedId", "acceptorAcceptedValue"],
    "HandleAccepted":  ["learnerFinalValue", "learnerFinalProposalId"],
}

# All schema variables with their type tag for conversion
SCHEMA_VARS = [
    ("proposerProposalId",      "proposer_pid"),
    ("proposerProposedValue",   "proposer_value"),
    ("proposerPromisesRcvd",    "proposer_set"),
    ("proposerLastAcceptedId",  "proposer_pid"),
    ("acceptorPromisedId",      "acceptor_pid"),
    ("acceptorAcceptedId",      "acceptor_pid"),
    ("acceptorAcceptedValue",   "acceptor_value"),
    ("learnerFinalValue",       "learner_value"),
    ("learnerFinalProposalId",  "learner_pid"),
]


def to_tla(v, type_tag):
    """Convert a JSON window value to a TLA+ expression string."""
    if type_tag.startswith("proposer_"):
        domain = PROPOSERS
        val_type = type_tag[len("proposer_"):]
    elif type_tag.startswith("acceptor_"):
        domain = ACCEPTORS
        val_type = type_tag[len("acceptor_"):]
    elif type_tag.startswith("learner_"):
        domain = LEARNERS
        val_type = type_tag[len("learner_"):]
    else:
        domain = None
        val_type = type_tag

    if isinstance(v, dict):
        parts = []
        for k in domain:
            val = v.get(k)
            parts.append(f'"{k}" :> {scalar_to_tla(val, val_type)}')
        return " @@ ".join(parts) if parts else "<<>>"
    else:
        return scalar_to_tla(v, val_type)


def scalar_to_tla(v, val_type):
    """Convert a single scalar/list value to TLA+."""
    if v is None:
        if val_type == "set":
            return "{}"
        return "NoValue"
    if isinstance(v, list):
        if len(v) == 0:
            if val_type == "set":
                return "{}"
            return "{}"  # empty set for promise sets too
        if val_type == "set":
            # list of acceptor ids → TLA+ set with quoted string elements
            elems = ", ".join(f'"{e}"' if isinstance(e, str) else str(e) for e in v)
            return "{" + elems + "}"
        if val_type == "pid":
            # [n, "p_uid"] → <<n, "p_uid">>
            n, uid = v[0], v[1]
            return f'<<{n}, "{uid}">>'
        # fallback
        elems = ", ".join(str(e) for e in v)
        return "<<" + elems + ">>"
    if isinstance(v, str):
        # Always quote strings — both role IDs and values become TLA+ string literals.
        # Role IDs (a1, p1, l1) cannot be used as unquoted identifiers in module body;
        # they must be quoted strings matching the cfg binding {"a1","a2","a3"}.
        return f'"{v}"'
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    return str(v)


def generate_tv_module(action, window, win_idx, tmp_dir):
    """Write a standalone TV_<Action>_w<N>.tla + .cfg for one window."""

    pre  = window["pre_state"]
    post = window["post_state"]
    inp  = window.get("input")

    changed = ACTION_CHANGED_VARS.get(action, [])

    # Build TLA+ constants for pre/post state
    tla_pre  = {}
    tla_post = {}
    for var, tag in SCHEMA_VARS:
        if var in pre:
            tla_pre[var]  = to_tla(pre[var],  tag)
            tla_post[var] = to_tla(post[var], tag)

    # proposerNextProposalNumber: infer from proposerProposalId post-state.
    # Prepare uses the CURRENT proposerNextProposalNumber[p] AS the ballot, then
    # increments it. So if post proposerProposalId[actor] = <<n, actor>>, the
    # PRE-state next number for the actor must be exactly n (not n+1).
    next_num_pre = " @@ ".join(f'"{p}" :> 1' for p in PROPOSERS)
    actor = window.get("actor")
    if action == "Prepare" and actor:
        post_pid = post.get("proposerProposalId", {}).get(actor)
        if post_pid and isinstance(post_pid, list):
            ballot = post_pid[0]
            entries = " @@ ".join(
                f'"{p}" :> {ballot}' if p == actor else f'"{p}" :> 1'
                for p in PROPOSERS
            )
            next_num_pre = entries

    # Build Init
    init_lines = []
    for var, tag in SCHEMA_VARS:
        if var in tla_pre:
            init_lines.append(f"    /\\ {var} = {tla_pre[var]}")
    init_lines.append(f"    /\\ proposerNextProposalNumber = {next_num_pre}")
    init_lines.append(f"    /\\ learnerProposals = [l \\in Learners |-> NoValue]")
    init_lines.append(f"    /\\ learnerAcceptors = [l \\in Learners |-> NoValue]")
    init_lines.append(f"    /\\ msgs = {{}}")
    init_lines.append(f"    /\\ step = 0")

    # Build PostReached checks (only changed vars)
    post_checks = ["    /\\ step = 1"]
    for var in changed:
        if var in tla_post:
            post_checks.append(f"    /\\ {var} = {tla_post[var]}")

    # Build Next — new spec uses single-argument handlers with \E m \in msgs internally.
    # For handler actions, we put the triggering message in msgs in Init and call with 1 arg.
    init_msg_tla = None  # set for handler actions to inject into msgs

    if action == "Prepare":
        next_action = f"\\E p \\in Proposers : S!Prepare(p)"
    elif action == "HandlePrepare":
        if inp:
            pid = scalar_to_tla(inp.get("proposal_id"), "pid")
            frm = scalar_to_tla(inp.get("from"), "")
            to  = scalar_to_tla(inp.get("to"),   "")
            init_msg_tla = (f'[type |-> "prepare", from |-> {frm}, to |-> {to}, '
                            f'proposal_id |-> {pid}, prev_accepted_id |-> NoValue, value |-> NoValue]')
            next_action = f"S!HandlePrepare({to})"
        else:
            next_action = "\\E a \\in Acceptors : S!HandlePrepare(a)"
    elif action == "HandlePromise":
        if inp:
            pid  = scalar_to_tla(inp.get("proposal_id"), "pid")
            frm  = scalar_to_tla(inp.get("from"), "")
            to   = scalar_to_tla(inp.get("to"),   "")
            pai  = scalar_to_tla(inp.get("prev_accepted_id"), "pid")
            pav  = scalar_to_tla(inp.get("prev_accepted_value"), "value")
            init_msg_tla = (f'[type |-> "promise", from |-> {frm}, to |-> {to}, '
                            f'proposal_id |-> {pid}, prev_accepted_id |-> {pai}, value |-> {pav}]')
            next_action = f"S!HandlePromise({to})"
        else:
            next_action = "\\E p \\in Proposers : S!HandlePromise(p)"
    elif action == "HandleAccept":
        if inp:
            pid  = scalar_to_tla(inp.get("proposal_id"), "pid")
            frm  = scalar_to_tla(inp.get("from"), "")
            to   = scalar_to_tla(inp.get("to"),   "")
            val  = scalar_to_tla(inp.get("value"), "value")
            init_msg_tla = (f'[type |-> "accept", from |-> {frm}, to |-> {to}, '
                            f'proposal_id |-> {pid}, prev_accepted_id |-> NoValue, value |-> {val}]')
            next_action = f"S!HandleAccept({to})"
        else:
            next_action = "\\E a \\in Acceptors : S!HandleAccept(a)"
    elif action == "HandleAccepted":
        if inp:
            pid  = scalar_to_tla(inp.get("proposal_id"), "pid")
            frm  = scalar_to_tla(inp.get("from"), "")
            to   = scalar_to_tla(inp.get("to"),   "")
            val  = scalar_to_tla(inp.get("value"), "value")
            init_msg_tla = (f'[type |-> "accepted", from |-> {frm}, to |-> {to}, '
                            f'proposal_id |-> {pid}, prev_accepted_id |-> NoValue, value |-> {val}]')
            next_action = f"S!HandleAccepted({to})"
        else:
            next_action = "\\E l \\in Learners : S!HandleAccepted(l)"
    else:
        next_action = "FALSE"

    # Inject triggering message into msgs for handler actions
    if init_msg_tla:
        # Replace msgs = {} with msgs = {init_msg_tla}
        for i, line in enumerate(init_lines):
            if "/\\ msgs = {}" in line:
                init_lines[i] = f"    /\\ msgs = {{{init_msg_tla}}}"
                break

    all_vars = [v for v, _ in SCHEMA_VARS] + ["proposerNextProposalNumber", "learnerProposals",
                                                "learnerAcceptors", "msgs", "step"]

    tla_content = f"""---- MODULE TV_{action}_w{win_idx} ----
EXTENDS Naturals, FiniteSets, TLC
CONSTANTS Acceptors, Proposers, Learners, Values, NoValue, MaxBallot

VARIABLES {", ".join(all_vars)}
vars == <<{", ".join(all_vars)}>>

S == INSTANCE EssentialPaxos

Init ==
{chr(10).join(init_lines)}

Next ==
    /\\ step = 0
    /\\ {next_action}
    /\\ step' = step + 1

PostReached ==
{chr(10).join(post_checks) if post_checks else "    /\\ FALSE"}

NeverPost == ~PostReached

Spec == Init /\\ [][Next]_vars
====
"""

    cfg_content = f"""CONSTANTS
    Acceptors = {{"a1", "a2", "a3"}}
    Proposers = {{"p1", "p2"}}
    Learners  = {{"l1"}}
    Values    = {{"foo", "bar"}}
    NoValue   = NoValue
    MaxBallot = 3

SPECIFICATION Spec
INVARIANT NeverPost
CHECK_DEADLOCK FALSE
"""

    mod_name = f"TV_{action}_w{win_idx}"
    tla_path = tmp_dir / f"{mod_name}.tla"
    cfg_path = tmp_dir / f"{mod_name}.cfg"
    tla_path.write_text(tla_content)
    cfg_path.write_text(cfg_content)
    return tla_path, cfg_path


def run_tlc(tla_path, cfg_path, spec_dir, timeout=30):
    """Run TLC. Returns (passed, error_msg)."""
    cmd = [
        "java", "-cp", str(LIB), "tlc2.TLC",
        "-config", cfg_path.name,
        tla_path.name,
        "-nowarning",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=timeout,
            cwd=str(tla_path.parent),
            env={**os.environ, "SPEC_DIR": str(spec_dir)},
        )
        output = result.stdout + result.stderr
        # TLC exit 12 = invariant violation (PostReached was reached) → PASS
        # TLC exit 0  = no violation (PostReached never reached) → FAIL
        # TLC exit 75 = exception → ERROR
        if result.returncode == 12:
            return True, None
        if result.returncode == 0:
            return False, "PostReached never satisfied (spec can't reach post-state)"
        # check output for "Error: Invariant NeverPost is violated"
        if "NeverPost is violated" in output or "Invariant NeverPost" in output:
            return True, None
        return False, f"TLC exit {result.returncode}: {output[:300]}"
    except subprocess.TimeoutExpired:
        return False, "TLC timeout"
    except Exception as e:
        return False, f"Exception: {e}"


def run_action(action):
    win_file = WIN_DIR / f"{action}.ndjson"
    if not win_file.exists():
        print(f"  [SKIP] No windows file: {win_file}")
        return {"passes": 0, "total": 0, "rate": 0.0, "details": []}

    windows = []
    with open(win_file) as f:
        for line in f:
            line = line.strip()
            if line:
                windows.append(json.loads(line))

    passed = 0
    details = []

    # Use a temporary directory co-located with the spec so INSTANCE works
    with tempfile.TemporaryDirectory(dir=str(SPEC_DIR)) as tmp_str:
        tmp_dir = Path(tmp_str)
        # Symlink spec files into tmp_dir
        for src in SPEC_DIR.iterdir():
            if src.suffix in (".tla", ".cfg"):
                (tmp_dir / src.name).symlink_to(src)

        for i, win in enumerate(windows, 1):
            tla_path, cfg_path = generate_tv_module(action, win, i, tmp_dir)
            ok, err = run_tlc(tla_path, cfg_path, SPEC_DIR)
            status = "PASS" if ok else "FAIL"
            details.append({"window": i, "status": status, "error": err})
            if ok:
                passed += 1
            print(f"    w{i:02d}: {status}" + (f" — {err}" if err else ""))

    total = len(windows)
    rate = passed / total if total > 0 else 0.0
    return {"passes": passed, "total": total, "rate": rate, "details": details}


def main():
    global WORKSPACE, TV_DIR, SPEC_DIR, WIN_DIR, REP_DIR, LIB

    parser = argparse.ArgumentParser(description="Deterministic TLC-based TV runner")
    parser.add_argument("--workspace", required=True,
                        help="TV workspace dir containing spec/ and windows/")
    parser.add_argument("--lib", default=str(LIB),
                        help="Path to tla2tools.jar (default: <project>/lib/tla2tools.jar)")
    args = parser.parse_args()

    WORKSPACE = Path(args.workspace).resolve()
    TV_DIR   = WORKSPACE / "tv"
    SPEC_DIR = WORKSPACE / "spec"
    WIN_DIR  = WORKSPACE / "windows"
    REP_DIR  = WORKSPACE / "reports"
    LIB      = Path(args.lib).resolve()

    if not SPEC_DIR.is_dir():
        sys.exit(f"ERROR: spec dir not found: {SPEC_DIR}")
    if not WIN_DIR.is_dir():
        sys.exit(f"ERROR: windows dir not found: {WIN_DIR}")
    if not LIB.is_file():
        sys.exit(f"ERROR: tla2tools.jar not found: {LIB}")

    REP_DIR.mkdir(exist_ok=True)
    results = {}

    for action in ACTIONS:
        print(f"\n=== {action} ===")
        r = run_action(action)
        results[action] = r
        print(f"  → {r['passes']}/{r['total']} ({r['rate']:.0%})")

    # Write tv_results.json (pipeline schema)
    tv_results = {
        action: {"passes": r["passes"], "total": r["total"], "rate": r["rate"]}
        for action, r in results.items()
    }
    out = REP_DIR / "tv_results.json"
    out.write_text(json.dumps(tv_results, indent=2))
    print(f"\nWrote {out}")

    total_p = sum(r["passes"] for r in results.values())
    total_t = sum(r["total"]  for r in results.values())
    print(f"\nOverall: {total_p}/{total_t} ({total_p/total_t:.0%})" if total_t else "No windows")


if __name__ == "__main__":
    main()
