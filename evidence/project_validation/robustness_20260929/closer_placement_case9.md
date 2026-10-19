# Bounded closer-base negative diagnostic

Source: v30b completion_full400 case9 a000 terminal. Evaluator: frozen v33 production placement predictor. No mj_step/tick or fresh Episode. One CPU, 4.78s total. Detailed records: runs/repair_20260929/closer_placement_probe.jsonl.

Terminal snapshot records only qpos/qvel/time; these were restored exactly (qpos max error0), other integration fields from final stored row. Bilateral measured force after forward13.594/13.333N. Controller grasp_rel is not stored and was explicitly rebuilt from measured terminal TCP. Thus this is an assumption-qualified kinematic prediction, not exact original planning or dynamic replay. Source qpos unchanged at end.

For each 22mm and80mm held position ceiling, original18 candidates:9 coupled IK rejects+9 collision/camera rejects. Additional9: nominal yaw at .47m and.45m with lateral0/+5/-5cm (6), measured-payload-compatible heading at.47m with same lateral offsets(3). All9 rejected:6 coupled IK,3 robot/table collision. Orientation ceiling .05rad and original relative rigidity/branch/collision/camera gates unchanged. No full align/descent/release qualified.

At80mm, closest nominal yaw candidate .45m,-5cm has L48.47mm/R58.46mm, orientation .06298/.05540rad, rigid7.748mm/.02407rad, branch.08465rad. Position and relative rigidity pass; common absolute wrist orientation remains the rejected condition. Payload heading alternatives collide robot_geom_11/front_right table by55.67/20.98/7.02mm. Do not propose these as navigable bases.

Independent current v34 actual audit: case9 combined/direct_combined a000 position44.31/59.10mm but orientation.06552/.05592rad, rigid6.567mm/.02129rad. Lift-only variant position53.52/68.12mm, orientation.10448/.08717rad, rigid9.81mm/.03490rad. This supports isolating an explicit held-orientation planning policy rather than continuing to raise position ceilings. It does not prove that an orientation-relaxed path executes or finishes the task. Case6 latest actual failures have progressed to push_accuracy, so no extra closer-base scan was run for it.

No new candidate policy is recommended from this all-failed scan; avoid extending the search indefinitely. The newly authorized v35 orientation candidate requires actual complete execution with existing contacts/rigidity/final placement checks.
