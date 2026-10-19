# Historical v4 versus current-code v24b baseline regression audit

## Denominators and provenance

Historical frozen `coverage_v4_20260928/runs/firstpass`:22/400 complete physics successes. Current-code `robust_v24b_20260929/runs/fresh_verification/baseline`:6/62; additive:17/62. Of the historical22 successes, current baseline retains5 and additive retains10. The same-code development baseline is NOT historical v4 behavior and must not be described as the original v4 baseline. These are different controllers/configurations and unequal overall evaluated populations.

The original/current common config keys have identical values, including criteria, physical/action limits and fixed primitives. However baseline explicitly enables NEW `reachability_screen_enabled=True` and `release_preflight_enabled=True`; v4 lacks both. Most new control options are off. Baseline versus additive differs in four feature keys: withdrawal path search, yaw feedback, additive fallback (all false→true), and retreat_joint_speed_scale(1→.5). Thus additive's incremental result is not a pure yaw-only comparison. Complete raw config diff:config_diff.csv/audit.json.

All22 scene specs equal after removing the provenance-only xml_sha256. XML differences are relative asset paths caused by deeper output directories; after normalizing file paths and hashing the actually referenced592 asset files across both releases, all22 normalized XML/asset descriptions match exactly. Source manifest SHA is identical18a00bc5eaca8f8a94ba98da54a59b7bdfb16173fe3fc213f8da3d9b67e003b9. Each frozen runtime/primitives/machine/geometry/trajectory/camera_guard source matches its run's recorded dependency hash. Both recorded environments are MuJoCo3.13.0, NumPy2.2.6, SciPy1.15.3. See provenance_and_aligned.json and environment_and_guards.json.

## What changed versus what did not

**Planning/reference changes, not physical/final acceptance relaxations:**

- Runtime.cartesian now unconditionally adds half-v/a/j reference headroom to all successful empty-arm joint shortcuts; v4 used max(.15,1.875*distance/speed) before ordinary joints timing. This is the proven FIRST divergence in case60.
- Supported-push IK now requires world-normal error<=.25mm and increases normal objective weight5→20. This can change subsequent contact trajectories, but it is NOT the first divergence in case60 and cannot alone be blamed from this audit.
- Placement descents now target staged XY and horizontal orientation with geometry-based touchdown; independently planned transport alignment may run before formerly combined descent. Release opening/budget/verification planning changed. These occur later than the case60 failure and cannot explain its initial divergence.
- Empty-arm endpoint IK fallback and new optional screening can change feasible path selection. Static robot-table planning collision now honors planner_margin_m where the old branch only rejected penetration below-.2mm. This is a planning boundary correction, not a changed actual penetration acceptance.
- New reachability/release preflights are explicitly active in the baseline. In case60, reachability finds zero qualified alternatives on both calls, so original candidate0 is still chosen and the new screen does not explain the first action difference.

**Unchanged acceptance/physical guards:** geometry.py and camera_guard.py are byte-identical; trajectory.py also byte-identical. Runtime.guard, check_retained_contact, camera_guard and _ik_tolerances have identical ASTs. Criteria values match. Runtime.tick's substep journal branch is disabled for both compared runs; normal per-frame apply_target→mj_step→mj_forward sequence is retained. No evidence supports attributing these17 historical failures to a newly stricter retained-contact guard.15 are actual table0 under the same retained guard, one is original primitive postcondition and one is final push accuracy.

## Earliest historical regression: case60

The first action difference is frame158(7.90s), APPROACH_TRAY/pregrasp. qpos/qvel/tray poses/contact forces/table contacts at that entry are EXACTLY equal. Action first differs by1.29342079e-4; qpos first differs at159. Both pick original candidate0 with identical base/heading and both report free_space_joint_shortcut discarding6 intermediate IK points.

The old shortcut executes158→195(37frames); new executes158→219(61frames). Endpoint action at old194/new218 is EXACTLY equal: this is the same solved endpoint with changed timing, not evidence of a new IK destination. A second pregrasp shortcut similarly adds24frames, so separation push begins old377 versus new425. Frozen source's added half-v/a/j duration calculation is the concrete path source for this first divergence. Reachability preflight has no qualified candidate and both follow the same base route.

By aligned push entry, joint state differs~.000992rad and reference~.001003rad; tray poses only~2.02e-7 max component. Both choose Blended2.45s motion with identical nominal separation goal up to numeric settling differences. Old completes2.55s push; new hits retained_contact_lost1.50s into it(table0, grip10.8205N). Later supported-normal IK and changed starting state also affect the push; read-only evidence identifies the causal first divergence but does not isolate which downstream change causes the final failure. Restoring only the old empty-arm timing as a controlled fresh comparison is warranted; no final guard needs weakening.

## Candidate lost successes176/300

Baseline versus additive first action differences are frame1011(50.55s) for176 and983(49.15s) for300, both PLACE_TRAY/retreat after the first placement. These are before later failing push feedback and coincide with retreat_joint_speed_scale1→.5. qpos first changes one frame later. Thus neither lost success may be assigned solely to yaw/additive without separating the retreat-scale confound. Root has assigned a separate same-code retreat-scale1 test; this audit did not rerun episodes.

## Historical22 outcome table

|Case|v4|current baseline|additive|
|---:|---|---|---|
|4|success|success|success|
|16|success|retained_contact_lost / table0|success|
|24|success|retained_contact_lost / table0|retained_contact_lost / table0|
|60|success|retained_contact_lost / table0|retained_contact_lost / table0|
|80|success|success|success|
|132|success|retained_contact_lost / table0|success|
|147|success|push_accuracy_not_met|retained_contact_lost / table0|
|152|success|retained_contact_lost / table0|retained_contact_lost / table0|
|156|success|retained_contact_lost / table0|retained_contact_lost / table0|
|160|success|retained_contact_lost / table0|retained_contact_lost / table0|
|176|success|success|retained_contact_lost / table0|
|188|success|retained_contact_lost / table0|retained_contact_lost / table0|
|236|success|retained_contact_lost / table0|success|
|240|success|retained_contact_lost / table0|success|
|256|success|retained_contact_lost / table0|success|
|276|success|success|success|
|288|success|retained_contact_lost / table0|retained_contact_lost / table0|
|292|success|retained_contact_lost / table0|success|
|300|success|success|retained_contact_lost / table0|
|304|success|primitive_postcondition_failed|retained_contact_lost / table0|
|344|success|retained_contact_lost / table0|retained_contact_lost / table0|
|364|success|retained_contact_lost / table0|success|

Nested distribution: {"baseline": {"success": 5, "retained_contact_lost / table0": 15, "push_accuracy_not_met": 1, "primitive_postcondition_failed": 1}, "additive": {"success": 10, "retained_contact_lost / table0": 12}}

Evidence is read-only: no frozen/source/collection modification, no whole-episode rerun, no H5 downloads. H5 was read in64-row blocks only until the first differing row, plus a few aligned phase boundary rows. Original raw hashes, context, nested failure details and unified frozen source diffs remain in this directory.
