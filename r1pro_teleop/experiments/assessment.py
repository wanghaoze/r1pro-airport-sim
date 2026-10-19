"""Persistent assessments: evidence and rejected hypotheses, not just a score."""
from datetime import datetime, timezone
from pathlib import Path
import json
import uuid

from .common import read
from ..airport_fsm.contracts import atomic_json


def assess(root, *, observation, evidence, hypothesis, next_action, outcome, run=None):
    if outcome not in ("ok", "partial", "failed", "crashed", "inconclusive"):
        raise ValueError("invalid_assessment_outcome")
    fields = dict(observation=observation, evidence=evidence, hypothesis=hypothesis, next_action=next_action)
    if any(not isinstance(v, str) or not v.strip() for v in fields.values()):
        raise ValueError("assessment_requires_evidence_and_next_action")
    directory = Path(root) / "assessments"
    directory.mkdir(parents=True, exist_ok=True)
    row = dict(fields, outcome=outcome, run=run, time=datetime.now(timezone.utc).isoformat())
    path = directory / (uuid.uuid4().hex + ".json")
    atomic_json(path, row)
    return row


def history(root):
    return sorted((read(p) for p in (Path(root) / "assessments").glob("*.json")), key=lambda r: r["time"])


def failure_chain(code, events):
    """Unwrap structured fault evidence without interpreting exception strings.

    A handoff wrapper can contain a zero-motion planning rejection. Keep the
    wrapper and the underlying reason separate so it is not mislabeled as a
    physical loss of grip. Successful results do not inherit old retry faults.
    """
    if not code:
        return []
    chain = [code]
    event = next((e for e in reversed(events)
                  if e.get('event') in ('operation_failed','primitive_failed')
                  and e.get('reason') in (None, code)), None)
    detail = event.get('detail') if event else None
    for _ in range(8):
        if not isinstance(detail, dict) or not isinstance(detail.get('reason'), str):
            break
        reason = detail['reason']
        if reason != chain[-1]:
            chain.append(reason)
        detail = detail.get('detail')
    return chain


def diagnose(collection, output):
    """Read existing collections only; preserve nested causes and stage evidence."""
    from collections import Counter
    rows = []
    for path in sorted(Path(collection).glob("attempts/*/*/result.json")):
        result = read(path)
        events_path = path.with_name("events.jsonl")
        events = []
        if events_path.exists():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a concurrently running writer may have a partial last line
                if event.get("event") in ("operation_failed", "primitive_failed", "candidate_rejected", "state_transition"):
                    events.append(event)
        chain = failure_chain(result.get('failure_code'), events)
        rows.append({"path": str(path.resolve()), "scene_id": result["scene_id"],
                     "attempt": result.get("attempt", 0),
                     "physics_success": result.get("physics_success", False),
                     "task_completed": result.get("task_completed", result.get("physics_success", False)),
                     "strict_success": result.get("strict_success", result.get("physics_success", False)),
                     "acceptance_profile": result.get("acceptance_profile", 'strict'),
                     "acceptance_deviations": result.get("acceptance_deviations", {}),
                     "recovery_used": bool(result.get('recovery_used',False)),
                     "diagnostic_only": bool(result.get('diagnostic_only',False)),
                     "failure_code": result.get("failure_code"), "error": result.get("error"),
                     "failure_chain": chain, "underlying_failure_code": chain[-1] if chain else None,
                     "simulation_seconds": result.get("simulation_seconds"), "last_events": events[-12:]})
    clean = [r for r in rows if r['physics_success'] and not r['recovery_used'] and not r['diagnostic_only']]
    from ..airport_fsm.completion import outcome_counts
    report = {**outcome_counts(rows), "attempts": len(rows), "successes": sum(r["physics_success"] for r in rows),
              "clean_complete_successes": len(clean),
              "attempted_scenes":len({r['scene_id'] for r in rows}),
              "clean_successful_scenes":len({r['scene_id'] for r in clean}),
              "qualification":"Task completion uses the declared acceptance profile; strict clean success is separate. Attempt counts and unique-scene coverage differ; recovered/diagnostic results are not clean successes.",
              "failures": dict(Counter(r["failure_code"] for r in rows if not r["physics_success"])),
              "underlying_failures": dict(Counter(r["underlying_failure_code"] for r in rows if not r["physics_success"])),
              "rows": rows}
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    atomic_json(output, report)
    return report
