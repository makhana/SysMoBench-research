"""Drive instrumented cocagne/paxos essential roles through trace scenarios."""

from __future__ import print_function

import os
import sys
from collections import deque
from pathlib import Path

from paxos import essential
from paxos import tla_trace


def _ser(value):
    if isinstance(value, essential.ProposalID):
        return [value.number, value.uid]
    if isinstance(value, (list, tuple)):
        return [_ser(item) for item in value]
    return value


def _describe(msg):
    return "%s%s" % (msg[0], tuple(_ser(item) for item in msg[1:]))


class Network(object):
    """In-memory transport with deterministic drop, duplicate, and reorder hooks."""

    def __init__(self, drop_ids=None, duplicate_ids=None, reorder=None):
        self.queue = deque()
        self.acceptors = {}
        self.proposers = {}
        self.learners = {}
        self.resolutions = []
        self.msg_counter = 0
        self.drop_ids = set(drop_ids or [])
        self.duplicate_ids = set(duplicate_ids or [])
        self.reorder = reorder

    def register(self, role, uid, obj):
        getattr(self, role + "s")[uid] = obj

    def enqueue(self, msg):
        message_id = self.msg_counter
        self.msg_counter += 1
        tla_trace.record_message(_describe(msg))
        if message_id in self.drop_ids:
            return
        self.queue.append((message_id, msg))
        if message_id in self.duplicate_ids:
            self.queue.append((message_id, msg))
        if self.reorder is not None:
            self.queue = self.reorder(self.queue)


class HarnessMessenger(object):
    """Concrete transport for the upstream networking-agnostic Messenger API."""

    def __init__(self, owner_uid, network, acceptor_uids, learner_uids):
        self.owner_uid = owner_uid
        self.network = network
        self.acceptor_uids = acceptor_uids
        self.learner_uids = learner_uids

    def send_prepare(self, proposal_id):
        for acceptor_uid in self.acceptor_uids:
            self.network.enqueue(
                ("prepare", self.owner_uid, acceptor_uid, proposal_id))

    def send_promise(self, proposer_uid, proposal_id, previous_id,
                     accepted_value):
        self.network.enqueue(
            ("promise", self.owner_uid, proposer_uid, proposal_id,
             previous_id, accepted_value))

    def send_accept(self, proposal_id, proposal_value):
        for acceptor_uid in self.acceptor_uids:
            self.network.enqueue(
                ("accept", self.owner_uid, acceptor_uid, proposal_id,
                 proposal_value))

    def send_accepted(self, proposal_id, accepted_value):
        for learner_uid in self.learner_uids:
            self.network.enqueue(
                ("accepted", self.owner_uid, learner_uid, proposal_id,
                 accepted_value))

    def on_resolution(self, proposal_id, value):
        self.network.resolutions.append((proposal_id, value))


def make_acceptor(uid, network, acceptor_uids, learner_uids):
    acceptor = essential.Acceptor()
    acceptor.trace_uid = uid
    acceptor.messenger = HarnessMessenger(
        uid, network, acceptor_uids, learner_uids)
    acceptor.promised_id = None
    acceptor.accepted_id = None
    acceptor.accepted_value = None
    network.register("acceptor", uid, acceptor)
    return acceptor


def make_proposer(uid, network, quorum, acceptor_uids, learner_uids):
    proposer = essential.Proposer()
    proposer.messenger = HarnessMessenger(
        uid, network, acceptor_uids, learner_uids)
    proposer.proposer_uid = uid
    proposer.quorum_size = quorum
    proposer.proposed_value = None
    proposer.proposal_id = None
    proposer.last_accepted_id = None
    proposer.next_proposal_number = 1
    proposer.promises_rcvd = set()
    network.register("proposer", uid, proposer)
    return proposer


def make_learner(uid, network, quorum, acceptor_uids, learner_uids):
    learner = essential.Learner()
    learner.trace_uid = uid
    learner.messenger = HarnessMessenger(
        uid, network, acceptor_uids, learner_uids)
    learner.quorum_size = quorum
    learner.proposals = None
    learner.acceptors = None
    learner.final_value = None
    learner.final_proposal_id = None
    network.register("learner", uid, learner)
    return learner


def setup(n_acceptors=3, n_learners=1, quorum=2, **network_options):
    network = Network(**network_options)
    acceptor_uids = ["a%s" % (index + 1) for index in range(n_acceptors)]
    learner_uids = ["l%s" % (index + 1) for index in range(n_learners)]
    for uid in acceptor_uids:
        make_acceptor(uid, network, acceptor_uids, learner_uids)
    for uid in learner_uids:
        make_learner(uid, network, quorum, acceptor_uids, learner_uids)
    return network, acceptor_uids, learner_uids


def dispatch_one(network):
    if not network.queue:
        return
    _, msg = network.queue.popleft()
    kind = msg[0]
    if kind == "prepare":
        _, from_uid, to_uid, proposal_id = msg
        network.acceptors[to_uid].recv_prepare(from_uid, proposal_id)
    elif kind == "promise":
        _, from_uid, to_uid, proposal_id, previous_id, value = msg
        network.proposers[to_uid].recv_promise(
            from_uid, proposal_id, previous_id, value)
    elif kind == "accept":
        _, from_uid, to_uid, proposal_id, value = msg
        network.acceptors[to_uid].recv_accept_request(
            from_uid, proposal_id, value)
    elif kind == "accepted":
        _, from_uid, to_uid, proposal_id, value = msg
        network.learners[to_uid].recv_accepted(from_uid, proposal_id, value)
    else:
        raise ValueError("unknown message kind %r" % kind)


def drain(network):
    while network.queue:
        dispatch_one(network)


def scenario_happy():
    network, acceptors, learners = setup()
    proposer = make_proposer("p1", network, 2, acceptors, learners)
    proposer.set_proposal("foo")
    proposer.prepare()
    drain(network)


def scenario_duel():
    network, acceptors, learners = setup()
    proposer1 = make_proposer("p1", network, 2, acceptors, learners)
    proposer2 = make_proposer("p2", network, 2, acceptors, learners)
    proposer1.set_proposal("foo")
    proposer2.set_proposal("bar")
    proposer1.prepare()
    for _ in range(3):
        dispatch_one(network)
    proposer2.prepare()
    drain(network)


def scenario_loss():
    network, acceptors, learners = setup(drop_ids=[1, 6])
    proposer = make_proposer("p1", network, 2, acceptors, learners)
    proposer.set_proposal("foo")
    proposer.prepare()
    drain(network)


def scenario_late():
    moved = {"done": False}

    def reorder(queue):
        if moved["done"]:
            return queue
        for index, (_, msg) in enumerate(queue):
            if msg[0] == "promise":
                item = queue[index]
                del queue[index]
                queue.append(item)
                moved["done"] = True
                break
        return queue

    network, acceptors, learners = setup(reorder=reorder)
    proposer = make_proposer("p1", network, 2, acceptors, learners)
    proposer.set_proposal("foo")
    proposer.prepare()
    drain(network)


def scenario_duplicate():
    network, acceptors, learners = setup(duplicate_ids=[0])
    proposer = make_proposer("p1", network, 2, acceptors, learners)
    proposer.set_proposal("foo")
    proposer.prepare()
    drain(network)


SCENARIOS = [
    ("happy", scenario_happy),
    ("duel", scenario_duel),
    ("loss", scenario_loss),
    ("late", scenario_late),
    ("duplicate", scenario_duplicate),
]


def main():
    out_dir = Path(os.environ.get(
        "TRACES_DIR", "artifacts/essential_paxos/traces"))
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale_trace in out_dir.glob("trace_*.ndjson"):
        stale_trace.unlink()

    for index, (name, scenario) in enumerate(SCENARIOS, start=1):
        path = out_dir / ("trace_%02d_%s.ndjson" % (index, name))
        tla_trace.start(str(path))
        try:
            scenario()
        finally:
            tla_trace.stop()
        print("[run.py] wrote %s" % path, file=sys.stderr)


if __name__ == "__main__":
    main()
