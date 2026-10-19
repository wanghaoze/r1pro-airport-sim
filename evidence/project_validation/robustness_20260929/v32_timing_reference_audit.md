# v32 5-second timing audit (actual first attempts)

Read-only comparison of frozen v30b completion_smoke and v32 retry_timing_development. No simulation run or source change. Same source scene IDs; v32 ik22 configuration changes from completion_first are primitive_seconds 3 -> 5 and max_attempts_per_scene 1 -> 3. This audit only considers a000, not retry-selected successes.

| Scene | v30b | v32 ik22 | v32 ik40 |
|---|---|---|---|
| 4 | complete 152.15s | complete 156.20s | complete 156.60s |
| 7 | complete 196.85s | complete 192.90s | push_accuracy_not_met 150.35s |
| 310 | complete 163.85s | release_not_verified 76.40s | same failure 76.40s |

## Confirmed unconditional reference change

Frozen primitives.py lines 465-467 passes remaining budget minus settle to retime_push_to_budget. Lines 194-212 stretch every shorter accepted path to that available duration. In scene310 op1 the same 42-frame minimum plan changes from 2.9s execution to 4.9s; op2 the same 37-frame plan does likewise. Actual H5 proves all action rows before index530 identical to v30b; first different action is index530, first different qpos/qvel/integration/base_state is531. v32 ik22 and ik40 have identical entire 1528-row action/base_action/base_state/qpos/qvel/integration datasets. Thus the first physical difference is the alignment reference, not relaxed IK.

Scene310 op2 baseline aligned tray XY [.8459271303,.3884647546]; v32 [.8440726910,.3889912060]. XY feedforward and opening therefore change. Baseline descent/release 1.45/.95s succeeds. v32 original descent planning rejects cartesian_collision_or_wrist, chooses saved-alignment reference, then executes 1.35/.95s. It waits another54 frames (2.7s) but remains stable_frames0, right force1.084246N, left0, table_contact4. This is actual incomplete release, not a new descent stretched to five seconds. The causal first divergence is proven; whether preserving old align alone restores the entire episode still needs a fresh run.

## Other budget-dependent choices

Scene4 retains completion despite align 2.9 -> 4.9s. Scene7 ik22 also completes and saves correction travel: op2 lift changes2.25 ->4.0s; subsequent align4.9s/place2.5s replaces baseline alignment, zero-motion failed place, arrival correction, second alignment and place. Lift loops geometric inward candidates and stops at first feasible: plan chooses shortest path for each candidate, not across all geometric candidates. A larger limit can therefore accept an earlier slower candidate. Scene7 ik40 already has a different first lift (1.65 vs1.45s); its later push_accuracy failure cannot be attributed solely to timing because ik22 completes.

## Bounded proposed fix review

For completion-only opt-in retiming, target_frames = min(available_frames, max(planned_frames, legacy_reference_frames)) preserves old2.9s align/push references when their old plan fit, and never compresses a newly feasible3.4s plan to2.9s. Retain existing target<=planned early return and inverse-dynamics checks. Compute legacy frames using original three-second budget minus the same configured settle reserve, with the same frame floor as old code; do not hardcode58 if fps/settle can differ. Actual deadline remains5s, leaving extra room for genuine new paths or release waiting. Log requested available, legacy cap and chosen actual frames. This directly targets the proven earliest difference in310, but is not a complete preservation of old3s candidate ordering. A later separate design can exhaust original-budget geometric candidates before expanded-budget ones, only before motion; it must not catch physical execution failure or reset controller state.

No claim that slower references are universally better/worse, or that the proposed fix has already restored an episode.
