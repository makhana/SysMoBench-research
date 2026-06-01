#!/usr/bin/env python3
"""Validate freshly generated essential_paxos Category A NDJSON traces."""

import argparse
import json
from collections import Counter
from pathlib import Path


EXPECTED_ACTIONS = {
    "Prepare",
    "HandlePrepare",
    "HandlePromise",
    "HandleAccept",
    "HandleAccepted",
}


def validate_file(path):
    timestamps = []
    actions = Counter()
    lines = path.read_text().splitlines()
    if not lines:
        raise ValueError("%s is empty" % path)
    for line_number, line in enumerate(lines, start=1):
        record = json.loads(line)
        if record.get("tag") != "trace":
            raise ValueError("%s:%s missing trace tag" % (path, line_number))
        timestamp = record.get("ts")
        if not isinstance(timestamp, int) or timestamp <= 0:
            raise ValueError("%s:%s has invalid real timestamp" % (path, line_number))
        timestamps.append(timestamp)
        event = record.get("event", {})
        action = event.get("name")
        if action not in EXPECTED_ACTIONS:
            raise ValueError("%s:%s has unexpected action %r" % (
                path, line_number, action))
        for field in ("nid", "state", "msg", "reads", "writes"):
            if field not in event:
                raise ValueError("%s:%s missing event.%s" % (
                    path, line_number, field))
        actions[action] += 1
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise ValueError("%s timestamps are not strictly increasing" % path)
    if len(timestamps) > 2 and all(
            right - left == 1 for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("%s timestamps look synthetic" % path)
    return len(lines), actions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("traces_dir", type=Path)
    args = parser.parse_args()

    paths = sorted(args.traces_dir.glob("trace_*.ndjson"))
    if len(paths) < 5:
        raise SystemExit("expected at least 5 traces, found %s" % len(paths))

    total_lines = 0
    all_actions = Counter()
    for path in paths:
        line_count, actions = validate_file(path)
        total_lines += line_count
        all_actions.update(actions)
        print("%s: %s events" % (path.name, line_count))

    missing = EXPECTED_ACTIONS - set(all_actions)
    if missing:
        raise SystemExit("target actions absent from traces: %s" % sorted(missing))
    print("validated %s traces, %s events; coverage=%s" % (
        len(paths), total_lines, dict(sorted(all_actions.items()))))


if __name__ == "__main__":
    main()
