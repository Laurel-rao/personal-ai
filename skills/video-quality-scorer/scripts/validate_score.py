#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


WEIGHTS = [25, 15, 15, 15, 10, 10, 5, 5]
NON_PASS = {"fail", "unverified"}


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def main():
    parser = argparse.ArgumentParser(description="Validate video quality score JSON")
    parser.add_argument("score_json", type=Path)
    args = parser.parse_args()

    data = json.loads(args.score_json.read_text(encoding="utf-8"))
    gate = data.get("story_gate") or {}
    status = gate.get("status")
    beats = gate.get("beats") or []
    score = data.get("score") or {}
    dimensions = data.get("dimensions") or []

    if status not in {"pass", "fail", "unverified"}:
        return fail("story_gate.status must be pass, fail, or unverified")
    if not beats:
        return fail("story_gate.beats must not be empty")
    if any(beat.get("status") not in {"pass", "fail", "unverified"} for beat in beats):
        return fail("every story beat needs a valid status")
    if len(dimensions) != 8:
        return fail("exactly eight dimensions are required")
    if [item.get("weight") for item in dimensions] != WEIGHTS:
        return fail(f"dimension weights must be {WEIGHTS}")

    raw_sum = round(sum(float(item.get("weighted_points", 0)) for item in dimensions), 6)
    if abs(raw_sum - float(score.get("raw", -1))) > 1e-6:
        return fail(f"score.raw {score.get('raw')} does not equal dimension sum {raw_sum}")

    if status in NON_PASS:
        expected_cap = "story_contract_failed" if status == "fail" else "story_contract_unverified"
        if score.get("final", 100) > 49:
            return fail("non-passing story gate must cap score.final at 49")
        if score.get("decision") != "regenerate":
            return fail("non-passing story gate must set decision=regenerate")
        if expected_cap not in (score.get("caps_applied") or []):
            return fail(f"missing cap {expected_cap}")
        if gate.get("veto_applied") is not True:
            return fail("non-passing story gate must set veto_applied=true")
    elif gate.get("veto_applied") is not False:
        return fail("passing story gate must set veto_applied=false")

    print(f"OK: {args.score_json} story_gate={status} raw={score.get('raw')} final={score.get('final')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
