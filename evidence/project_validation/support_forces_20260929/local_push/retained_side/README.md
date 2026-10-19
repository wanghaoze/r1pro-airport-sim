# v11 case 5: private retained-side swap

Restored the exact last placement entry at frame 2418, before release, with the recorded INTEGRATION state, warm start, preceding command targets, base targets and actual two-handed gripping. The command grasp relationship is reconstructed and the original placement function re-estimates it before planning, as in the source. No physical state or target is altered by the candidate except the retained-side selection.

The original right-side continuation reproduces every recorded action/qpos/qvel with zero error. It completes placement, then reproduces the original `retained_contact_lost` failure 2.70 seconds into push (4.95 seconds from placement entry). The raw1 terminal post-step state is absent, so the terminal endpoint is not claimed as independently exact.

The sole candidate changes the private placement function's `keep` choice from right to left; the original release and free-arm withdrawal algorithms then operate on the opposite arms. Placement completes in the same 2.25 seconds. Actual table contact count is four, retained left grip force is 13.040 N and released right grip force is zero.

The subsequent push is rejected **before any push motion** by the original `cartesian_collision_or_wrist` check. Its planned robot_geom_45 intersects tray_2__tray_contact_004 by 14.784 mm; reported wrist optical-forward dot products are -0.1532/-0.1562, also outside the original camera guard. These are planned invalid configurations, not executed collisions. No constraint, timing budget or goal was changed to bypass them. Because planning stops here, no final push/yaw/release/verification result exists for this candidate.

Conclusion: merely swapping the retained side is not feasible at this case's existing stance and placement. A side choice would need joint feasibility screening of the corresponding release, free-arm escape and push before committing to it. This single local failure does not establish a universal right/left advantage. Both variants remain failed local continuations, not full Episode successes.

Evidence subdirectories contain summary, events, private placement source and small force CSV files. Force/support averages covering placement include the intentionally airborne carried phase and must not be mistaken for push-support stability metrics. No production or frozen release was edited.
