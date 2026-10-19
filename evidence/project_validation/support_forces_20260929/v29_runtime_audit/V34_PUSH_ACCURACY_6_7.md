# v34 case6/7 final push accuracy (read-only)

combined and nominal a000 have identical physical outcomes. The frozen implementation emits no failed verify_operation detail event: operation_failed/detail=null. The following is recomputed from the last 41 recorded samples, metadata config/scene, terminal qpos, and the frozen geometry functions, without physics stepping.

|Case|Tray / slot|Position error|Yaw error|Tilt|Forces L/R|Table/support|Speed max (2s tail)|
|---|---|---|---|---|---|---|---|
|6|0 / 1|9.206294 mm|1.873938 deg|0.000019637 deg|0 / 0 N|4 / 4|1.31e-11 m/s|
|7|2 / 1|10.725743 mm|2.884334 deg|0.000019637 deg|0 / 0 N|4 / 4|1.34e-11 m/s|

Both fully released hands measure 80.384/80.442 mm opening. Terminal pose differs from last recorded observation by at most 5.87e-12. Position <=50mm, yaw <=10deg, tilt <=5deg, support, force <=.5N and stationary conditions all pass.

The rejecting condition is reserved future slot2 footprint, not current physical overlap or excessive target error. Mapping case6=[2,0,1], case7=[0,2,1]. Tray1 is not yet placed, so slot_geometry_ready substitutes its nominal future footprint at [.85,-.51,.8]. The newly placed slot1 tray overlaps this reserved rectangle even with zero clearance: largest SAT axis gap case6=-0.846685mm, case7=-5.198897mm. Therefore footprint_neighbour_gaps returns None and the subsequent 2mm reserved-space condition also fails. This is more than the earlier single-axis projection false-negative: the two virtual footprints genuinely intersect.

Actual existing trays do not intersect: neighbor boundary gaps case6=[16.143335,481.505186]mm and case7=[8.894333,1165.352176]mm. The large second gap belongs to the still-unplaced tray and is not itself the operation's deciding test. Neither case is globally complete. A speed-only profile change cannot directly remove this deterministic reserved-footprint rejection on these same states.

No production edits or simulation. Detailed data: v34_push_accuracy_6_7.json.
