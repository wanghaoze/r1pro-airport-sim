# v35 case4 orientation-policy regression

Read-only actual a000 comparison, frozen v35 release vs orientation. release completes; orientation ends contact_handoff_aborted / primitive_postcondition_failed. Config differs in two fields: completion_held_ik_orientation_tolerance_rad .05 vs .12, and completion_release_replan_enabled True vs False. Do not label this a globally single-variable experiment.

Exact H5 comparison: action first difference row2469; base_action2502; qpos/qvel/integration_state2470. Thus the entire physical prefix before op3 lift is identical, despite the config difference. First two operations choose the same nominal lift paths. No release-replan physical divergence precedes the lift branch.

At frame2469 op3 tray0/slot2:
- release rejects inward0,+.02,-.02,+.04 because left rotation errors .06150,.05197,.06052,.06214rad exceed .05; it then selects inward-.04 and commands .20m lift.
- orientation accepts inward0 immediately, command .18m, including held_ik_orientation_outside_strict_contract evidence. It never reaches the old feasible -.04 alternative. Final push ends2.55s with left19.948/right22.752N, table1, tilted tray and stable_frames0.

The single-query strict-seed preference is working as designed, but cannot preserve strict paths across geometric candidates. Enlarging each query makes an earlier candidate qualify, changing the entire later physical history. The evidence establishes the first branch cause; no counterfactual rerun has been performed to prove restoring the lift alone fixes every later difference.

Small bounded design: for a lift with orientation policy enabled, run the complete existing geometric candidate selection at the original .05 orientation ceiling first (retain the explicitly selected position ceiling, existing nominal/extended duration policy, all rigid/collision/branch rules). If any full path qualifies, execute it unchanged. Only if the complete original search fails without any physical step, rerun a bounded candidate pass with the declared orientation ceiling. A failed Cartesian query does not contain a complete reusable path, so this second pass must re-solve rather than treating incomplete points as valid. Fixed local RNG makes repeated queries deterministic; execution references and live integration must remain unchanged and original primitive deadline must not reset. Record first-pass failure and second-pass selection, with CPU/probe count and planning-only warning semantics. Do not catch executed lift or push failures.

The broader placement policy would need equivalent whole-plan boundaries encompassing existing reference/arrival alternatives; adding relaxation at a low-level first failing query again would not preserve higher-level alternatives. v36 keeping .05 until a bounded whole-search policy is tested avoids this known regression.

Inputs: runs/repair_20260929/v35_orientation_case4.json and v35_orientation_prefix.py. No production changes or additional physical simulation.
