# v40 subdivision 16-scene prefix audit

Read-only snapshot at 2026-09-30 03:56 UTC from frozen server release `robust_v40_20260930`, using `runs/control_deploy_20260930/audit_v40_subdivision_prefix.py`. This is a **running prefix**: the root status is `running`, neither v40 group has `evaluation_summary.json`, and scene 42 has only its first attempt so far. Do not interpret the current counts as budget-closed rates.

| Group | Scenes with results | Actual completed scenes | Coupled-IK terminal scenes (current last attempt) | Coupled interval events |
|---|---:|---|---|---|
| closed v38 same 16 | 16 | 4, 7, 82, 310 | 9, 54, 15, 18, 23, 27, 30, 50, 155 | feature absent |
| closed v39 same 16 | 16 | 4, 7, 82, 310 | 9, 54, 15, 18, 23, 27, 30, 50, 155 | feature absent |
| v40 subdivision, running | 16 | 4, 7, 82, 310 | 9, 54, 15, 18, 23, 27, 30, 50, 155 | 0 accepted, 27 rejected; each depth 4 |
| v40 refit + subdivision, running | 16 | 4, 7, 82, 310 | 9, 54, 15, 18, 23, 27, 30, 50, 155 | 0 accepted, 27 rejected; each depth 4 |

For both v40 groups, 27 emitted `cartesian_coupled_interval_subdivision` events record `qualified=false`, each with four interval halvings, for 108 recorded halvings per group. No saved event shows a successful split route or a changed terminal coupled-IK outcome. Scene 42 has so far shifted from the closed references' `contact_handoff_aborted` to `ik_unreachable` at attempt 0, after two rejected split events; later attempts are pending, so this is not a final regression conclusion. The event count is a count of saved trace events, not a claim that every private failed probe emitted a public event. No Episode was started by this audit.
