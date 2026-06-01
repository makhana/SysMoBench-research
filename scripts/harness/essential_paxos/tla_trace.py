"""Category A NDJSON tracing for the cocagne/paxos essential implementation."""

from __future__ import print_function

import json
import threading
import time
from contextlib import contextmanager


_writer = None
_writer_guard = threading.Lock()
_local = threading.local()


def _ser(value):
    if hasattr(value, "number") and hasattr(value, "uid"):
        return [value.number, value.uid]
    if isinstance(value, (set, frozenset)):
        return sorted(_ser(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [_ser(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _ser(item) for key, item in value.items()}
    return value


def _diff(before, after):
    return {
        key: value
        for key, value in after.items()
        if before.get(key) != value
    }


def proposer_state(proposer):
    uid = proposer.proposer_uid
    return {
        "proposal_id[%s]" % uid: proposer.proposal_id,
        "proposed_value[%s]" % uid: proposer.proposed_value,
        "last_accepted_id[%s]" % uid: proposer.last_accepted_id,
        "next_proposal_number[%s]" % uid: proposer.next_proposal_number,
        "promises_rcvd[%s]" % uid: sorted(proposer.promises_rcvd or []),
    }


def acceptor_state(acceptor):
    uid = acceptor.trace_uid
    return {
        "promised_id[%s]" % uid: acceptor.promised_id,
        "accepted_id[%s]" % uid: acceptor.accepted_id,
        "accepted_value[%s]" % uid: acceptor.accepted_value,
    }


def learner_state(learner):
    uid = learner.trace_uid
    proposals = []
    for proposal_id, state in sorted((learner.proposals or {}).items()):
        proposals.append({
            "proposal_id": proposal_id,
            "accept_count": state[0],
            "retain_count": state[1],
            "value": state[2],
        })
    return {
        "learner_acceptors[%s]" % uid: dict(learner.acceptors or {}),
        "learner_proposals[%s]" % uid: proposals,
        "final_proposal_id[%s]" % uid: learner.final_proposal_id,
        "final_value[%s]" % uid: learner.final_value,
    }


class _TraceWriter(object):
    def __init__(self, out_path):
        self.out = open(out_path, "w")
        self.lock = threading.Lock()
        self.seq = 0

    def emit(self, action, label, pid, archetype, before, after, msg, sent):
        reads = dict(before)
        for key, value in msg.items():
            reads["msg.%s" % key] = value
        writes = _diff(before, after)
        if sent:
            writes["msgs+"] = sent
        event = {
            "seq": self.seq,
            "name": action,
            "action": action,
            "label": label,
            "nid": pid,
            "pid": pid,
            "archetype": archetype,
            "state": _ser(after),
            "msg": _ser(msg),
            "reads": _ser(reads),
            "writes": _ser(writes),
        }
        with self.lock:
            event["seq"] = self.seq
            self.seq += 1
            record = {
                "tag": "trace",
                "ts": time.monotonic_ns(),
                "event": event,
            }
            self.out.write(json.dumps(record, sort_keys=True) + "\n")
            self.out.flush()

    def close(self):
        with self.lock:
            self.out.close()


def start(out_path):
    global _writer
    with _writer_guard:
        if _writer is not None:
            _writer.close()
        _writer = _TraceWriter(out_path)


def stop():
    global _writer
    with _writer_guard:
        if _writer is not None:
            _writer.close()
            _writer = None


def record_message(description):
    frame = getattr(_local, "frame", None)
    if frame is not None:
        frame["sent"].append(description)


@contextmanager
def action(action_name, label, pid, archetype, snapshot, msg=None):
    writer = _writer
    if writer is None:
        yield
        return

    before = snapshot()
    previous = getattr(_local, "frame", None)
    frame = {"sent": []}
    _local.frame = frame
    try:
        yield
    finally:
        after = snapshot()
        _local.frame = previous
        writer.emit(
            action_name,
            label,
            pid,
            archetype,
            before,
            after,
            msg or {},
            frame["sent"],
        )
