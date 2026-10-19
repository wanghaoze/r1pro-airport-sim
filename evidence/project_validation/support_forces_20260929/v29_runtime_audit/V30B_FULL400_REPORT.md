# v30b full400 final actual outcome audit

Frozen collection: robust_v30b_20260929/runs/completion_full400. Read actual result.json and per-scene source JSON only. All 400 unique registered scenes have one completed actual attempt, a000, under completion_first. No diagnostic or partial result is used. Successful episodes report no recovery.

**Task completed: 170/400 (42.5%). Original strict success: 58/400 (14.5%). The 70% target is not reached.**

| Stratum | Completed | Strict | Total | Task rate |
|---|---:|---:|---:|---:|
| front_count 0 | 87 | 57 | 100 | 87% |
| front_count 1 | 48 | 0 | 100 | 48% |
| front_count 2 | 9 | 0 | 100 | 9% |
| front_count 3 | 26 | 1 | 100 | 26% |
| ordinary | 170 | 58 | 380 | 44.74% |
| complex | 0 | 0 | 20 | 0% |
| train | 135 | 48 | 300 | 45% |
| val | 19 | 6 | 50 | 38% |
| test | 16 | 4 | 50 | 32% |

## Historical v4 comparison

Original coverage_v4_20260928/runs/firstpass contains 22 clean successful scenes. All 22 are retained under v30b task completion; 148 additional scenes complete, and no historical successful scene is lost under this task metric. Fourteen of those 22 retain strict success; eight require the completion profile. Thus this is NOT a controlled estimate of controller improvement: frozen code, planning policies, timing, and acceptance profile differ. Nor can 170 task-completed trajectories be described as 170 original-strict passes.

Historical 22 case indices: 4,16,24,60,80,132,147,152,156,160,176,188,236,240,256,276,288,292,300,304,344,364.

Historical cases still strict: 24,60,80,132,152,176,188,236,276,288,292,300,344,364.

## Remaining actual failure classes

112 coupled_ik_unreachable; 25 contact_handoff_aborted; 19 multiple_trays_lifted; 15 ik_unreachable; 12 no_safe_release_precondition; 10 primitive_lift_path_unavailable; 8 final_physical_acceptance_failed; 6 push_accuracy_not_met; 4 cartesian_collision_or_wrist; 3 each no_supported_airborne_recovery, illegal_collision, primitive_postcondition_failed, placement_needs_correction; 2 each joint_path_collision_or_wrist, no_feasible_grasp_approach, primitive_path_infeasible; 1 carried_payload_support_contact. Total 230 failed scenes.

Evidence: v30b_full400_strata.json contains complete retained/new/lost scene identities, source-backed strata and failure counts; v30b_full400_identity.json verifies attempt/profile/strict/recovery semantics. Existing collections and physics were not modified or rerun.
