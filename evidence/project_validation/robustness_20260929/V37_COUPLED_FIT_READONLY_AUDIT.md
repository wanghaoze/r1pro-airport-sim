# v37 coupled IK fit: read-only eight-case audit

The frozen `robust_v37_20260929` stratified run used the predeclared eight v36 placement failures (15, 18, 23, 27, 30, 42, 50, 155). Seven still terminate in `coupled_ik_unreachable` on their last attempt; case 42 instead reaches a later physical `contact_handoff_aborted` with `retained_contact_lost`. These eight are an enriched development set, not a 400-scene rate estimate. Source: server `releases/robust_v37_20260929/runs/ik_orientation_stratified_20260930/priority/attempts`. Extractor: `runs/control_deploy_20260930/audit_v37_pair_fit.py` (read-only event/result parsing).

| Scene | Terminal max TCP position | Terminal max TCP orientation | Best screened base by position, with orientation <=.12 and rigid position <=.015 |
|---|---:|---:|---:|
| 15 | 87.926 mm | .11191 rad | 80.220 mm / .09019 rad / 8.915 mm rigid |
| 18 | 83.322 mm | .10573 rad | 80.992 mm / .08787 rad / 9.002 mm rigid |
| 23 | 87.086 mm | .10672 rad | 80.754 mm / .09353 rad / 8.974 mm rigid |
| 27 | 83.444 mm | .08686 rad | 82.124 mm / .08205 rad / 9.127 mm rigid |
| 30 | 90.435 mm | .10686 rad | 81.829 mm / .08634 rad / 9.160 mm rigid |
| 50 | 94.418 mm | .12158 rad | 82.841 mm / .10044 rad / 9.206 mm rigid |
| 155 | 88.778 mm | .11069 rad | 81.151 mm / .09519 rad / 9.018 mm rigid |

Each arrival screen evaluated 18 bases. Eight or nine per case reached the coupled solver; the other bases failed the original collision or camera guard. Several alternatives reduce position at the expense of exceeding the .12 rad orientation or 15 mm rigid limits. For example, case 18 at base `[.32,-.56474,0]` has 76.280 mm position but .13331 rad orientation, while another base has 80.992 mm and .08787 rad. Case 27's 71.744 mm alternative has .13369 rad orientation and 16.711 mm rigid error. These are tradeoffs between distinct bases, not evidence that one feasible joint configuration exists at any one base. The terminal fits' rigid position errors are about 9–10.5 mm and branches about .09–.17 rad, well below their 15 mm and .65 rad limits.

`Runtime.solve_pair` starts the coupled least-squares fit from exactly one independently solved left/right arm vector. It gives both TCP positions unit weight, rotations weight .4, implied payload position disagreement weight 3, rotation disagreement weight .6, and reference displacement weight .002; it permits at most 60 function evaluations. Unlike the independent solves, it does not keep multiple coupled seeds or compare feasible coupled candidates. Changing the orientation acceptance limit from .05 to .12 also changes which independent candidate is fed to this single coupled fit. This explains how v36's rejected fitted output could be under 80 mm but v37's newly selected fit can be over 80 mm; it does not prove that the old v36 fit would meet .12 rad on the same v37 query.

Proposed bounded v39 experiment: preserve the entire existing solve and any accepted answer first. Only after a completion-profile, non-retained, two-hand **coupled** rejection where position is over 80 mm and orientation/rigid/branch remain otherwise close, retry the same query in a private kinematic data copy from two deterministic seeds: the original coupled fitted vector and the independent combined vector. Use a positional-priority objective (e.g. rotation coefficient .25 instead of .4), keeping rigid terms and hard bounds unchanged, at most two additional 60-evaluation solves. Score candidates by hard feasibility first, then original normalized residual score; return only if every existing position, rotation, rigid, branch, joint, collision and wrist criterion passes. The fit itself is only a waypoint proposal. Existing continuous-path validation and full physical Episode still decide success. Log each tried weight/seed, CPU time, residuals and why rejected. Do not globally widen 80 mm or .12 rad: case 15 misses by only .220 mm, but other cases miss by 1–3 mm and no currently saved trace proves feasible configurations exist.

No production code or physical run was changed for this audit.
