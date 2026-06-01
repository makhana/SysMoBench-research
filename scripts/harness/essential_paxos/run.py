"""
artifacts/essential_paxos_skill_compare/run.py

Trace harness driver for cocagne/paxos `essential.py` — produced by the
harness-gen skill methodology.

Category A (simulated distributed) — single-process, no real network, but
operation timescales are not ns-level CAS ops, so the standard single-file
NDJSON approach is correct.  No mutex needed because everything is
single-threaded.

Instrumentation strategy: implement cocagne's abstract Messenger interface
externally (HarnessMessenger). This is the intended extension point — no
source patching required.

The Py2 vs Py3 None-comparison bug in Learner.recv_accepted is handled via
TracedLearner (same fix as existing harness).

Emitted NDJSON envelope (one line per event):
    {"tag": "trace", "ts": <epoch_ns>, "event": {
        "name":      <spec_action>,
        "nid":       <role_uid>,
        "archetype": <"Proposer"|"Acceptor"|"Learner">,
        "state":     {<post-state vars>},
        "msg":       {<incoming message fields or null>}
    }}

Config line (first line of each trace file):
    {"tag": "config", "ts": <epoch_ns>, "config": {
        "acceptors": [...], "proposers": [...], "learners": [...],
        "quorum_size": N
    }}

Usage:
    TRACES_DIR=artifacts/essential_paxos/traces \\
    PYTHONPATH=data/repositories/cocagne_paxos \\
    python3 artifacts/essential_paxos_skill_compare/run.py
"""

import json
import os
import sys
import time
from collections import deque
from pathlib import Path

from paxos import essential
from paxos.essential import ProposalID

# ---------------------------------------------------------------------------
# Py3 sentinel for None comparisons in essential.py
# ---------------------------------------------------------------------------

NEG_INF = ProposalID(-1, "")


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _ser(v):
    """JSON-serializable form for Paxos types."""
    if isinstance(v, ProposalID):
        return None if v == NEG_INF else [v.number, v.uid]
    if isinstance(v, (set, frozenset)):
        return sorted(_ser(x) for x in v)
    if isinstance(v, (list, tuple)):
        return [_ser(x) for x in v]
    if isinstance(v, dict):
        return {k: _ser(val) for k, val in v.items()}
    return v


def _ts():
    """Real epoch timestamp in nanoseconds (never synthetic)."""
    return time.time_ns()


# ---------------------------------------------------------------------------
# Trace writer
# ---------------------------------------------------------------------------

class TraceWriter:
    """Writes NDJSON to a single file. Thread-safe via GIL (single-threaded
    simulation, but the mutex pattern is documented for Category A)."""

    def __init__(self, path):
        self._f = open(path, "w")

    def write_config(self, config: dict):
        line = {"tag": "config", "ts": _ts(), "config": config}
        self._f.write(json.dumps(line) + "\n")

    def emit(self, name: str, nid: str, archetype: str, state: dict,
             msg: dict | None = None):
        """Emit one trace event.

        Args:
            name:      Spec action name (must match Trace.tla exactly).
            nid:       Node/role UID (maps to TLA+ identifier).
            archetype: Role class ("Proposer", "Acceptor", "Learner").
            state:     Post-state snapshot (written variables after the action).
            msg:       Incoming message fields, or None for self-initiated actions.
        """
        event = {
            "name":      name,
            "nid":       nid,
            "archetype": archetype,
            "state":     {k: _ser(v) for k, v in state.items()},
        }
        if msg is not None:
            event["msg"] = {k: _ser(v) for k, v in msg.items()}
        line = {"tag": "trace", "ts": _ts(), "event": event}
        self._f.write(json.dumps(line) + "\n")

    def close(self):
        self._f.flush()
        self._f.close()


# ---------------------------------------------------------------------------
# State snapshots (post-state after each action)
# ---------------------------------------------------------------------------

def state_proposer(p) -> dict:
    return {
        "proposal_id":     p.proposal_id,
        "proposed_value":  p.proposed_value,
        "last_accepted_id": p.last_accepted_id,
        "promises_rcvd":   sorted(list(p.promises_rcvd or [])),
    }


def state_acceptor(a) -> dict:
    return {
        "promised_id":    a.promised_id,
        "accepted_id":    a.accepted_id,
        "accepted_value": a.accepted_value,
    }


def state_learner(l) -> dict:
    return {
        "final_proposal_id": l.final_proposal_id,
        "final_value":       l.final_value,
    }


# ---------------------------------------------------------------------------
# Network — in-memory message bus with optional fault injection
# ---------------------------------------------------------------------------

class Network:
    """Collects outbound messages from Messenger calls, delivers them on drain."""

    def __init__(self, drop_ids=None, duplicate_ids=None, reorder_fn=None):
        self.queue         = deque()
        self.acceptors     = {}
        self.proposers     = {}
        self.learners      = {}
        self._counter      = 0
        self._drop         = set(drop_ids or [])
        self._dup          = set(duplicate_ids or [])
        self._reorder      = reorder_fn
        self._capture      = None

    def register(self, role: str, uid: str, obj):
        getattr(self, role + "s")[uid] = obj

    def start_capture(self):
        self._capture = []

    def end_capture(self):
        cap, self._capture = self._capture, None
        return cap or []

    def enqueue(self, msg: tuple):
        mid = self._counter
        self._counter += 1
        if self._capture is not None:
            self._capture.append(msg)
        if mid in self._drop:
            return
        self.queue.append((mid, msg))
        if mid in self._dup:
            self.queue.append((mid, msg))
        if self._reorder is not None:
            self.queue = self._reorder(self.queue)


# ---------------------------------------------------------------------------
# HarnessMessenger — implements Messenger interface externally
# ---------------------------------------------------------------------------

class HarnessMessenger(essential.Messenger):
    """Implements cocagne's Messenger by routing messages through Network."""

    def __init__(self, owner_uid: str, network: Network,
                 acceptor_uids: list, learner_uids: list):
        self.uid          = owner_uid
        self.net          = network
        self.acceptors    = acceptor_uids
        self.learners     = learner_uids

    def send_prepare(self, proposal_id):
        for a in self.acceptors:
            self.net.enqueue(("prepare", self.uid, a, proposal_id))

    def send_promise(self, proposer_uid, proposal_id, previous_id, accepted_value):
        self.net.enqueue(
            ("promise", self.uid, proposer_uid, proposal_id, previous_id, accepted_value)
        )

    def send_accept(self, proposal_id, proposal_value):
        for a in self.acceptors:
            self.net.enqueue(("accept", self.uid, a, proposal_id, proposal_value))

    def send_accepted(self, proposal_id, accepted_value):
        for ln in self.learners:
            self.net.enqueue(("accepted", self.uid, ln, proposal_id, accepted_value))

    def on_resolution(self, proposal_id, value):
        # Resolution is captured as a field in the final HandleAccepted state;
        # no separate spec action for it.
        pass


# ---------------------------------------------------------------------------
# TracedLearner — Py3 fix for None comparison in essential.Learner
# ---------------------------------------------------------------------------

class TracedLearner(essential.Learner):
    """Replaces None-sentinel comparisons with NEG_INF for Python 3."""

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
        assert accepted_value == t[2], "Value mismatch for single proposal!"
        t[0] += 1
        t[1] += 1
        if t[0] == self.quorum_size:
            self.final_value       = accepted_value
            self.final_proposal_id = proposal_id
            self.proposals         = None
            self.acceptors         = None
            self.messenger.on_resolution(proposal_id, accepted_value)


# ---------------------------------------------------------------------------
# Action emitters — one function per spec action
# ---------------------------------------------------------------------------

def emit_prepare(tw: TraceWriter, net: Network, proposer):
    """Spec action: Prepare — proposer broadcasts prepare(proposal_id)."""
    net.start_capture()
    proposer.prepare()
    net.end_capture()           # discard; network state is in net.queue
    tw.emit(
        name="Prepare",
        nid=proposer.proposer_uid,
        archetype="Proposer",
        state=state_proposer(proposer),
        msg=None,               # self-initiated, no inbound message
    )


def emit_handle_prepare(tw: TraceWriter, net: Network, acceptor, uid: str,
                        from_uid: str, proposal_id):
    """Spec action: HandlePrepare — acceptor processes prepare message."""
    net.start_capture()
    acceptor.recv_prepare(from_uid, proposal_id)
    net.end_capture()
    tw.emit(
        name="HandlePrepare",
        nid=uid,
        archetype="Acceptor",
        state=state_acceptor(acceptor),
        msg={"from_uid": from_uid, "proposal_id": proposal_id},
    )


def emit_handle_promise(tw: TraceWriter, net: Network, proposer,
                        from_uid: str, proposal_id,
                        prev_accepted_id, prev_accepted_value):
    """Spec action: HandlePromise — proposer processes promise message."""
    net.start_capture()
    proposer.recv_promise(from_uid, proposal_id, prev_accepted_id, prev_accepted_value)
    net.end_capture()
    tw.emit(
        name="HandlePromise",
        nid=proposer.proposer_uid,
        archetype="Proposer",
        state=state_proposer(proposer),
        msg={
            "from_uid":          from_uid,
            "proposal_id":       proposal_id,
            "prev_accepted_id":  prev_accepted_id,
            "prev_accepted_value": prev_accepted_value,
        },
    )


def emit_handle_accept(tw: TraceWriter, net: Network, acceptor, uid: str,
                       from_uid: str, proposal_id, value):
    """Spec action: HandleAccept — acceptor processes accept request."""
    net.start_capture()
    acceptor.recv_accept_request(from_uid, proposal_id, value)
    net.end_capture()
    tw.emit(
        name="HandleAccept",
        nid=uid,
        archetype="Acceptor",
        state=state_acceptor(acceptor),
        msg={"from_uid": from_uid, "proposal_id": proposal_id, "value": value},
    )


def emit_handle_accepted(tw: TraceWriter, net: Network, learner, uid: str,
                         from_uid: str, proposal_id, value):
    """Spec action: HandleAccepted — learner processes accepted message."""
    net.start_capture()
    learner.recv_accepted(from_uid, proposal_id, value)
    net.end_capture()
    tw.emit(
        name="HandleAccepted",
        nid=uid,
        archetype="Learner",
        state=state_learner(learner),
        msg={"from_uid": from_uid, "proposal_id": proposal_id, "value": value},
    )


# ---------------------------------------------------------------------------
# Network drain (message dispatch loop)
# ---------------------------------------------------------------------------

def drain(tw: TraceWriter, net: Network):
    """Deliver all queued messages, emitting one trace event per delivery."""
    while net.queue:
        _mid, msg = net.queue.popleft()
        kind = msg[0]
        if kind == "prepare":
            _, from_uid, to_uid, pid = msg
            emit_handle_prepare(tw, net, net.acceptors[to_uid], to_uid, from_uid, pid)
        elif kind == "promise":
            _, from_uid, to_uid, pid, prev_id, prev_val = msg
            emit_handle_promise(tw, net, net.proposers[to_uid],
                                from_uid, pid, prev_id, prev_val)
        elif kind == "accept":
            _, from_uid, to_uid, pid, val = msg
            emit_handle_accept(tw, net, net.acceptors[to_uid], to_uid, from_uid, pid, val)
        elif kind == "accepted":
            _, from_uid, to_uid, pid, val = msg
            emit_handle_accepted(tw, net, net.learners[to_uid], to_uid, from_uid, pid, val)


def drain_one(tw: TraceWriter, net: Network):
    """Deliver a single queued message (used for interleaved scenarios)."""
    if not net.queue:
        return
    saved = net.queue
    net.queue = deque([saved.popleft()])
    drain(tw, net)
    net.queue.extendleft(reversed(list(saved)))


# ---------------------------------------------------------------------------
# Cluster factory helpers
# ---------------------------------------------------------------------------

def make_acceptor(uid: str, net: Network, acceptor_uids: list, learner_uids: list):
    a = essential.Acceptor()
    a.messenger      = HarnessMessenger(uid, net, acceptor_uids, learner_uids)
    a.promised_id    = NEG_INF
    a.accepted_id    = NEG_INF
    a.accepted_value = None
    net.register("acceptor", uid, a)
    return a


def make_proposer(uid: str, net: Network, quorum: int,
                  acceptor_uids: list, learner_uids: list):
    p = essential.Proposer()
    p.messenger        = HarnessMessenger(uid, net, acceptor_uids, learner_uids)
    p.proposer_uid     = uid
    p.quorum_size      = quorum
    p.last_accepted_id = NEG_INF
    p.promises_rcvd    = set()
    net.register("proposer", uid, p)
    return p


def make_learner(uid: str, net: Network, quorum: int,
                 acceptor_uids: list, learner_uids: list):
    l = TracedLearner()
    l.messenger   = HarnessMessenger(uid, net, acceptor_uids, learner_uids)
    l.quorum_size = quorum
    net.register("learner", uid, l)
    return l


def setup_cluster(n_acceptors=3, n_learners=1, quorum=2, **net_kwargs):
    """Create a fresh cluster and return (net, acceptor_uids, learner_uids)."""
    net = Network(**net_kwargs)
    A   = [f"a{i+1}" for i in range(n_acceptors)]
    L   = [f"l{i+1}" for i in range(n_learners)]
    for u in A:
        make_acceptor(u, net, A, L)
    for u in L:
        make_learner(u, net, quorum, A, L)
    return net, A, L


# ---------------------------------------------------------------------------
# Scenarios (4 total: normal + 3 fault/edge cases)
# ---------------------------------------------------------------------------

def scenario_happy(tw: TraceWriter):
    """
    Normal single-proposer path:
      p1 prepares → acceptors promise → p1 reaches quorum → accept → accepted.
    Covers: Prepare, HandlePrepare, HandlePromise, HandleAccept, HandleAccepted.
    """
    net, A, L = setup_cluster()
    tw.write_config({"acceptors": A, "learners": L, "quorum_size": 2})
    p1 = make_proposer("p1", net, 2, A, L)
    p1.set_proposal("foo")
    emit_prepare(tw, net, p1)
    drain(tw, net)


def scenario_duel(tw: TraceWriter):
    """
    Two competing proposers (p1 then p2 with a higher ballot):
      p1 prepares, p2 interrupts mid-phase1 with higher proposal number.
    Exercises ballot preemption; p2 wins.
    """
    net, A, L = setup_cluster()
    tw.write_config({"acceptors": A, "learners": L, "quorum_size": 2,
                     "scenario": "duel"})
    p1 = make_proposer("p1", net, 2, A, L)
    p2 = make_proposer("p2", net, 2, A, L)
    p1.set_proposal("foo")
    p2.set_proposal("bar")
    emit_prepare(tw, net, p1)
    # Deliver a few messages, then let p2 interject
    for _ in range(3):
        if not net.queue:
            break
        drain_one(tw, net)
    emit_prepare(tw, net, p2)
    drain(tw, net)


def scenario_message_loss(tw: TraceWriter):
    """
    Drop promise msg #1 and accepted msg #6.
    Proposer must still reach quorum from the remaining acceptors (quorum=2).
    Exercises resilience to message loss.
    """
    net, A, L = setup_cluster(drop_ids=[1, 6])
    tw.write_config({"acceptors": A, "learners": L, "quorum_size": 2,
                     "dropped_msg_ids": [1, 6]})
    p1 = make_proposer("p1", net, 2, A, L)
    p1.set_proposal("foo")
    emit_prepare(tw, net, p1)
    drain(tw, net)


def scenario_late_promise(tw: TraceWriter):
    """
    One promise arrives after the others (reordered to the back of the queue).
    Proposer reaches quorum on the first two; the late promise is processed
    after accept/accepted have already been sent.
    """
    moved = {"done": False}

    def reorder(q):
        if moved["done"]:
            return q
        for i, (_mid, m) in enumerate(q):
            if m[0] == "promise":
                item = q[i]
                del q[i]
                q.append(item)
                moved["done"] = True
                break
        return q

    net, A, L = setup_cluster(reorder_fn=reorder)
    tw.write_config({"acceptors": A, "learners": L, "quorum_size": 2,
                     "scenario": "late_promise"})
    p1 = make_proposer("p1", net, 2, A, L)
    p1.set_proposal("foo")
    emit_prepare(tw, net, p1)
    drain(tw, net)


SCENARIOS = [
    ("happy",        scenario_happy),
    ("duel",         scenario_duel),
    ("loss",         scenario_message_loss),
    ("late_promise", scenario_late_promise),
]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    traces_dir = Path(os.environ.get("TRACES_DIR",
                                     "artifacts/essential_paxos/traces"))
    traces_dir.mkdir(parents=True, exist_ok=True)

    for i, (name, fn) in enumerate(SCENARIOS, start=1):
        path = traces_dir / f"trace_{i:02d}_{name}.ndjson"
        tw = TraceWriter(path)
        try:
            fn(tw)
        finally:
            tw.close()
        n_lines = sum(1 for _ in open(path))
        print(f"[run.py] wrote {path}  ({n_lines} events)", file=sys.stderr)


if __name__ == "__main__":
    main()
