"""
scripts/harness/essential_paxos/run.py

Instrumentation harness for cocagne/paxos `essential.py`. Drives
Proposer/Acceptor/Learner instances through four scenarios and emits
SysMoBench-canonical NDJSON traces directly (no parse step needed).

Each emitted line is one atomic spec-action transition:

    {"tag":"trace","event":{
       "name":   <action_or_label>,
       "action": <spec_action_or_null>,
       "label":  <method-qualified code path>,
       "pid":    <role_uid>,
       "archetype": <"Proposer"|"Acceptor"|"Learner">,
       "reads":  {<var>: <pre-value>, ...},
       "writes": {<var>: <post-value>, ...}
    }}

Usage (from project root):
    bash scripts/harness/essential_paxos/run.sh
or directly:
    TRACES_DIR=artifacts/essential_paxos/traces \\
    python3 scripts/harness/essential_paxos/run.py
"""

import copy
import json
import os
import sys
from collections import deque
from pathlib import Path

from paxos import essential
from paxos.essential import ProposalID

# Python-2 vs Python-3 compatibility: essential.py compares ProposalID tuples
# against None in several places. Initialize every proposal-id-typed field to
# a sentinel so comparisons always succeed.
NEG_INF = ProposalID(-1, "")

ARCHETYPE = {
    "Proposer": "Proposer",
    "Acceptor": "Acceptor",
    "Learner":  "Learner",
}

# ---------------------------------------------------------------------------
# Canonical trace emission
# ---------------------------------------------------------------------------

def _ser(v):
    """JSON-friendly serialization. ProposalID → 2-list or null."""
    if isinstance(v, ProposalID):
        return None if v == NEG_INF else [v.number, v.uid]
    if isinstance(v, (set, frozenset)):
        return sorted(_ser(x) for x in v)
    if isinstance(v, (list, tuple)):
        return [_ser(x) for x in v]
    if isinstance(v, dict):
        return {k: _ser(val) for k, val in v.items()}
    return v


class CanonicalTrace:
    """Buffers events for one scenario, writes them out as NDJSON on close."""

    def __init__(self, out_path):
        self.out = open(out_path, "w")
        self.seq = 0

    def emit(self, action, label, pid, archetype, reads, writes):
        rec = {
            "tag": "trace",
            "event": {
                "seq":       self.seq,
                "name":      action if action else label,
                "action":    action,
                "label":     label,
                "pid":       pid,
                "archetype": archetype,
                "reads":     {k: _ser(v) for k, v in reads.items()},
                "writes":    {k: _ser(v) for k, v in writes.items()},
            }
        }
        self.out.write(json.dumps(rec) + "\n")
        self.seq += 1

    def close(self):
        self.out.close()


# ---------------------------------------------------------------------------
# State snapshots (used to compute pre/post deltas)
# ---------------------------------------------------------------------------

def snap_proposer(p):
    return {
        f"proposal_id[{p.proposer_uid}]":     p.proposal_id,
        f"proposed_value[{p.proposer_uid}]":  p.proposed_value,
        f"last_accepted_id[{p.proposer_uid}]": p.last_accepted_id,
        f"promises_rcvd[{p.proposer_uid}]":   sorted(list(p.promises_rcvd or [])),
    }

def snap_acceptor(a, uid):
    return {
        f"promised_id[{uid}]":    a.promised_id,
        f"accepted_id[{uid}]":    a.accepted_id,
        f"accepted_value[{uid}]": a.accepted_value,
    }

def snap_learner(l, uid):
    return {
        f"final_proposal_id[{uid}]": l.final_proposal_id,
        f"final_value[{uid}]":       l.final_value,
    }

def diff(pre, post):
    """Return only the entries of `post` that differ from `pre`."""
    out = {}
    for k, v in post.items():
        if pre.get(k) != v:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Network — collects messages emitted during a role method, dispatches them
# ---------------------------------------------------------------------------

class Network:
    """In-memory message queue with optional drop / duplicate / reorder hooks."""

    def __init__(self, drop_ids=None, duplicate_ids=None, reorder=None):
        self.queue         = deque()
        self.acceptors     = {}
        self.proposers     = {}
        self.learners      = {}
        self.msg_counter   = 0
        self.drop_ids      = set(drop_ids or [])
        self.duplicate_ids = set(duplicate_ids or [])
        self.reorder       = reorder
        self._capture      = None    # if not None, sends append here too

    def register(self, role, uid, obj):
        getattr(self, role + "s")[uid] = obj

    def start_capture(self):
        self._capture = []

    def end_capture(self):
        cap, self._capture = self._capture, None
        return cap

    def enqueue(self, msg):
        mid = self.msg_counter
        self.msg_counter += 1
        if self._capture is not None:
            self._capture.append(_describe(msg))
        if mid in self.drop_ids:
            return
        self.queue.append((mid, msg))
        if mid in self.duplicate_ids:
            self.queue.append((mid, msg))
        if self.reorder is not None:
            self.queue = self.reorder(self.queue)


def _describe(msg):
    kind = msg[0]
    return f"{kind}{tuple(_ser(x) for x in msg[1:])}"


# ---------------------------------------------------------------------------
# LoggingMessenger — implements cocagne's Messenger interface
# ---------------------------------------------------------------------------

class HarnessMessenger:
    def __init__(self, owner_uid, network, acceptor_uids, learner_uids):
        self.owner_uid     = owner_uid
        self.network       = network
        self.acceptor_uids = acceptor_uids
        self.learner_uids  = learner_uids

    def send_prepare(self, proposal_id):
        for a in self.acceptor_uids:
            self.network.enqueue(("prepare", self.owner_uid, a, proposal_id))

    def send_promise(self, proposer_uid, proposal_id, previous_id, accepted_value):
        self.network.enqueue(("promise", self.owner_uid, proposer_uid,
                              proposal_id, previous_id, accepted_value))

    def send_accept(self, proposal_id, proposal_value):
        for a in self.acceptor_uids:
            self.network.enqueue(("accept", self.owner_uid, a,
                                  proposal_id, proposal_value))

    def send_accepted(self, proposal_id, accepted_value):
        for ln in self.learner_uids:
            self.network.enqueue(("accepted", self.owner_uid, ln,
                                  proposal_id, accepted_value))

    def on_resolution(self, proposal_id, value):
        # Learner's "decided" signal. Captured indirectly via state snapshot
        # on the next HandleAccepted emit; no separate trace event.
        pass


# ---------------------------------------------------------------------------
# Py3-patched Learner — same fix as before
# ---------------------------------------------------------------------------

class TracedLearner(essential.Learner):
    def recv_accepted(self, from_uid, proposal_id, accepted_value):
        if self.final_value is not None:
            return
        if self.proposals is None:
            self.proposals = {}
            self.acceptors = {}
        last_pn = self.acceptors.get(from_uid, NEG_INF)
        if not proposal_id > last_pn:
            return
        self.acceptors[from_uid] = proposal_id
        if last_pn is not NEG_INF:
            oldp = self.proposals[last_pn]
            oldp[1] -= 1
            if oldp[1] == 0:
                del self.proposals[last_pn]
        if proposal_id not in self.proposals:
            self.proposals[proposal_id] = [0, 0, accepted_value]
        t = self.proposals[proposal_id]
        assert accepted_value == t[2]
        t[0] += 1
        t[1] += 1
        if t[0] == self.quorum_size:
            self.final_value = accepted_value
            self.final_proposal_id = proposal_id
            self.proposals = None
            self.acceptors = None
            self.messenger.on_resolution(proposal_id, accepted_value)


# ---------------------------------------------------------------------------
# Action emitters — wrap each role method, emit canonical event
# ---------------------------------------------------------------------------

def do_prepare(trace, network, proposer):
    pre = snap_proposer(proposer)
    network.start_capture()
    proposer.prepare()
    sent = network.end_capture()
    post = snap_proposer(proposer)
    writes = diff(pre, post)
    if sent:
        writes["msgs+"] = sent
    trace.emit(
        action="Prepare",
        label="Proposer.prepare",
        pid=proposer.proposer_uid,
        archetype="Proposer",
        reads={k: pre[k] for k in pre},
        writes=writes,
    )

def do_recv_prepare(trace, network, acceptor, uid, from_uid, proposal_id):
    pre = snap_acceptor(acceptor, uid)
    pre[f"msg.from_"]        = from_uid
    pre[f"msg.proposal_id"]  = proposal_id
    network.start_capture()
    acceptor.recv_prepare(from_uid, proposal_id)
    sent = network.end_capture()
    post = snap_acceptor(acceptor, uid)
    writes = diff(pre, post)
    if sent:
        writes["msgs+"] = sent
    trace.emit(
        action="HandlePrepare",
        label="Acceptor.recv_prepare",
        pid=uid,
        archetype="Acceptor",
        reads={k: v for k, v in pre.items() if not k.startswith("msg.") or True},
        writes=writes,
    )

def do_recv_promise(trace, network, proposer, from_uid, proposal_id, prev_id, prev_val):
    pre = snap_proposer(proposer)
    pre["msg.from_"]                 = from_uid
    pre["msg.proposal_id"]            = proposal_id
    pre["msg.prev_accepted_id"]       = prev_id
    pre["msg.prev_accepted_value"]    = prev_val
    network.start_capture()
    proposer.recv_promise(from_uid, proposal_id, prev_id, prev_val)
    sent = network.end_capture()
    post = snap_proposer(proposer)
    writes = diff(pre, post)
    if sent:
        writes["msgs+"] = sent
    trace.emit(
        action="HandlePromise",
        label="Proposer.recv_promise",
        pid=proposer.proposer_uid,
        archetype="Proposer",
        reads=pre,
        writes=writes,
    )

def do_recv_accept(trace, network, acceptor, uid, from_uid, proposal_id, value):
    pre = snap_acceptor(acceptor, uid)
    pre["msg.from_"]       = from_uid
    pre["msg.proposal_id"] = proposal_id
    pre["msg.value"]       = value
    network.start_capture()
    acceptor.recv_accept_request(from_uid, proposal_id, value)
    sent = network.end_capture()
    post = snap_acceptor(acceptor, uid)
    writes = diff(pre, post)
    if sent:
        writes["msgs+"] = sent
    trace.emit(
        action="HandleAccept",
        label="Acceptor.recv_accept_request",
        pid=uid,
        archetype="Acceptor",
        reads=pre,
        writes=writes,
    )

def do_recv_accepted(trace, network, learner, uid, from_uid, proposal_id, value):
    pre = snap_learner(learner, uid)
    pre["msg.from_"]       = from_uid
    pre["msg.proposal_id"] = proposal_id
    pre["msg.value"]       = value
    network.start_capture()
    learner.recv_accepted(from_uid, proposal_id, value)
    sent = network.end_capture()    # always empty for Learner
    post = snap_learner(learner, uid)
    writes = diff(pre, post)
    trace.emit(
        action="HandleAccepted",
        label="Learner.recv_accepted",
        pid=uid,
        archetype="Learner",
        reads=pre,
        writes=writes,
    )


# ---------------------------------------------------------------------------
# Drainer — pops messages off the network queue, dispatches to action emitters
# ---------------------------------------------------------------------------

def drain(trace, network):
    while network.queue:
        mid, msg = network.queue.popleft()
        kind = msg[0]
        if kind == "prepare":
            _, from_uid, to_uid, pid = msg
            do_recv_prepare(trace, network,
                            network.acceptors[to_uid], to_uid, from_uid, pid)
        elif kind == "promise":
            _, from_uid, to_uid, pid, prev_id, prev_val = msg
            do_recv_promise(trace, network,
                            network.proposers[to_uid], from_uid, pid, prev_id, prev_val)
        elif kind == "accept":
            _, from_uid, to_uid, pid, val = msg
            do_recv_accept(trace, network,
                           network.acceptors[to_uid], to_uid, from_uid, pid, val)
        elif kind == "accepted":
            _, from_uid, to_uid, pid, val = msg
            do_recv_accepted(trace, network,
                             network.learners[to_uid], to_uid, from_uid, pid, val)


# ---------------------------------------------------------------------------
# Factories — instantiate roles with NEG_INF sentinels for Py3 compat
# ---------------------------------------------------------------------------

def make_acceptor(uid, network, acceptor_uids, learner_uids):
    a = essential.Acceptor()
    a.messenger      = HarnessMessenger(uid, network, acceptor_uids, learner_uids)
    a.promised_id    = NEG_INF
    a.accepted_id    = NEG_INF
    a.accepted_value = None
    network.register("acceptor", uid, a)
    return a

def make_proposer(uid, network, quorum, acceptor_uids, learner_uids):
    p = essential.Proposer()
    p.messenger        = HarnessMessenger(uid, network, acceptor_uids, learner_uids)
    p.proposer_uid     = uid
    p.quorum_size      = quorum
    p.last_accepted_id = NEG_INF
    p.promises_rcvd    = set()
    network.register("proposer", uid, p)
    return p

def make_learner(uid, network, quorum, acceptor_uids, learner_uids):
    l = TracedLearner()
    l.messenger   = HarnessMessenger(uid, network, acceptor_uids, learner_uids)
    l.quorum_size = quorum
    network.register("learner", uid, l)
    return l


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def setup(n_accept=3, n_learn=1, quorum=2, **net_kwargs):
    net = Network(**net_kwargs)
    A = [f"a{i+1}" for i in range(n_accept)]
    L = [f"l{i+1}" for i in range(n_learn)]
    for u in A: make_acceptor(u, net, A, L)
    for u in L: make_learner(u, net, quorum, A, L)
    return net, A, L

def scenario_happy(trace):
    net, A, L = setup()
    p1 = make_proposer("p1", net, 2, A, L)
    p1.set_proposal("foo")
    do_prepare(trace, net, p1)
    drain(trace, net)

def scenario_duel(trace):
    net, A, L = setup()
    p1 = make_proposer("p1", net, 2, A, L)
    p2 = make_proposer("p2", net, 2, A, L)
    p1.set_proposal("foo")
    p2.set_proposal("bar")
    do_prepare(trace, net, p1)
    # deliver three messages, then p2 interjects with a higher prepare
    for _ in range(3):
        if not net.queue: break
        drain_one(trace, net)
    do_prepare(trace, net, p2)
    drain(trace, net)

def drain_one(trace, network):
    """Single-step drain — used by duel scenario for interleaving."""
    if not network.queue:
        return
    saved = network.queue
    network.queue = deque([saved.popleft()])
    drain(trace, network)
    network.queue.extend(saved)

def scenario_loss(trace):
    # Drop two messages by id (1 = first promise, 6 = an accepted)
    net, A, L = setup(drop_ids=[1, 6])
    p1 = make_proposer("p1", net, 2, A, L)
    p1.set_proposal("foo")
    do_prepare(trace, net, p1)
    drain(trace, net)

def scenario_late(trace):
    moved = {"done": False}
    def reorder(q):
        if moved["done"]: return q
        for i, (_, m) in enumerate(q):
            if m[0] == "promise":
                item = q[i]; del q[i]; q.append(item)
                moved["done"] = True
                break
        return q
    net, A, L = setup(reorder=reorder)
    p1 = make_proposer("p1", net, 2, A, L)
    p1.set_proposal("foo")
    do_prepare(trace, net, p1)
    drain(trace, net)

SCENARIOS = [
    ("happy", scenario_happy),
    ("duel",  scenario_duel),
    ("loss",  scenario_loss),
    ("late",  scenario_late),
]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    out_dir = Path(os.environ.get("TRACES_DIR", "artifacts/essential_paxos/traces"))
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, (name, fn) in enumerate(SCENARIOS, start=1):
        path = out_dir / f"trace_{i:02d}_{name}.ndjson"
        trace = CanonicalTrace(path)
        try:
            fn(trace)
        finally:
            trace.close()
        print(f"[run.py] wrote {path}", file=sys.stderr)

if __name__ == "__main__":
    main()