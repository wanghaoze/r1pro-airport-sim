# One structural withdrawal candidate and one bounded feedback combination

Source: frozen v21 geometry case 310 final push frame 2278. Entry qualification remains terminal-interval reconstruction without an independent recorded final state; neighbor frames2275/2276 qpos/qvel errors zero. Original controller's .30/.45/.60 paths all fail duration before motion (3.05/3.05/3.10 seconds vs2.90 available). No height/timing/threshold scan.

## Sole structural candidate, no feedback

The original four points' point1 and point2 have exactly equal free-arm references, including gripper columns. Point1 contains an artificial held-arm joint blend; point2 contains a true held-hand IK midpoint. Keep original points[0,2,3] without altering any values. This preserves the exact free-clearance waypoint and both endpoints while eliminating the artificial retained-hand reversal.

Original Blended native duration3.021012 becomes2.457410 seconds; normal rounding selects2.50 movement seconds plus0.10 verification. Right joint4 jerk-only requirement falls2.918184 to2.371890 seconds; left joint4 velocity requirement falls3.021009 to2.457408. The same original full plan, camera, normal, ID and runtime checks pass. Push, release and retreat run, but final `push_accuracy_not_met` persists: position error8.203mm and equivalent yaw+2.202deg individually pass; reserved gap to future slot2 is-1.960mm and footprint overlaps that reservation. This candidate alone is NOT a success. Whole local operation19.10 seconds. Push2.60-second support81.3846%, force peak51.9013N, longest missing8ms.

## Exactly one combination with existing production feedback

Same entry and same three-point structure, frozen v24b production feedback enabled with existing placement scope, time1.50s, gain2, cap1.50deg and additive fallback. No change to other source configuration, physical model, guards or goals. At1.50s yaw error+1.009373deg yields command-1.50deg, leaving1.00s of original2.50s motion. Original quintic rejects `exact_joint_limit`; same-endpoint additive accepts with116/8192 certificate nodes and v/a/j upper-limit ratios .812174/.973517/.881369. Additive planning .82147 wall seconds.

Complete local push/release/retreat/verify passes. Final position error8.029mm, equivalent yaw+1.237deg, reserved gap4.668mm, no future-slot overlap, hand forceszero and four table contacts. Push remains2.60s counted; full local18.30 simulation seconds,28.20 wall seconds. Physical force peak57.211N and longest absence8ms show microbounce is not solved. This is a local accepted operation, not a complete Episode. Evidence preserves original duration failures, structural-only final failure and combined positive result.

Production implementation is default off and separately tested; frozen releases were not edited. Private scripts: diagnose_push_duration.py, diagnose_withdraw_merge.py, diagnose_withdraw_merge_feedback.py and diagnose_withdraw_feedback_runner.py.


## Frozen v26 production verification

Release `robust_v26_20260929`, frozen SHA `0ae13ba4bbafdc103eeabc8ee03005fa8214df7bb5d187965ef591e70315e714`, ran the production merge implementation without the private knot-deletion monkeypatch. The only source-config changes enabled the existing withdrawal search, new merge flag, and unchanged placement yaw/additive configuration. Same frame2278 reconstructed boundary and same qualification.

Events verify: original .30 Blended3.05s duration rejection, .45 Blended3.05s and .60 Blended3.10s rejections, then exactly ONE `push_withdraw_merge_fallback` accepted at unchanged frame2278, retaining[0,2,3]. No planning invariant event occurred; complete integration/base/deadline/warmstart snapshots did not falsely reject. Push movement2.50s plus0.10 verification=2.60s. Original yaw quintic rejects exact_joint_limit; additive is accepted with116/8192 nodes and unchanged derivative bounds, planning wall .61846s.

Full local push/release/retreat/verify succeeds in18.30 simulation seconds (21.254 wall seconds). Final position error8.029mm, equivalent yaw+1.237degrees, slot_geometry_ready true, zero hand forces/four table contacts. The complete9150-row force CSV is byte-identical to the earlier private combined positive run, so the production structure and snapshot guards preserve that physical continuation. Force peak57.211N and8ms maximum missing support remain unchanged. This does not establish complete Episode success. `v26_310_production_merge_feedback/production_verification.json` records event counts and byte identity; all original and negative results are preserved.
