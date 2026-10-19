# v21 direct-place hypothesis: bounded read-only audit

Source: frozen `robust_v21_20260929/runs/ablation/geometry`. Production, release_location's65mm blocker rule, runtime guards and physical collections unchanged. No physical candidate was executed.

## Case6

The failed first operation actually selected **width** rims, not the new length-rim family: half_span.205m, edge_half_length.27m, candidate face-.502879rad. Destination is `[.85,-.501724,.801]`, staged position `[.85,-.396724,.801]` (105mm offset). Original recorded place completes in2.65s; its left-retained push fails after1.15s with table0 and force11.4705N.

At the recorded pre-alignment entry frame542, measured tray center is `[.758078,-.201785,.960005]`; left/right TCP positions are `[.757038,.004067,1.038344]` and `[.738267,-.409551,1.061549]`. The hands remain approximately opposite in worldY, so the proposed length-family sideways-release explanation does not apply.

For the unchanged operation destination, tray-footprint blockers with zero added margin are empty; the65mm-expanded query returns tray1. That establishes conservatism relative to tray footprint only, not clearance of actual fingers or wrist bodies. Neighbor tray1 is at `[.770407,-1.122566,.799995]` with yaw approximately-120degrees.

One private frozen `qualify_placement` prediction, from the recorded entry at unchanged base pose and with staged=destination, fails `ik_unreachable` for the left arm (27.857mm position error, .046738rad rotation error). It cannot authorize execution. This is a kinematic prediction rather than an independently exact original place re-execution; no physical motion occurs. Because IK rejects before full release-path qualification, the audit **does not claim an actual hand-neighbor collision has been proven**. It equally provides no safe geometric basis for bypassing staging. Original recorded events remain the control reference.

## Additional permitted read-only cases

Case218's staged operations use width rims. Case7's final retained push (op3/tray2) uses the original short/width template. Case7 does have a length-rim pickup in op2, but it is a rear temporary placement with `retained_side=None`, and no corresponding retained push is logged. It therefore does not demonstrate the hypothesized unnecessary retained push caused by a length-rim release direction.

No qualifying alternate-rim example was selected for a new physical experiment, and no broader scan was performed. Evidence: `v21_case6_direct_geometry.json` and `v21_other_rims.jsonl`. Read-only scripts: `inspect_v21_case6_release.py`, `inspect_v21_case6_direct_geometry.py`, `inspect_v21_other_rims.py` under scripts and server diagnostictools.
