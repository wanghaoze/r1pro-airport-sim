# v37 original eight: baseline versus 0.12 rad priority

Read-only comparison of fresh v37 `a000` server traces in `robust_v37_20260929/runs/completion_candidates/{baseline,priority}`. `v37_divergence_audit.json` records first differing HDF5 action/state frames and relevant primitive events.

| Case | First differing action / measured qpos frame | Baseline decision | Priority decision | Physical outcome |
| --- | ---: | --- | --- | --- |
| 4 | 2696 / 2697 | `transport_align` deferred on IK; combined descent | 60-frame separate alignment | Both completed, priority used 49 more frames |
| 7 | 476 / 477 | Alignment deferred; combined descent | Separate alignment | Baseline completed; priority later failed push contact handoff |
| 82 | 1371 / 1372 | Alignment deferred; combined descent | Separate alignment | Baseline completed; priority later failed push accuracy |
| 310 | 1900 / 1901 | Alignment deferred; combined descent | Separate alignment | Baseline completed; priority later failed push accuracy |

All earlier actions and measured joint states in each pair agree through the listed action frame. The first divergence is the widened orientation bound allowing an independent alignment plan that 0.05 rad rejected. This changes actual motion and subsequent release/push geometry; these are real control regressions, not merely a scoring difference. Although all 130 v36 terminal coupled-IK residuals fit the proposed 0.12 rad orientation ceiling, isolated v37 `priority` attempts on eight of those cases had no early completion and often returned 83–94 mm coupled position error, above the unchanged 80 mm bound. Widening the bound changes the independent IK seed used for coupled refinement.

The v38 candidate keeps the original 0.05 rad alignment choice. It tries the full original place descent/release reference first, then, only on a zero-motion pure IK rejection, attempts one complete private 0.12 rad reference. Within that private attempt, an independent seed satisfying the old 0.05 rad orientation bound takes precedence if available; the 80 mm position, rigid grasp, branch, collision, camera and physical checks remain authoritative. This is a candidate design awaiting actual Episodes; the comparison above does not establish that v38 restores the old successes or resolves the 130 failures.
