"""Prevent implementation changes from silently leaving the shared spec stale."""
from scripts.sync_task_spec import DOC, START, END, render


def test_task_spec_matches_implementation():
    text = DOC.read_text(encoding="utf8")
    assert text.split(START, 1)[1].split(END, 1)[0] == render(), (
        "Review SCENE_TASK_SPEC.md workflow and change log, then run "
        "python scripts/sync_task_spec.py --write"
    )
