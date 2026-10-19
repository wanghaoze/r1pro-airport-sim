# v39 free-first physical comparison

The eight-scene `stage_refit_free_first` development collection is closed on the server: `runner_complete=true`, `selected_stopping_budget_closed=true`, 24/24 actual attempts finished, 5 s configured primitive budget, and **0/8 complete tasks**. This is an actual MuJoCo Episode result, not a planning probe. The corresponding v36 selected attempts were also 0/8 complete. The collection is a selected stress subset of a 400-scene source, so its 0% is **not** a full-400 success rate.

| Scene | v36 final underlying failure | v39 final underlying failure | v39 candidate accepted / rejected / path fallback (all attempts) |
| --- | --- | --- | ---: |
| 0014 | retained support lost | retained support lost | 0 / 3 / 0 |
| 0075 | retained support lost | coupled IK unreachable | 0 / 0 / 0 |
| 0098 | push postcondition failed | push postcondition failed | 3 / 1 / 3 |
| 0102 | retained support lost | retained support lost | 0 / 2 / 0 |
| 0110 | push postcondition failed | retained support lost | 2 / 0 / 0 |
| 0118 | push postcondition failed | retained support lost | 2 / 0 / 0 |
| 0174 | retained support lost | retained support lost | 0 / 2 / 0 |
| 0206 | retained support lost | retained support lost | 0 / 1 / 0 |

There were 7 geometrically accepted free-first proposals across 24 attempts. Three were rejected later by the whole-path validator and **fell back before motion** to the original path (`0098` a000–a002). For `0098` a001, the path review specifically detected a free finger 4.22 mm from the moving-tray sweep boundary, below the required 5 mm, while another path violated a joint limit. Nine proposals were rejected at the bounded geometry step, usually because retreat exceeded 18 cm. Four accepted proposals (`0110` and `0118` a001/a002) reached execution without fallback; all four physically lost table support.

The executed candidate did not prevent free-hand recontact. In `0110` a001/a002, the free right jaw command opened to 0.10 m and right TCP retreated from y≈−0.669 to −0.788 m. Its actual tray contact force first dropped to zero, then rose to 21.2 N as the tray moved; the retained left hand reached 24.8 N, table contacts fell to zero for 0.35 s, and tray center rose from z≈0.800 to 0.836 m. `0118` a001/a002 similarly ended with free-hand force 21.9 N, retained force 26.1 N, no table support for 0.35 s, and center z≈0.838 m. The real contact/support guard correctly rejected these attempts. The planned finger sweep clearance did not predict this dynamic contact; it is a geometric candidate check rather than a guarantee about compliant motion.

Conclusion for this bounded experiment: **the free-first candidate provided no complete-task gain and worsened the terminal failure mode in the two scenes where it executed**. Keep the flag disabled for broad runs. More retreat distance or a looser support/contact threshold is not supported by these traces. A later controller change would need to account for the actual commanded-versus-measured free-hand path and contact force during separation, and be verified on fresh Episodes before use in a full collection.

Evidence: `v39_free_first_evaluation_summary.json`, `v39_free_first_snapshot.json`, `v39_free_first_trace_snapshot.json`; v36 reference: `v36_handoff_audit.json`, `v36_handoff_trace_audit.json`. All trace reads were read-only; no existing server attempt or collection was changed.
