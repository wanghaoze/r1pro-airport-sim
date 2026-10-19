# v38 place fallback event audit (read-only)

Source: frozen server `releases/robust_v38_20260930/runs/stage_place_development_16/attempts`, parsed with `runs/control_deploy_20260930/audit_v38_place_events.py`. The table uses the last (`a002`) attempt of seven predeclared v36 coupled-IK failures. No Episode was rerun.

| Scene index | Failed frame | Original place fit: max position / rotation | Private .12 fallback | Actual place motion | Arrival base screen |
|---|---:|---:|---|---:|---|
| 15 | 529 | 36.09 mm / .05175 rad | coupled IK failed | 0 s | 0/18 qualified; 9 IK, 9 collision/camera |
| 18 | 563 | 47.20 mm / .05896 rad | coupled IK failed | 0 s | 0/18; 9 IK, 9 collision/camera |
| 23 | 1042 | 55.39 mm / .05423 rad | coupled IK failed | 0 s | 0/18; 9 IK, 9 collision/camera |
| 27 | 532 | 54.04 mm / .05327 rad | coupled IK failed | 0 s | 0/17; 8 IK, 9 collision/camera |
| 30 | 576 | 62.33 mm / .06165 rad | coupled IK failed | 0 s | 0/18; 9 IK, 9 collision/camera |
| 50 | 455 | 60.25 mm / .06465 rad | coupled IK failed | 0 s | 0/18; 9 IK, 9 collision/camera |
| 155 | 941 | 69.49 mm / .07928 rad | coupled IK failed | 0 s | 0/18; 9 IK, 9 collision/camera |

All seven last attempts emitted `primitive_place_orientation_search` with `selected=null`, `original_reason=coupled_ik_unreachable`, `relaxed_reason=coupled_ik_unreachable`. Thus the private .12 planning fallback **did run**, and its own solver failed. At each failed frame there is no `primitive_descent_geometry` or `primitive_release_plan` event; the rejection happened inside `object_points` Cartesian waypoint generation before the complete descent/release path or any place physics. The wrapper rethrows the original .05 fault, so the table's numerical residuals belong to that **original** fit. v38 does not log the private .12 fit's TCP/rigid/branch numbers. They cannot be inferred from these terminal error details, nor can the exact offending waypoint be recovered from them.

There are zero `place_coupled_position_refit` events because the frozen v38 release does not contain the v39 default-off refit. Earlier operations in cases 23 and 155 did log `selected=original` and proceed physically; this does not change the later failing operation classification. Case 27's first attempt instead reached physical contact handoff failure, while its last two attempts have the place planning failure shown above. The current evidence supports instrumenting and testing v39 on a fresh physical run; it does not show that `.12` or a changed solver weight already solved these seven.
