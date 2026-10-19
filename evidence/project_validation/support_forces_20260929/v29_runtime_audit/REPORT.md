# v29 completion smoke runtime audit

Source: frozen robust_v29_20260929/runs/completion_smoke; actual completed results only. Detailed evidence: audit.json. No replay, no physics intervention, no collection mutation.

| Case | Task completed | Strict success | Runtime soft evidence | Final outcome |
|---|---|---|---|---|
| 4 | yes | no | One 200 ms sampled support absence; gap 45.833 um | completed |
| 5 | no | no | none | push_accuracy_not_met |
| 6 | no | no | none; 23 geometry predicate deviations | placement_needs_correction |
| 7 | no | no | One 200 ms sampled support absence; gap 13.141 um | push_accuracy_not_met |
| 8 | yes | yes | none | completed |
| 16 | yes | no | Two 200 ms sampled support absences; max gap 62.842 um | completed |
| 218 | no | no | Six speed warnings; peak ratio 1.023733 | illegal_collision |
| 310 | no | no | 17 speed warnings; peak ratio 1.024800; support absence through 300 ms, max gap 28.060 um | push_accuracy_not_met |

Actual completion is 3/8 (37.5%); original strict success is 1/8 (12.5%). These are policy-qualified smoke results, not evidence of 70% on the formal 400 scenes. No completed case with a recorded deviation was labeled strict_success=True.

Support durations refer to 20 Hz observation continuity. Logged table_contact remains zero at warning observations. Micrometer-scale gaps are consistent with intermittent contact but do not prove continuous 500 Hz separation or sampling aliasing. Case 310 continued through exactly the configured 300 ms boundary; no unsupported extension beyond that bound is evidenced.

All speed warning records have excursion_seconds=0: each warning begins a fresh integer-timed excursion after a prior safe substep reset. Warnings can recur every control frame. This does not mean the complete inter-frame interval was always within strict speed; complete duration inference requires substep velocity evidence. No new replay was run.

Remaining hard runtime cause is case 218 illegal_collision. Other four incomplete outcomes are released placement/push final geometry failures. Intermediate primitive_failed records which were handled by existing fallback must not be mistaken for episode termination.

## Proposed bounded continuous correction (not implemented)

An opt-in completion-only helper may authorize the existing local retry for exactly push_accuracy_not_met or placement_needs_correction when there is no holding, retained contact, pending handoff, or active primitive deadline. Original Runtime.guard must run and propagate every hard failure. Require all trays genuinely supported, target actually released, and the existing stable_s observation window stable before retry. Do not recursively unwrap contact_handoff_aborted. Do not treat negative projected gap as success.

Keep total local attempts at min(max_local_retries,3), preserve operation destination, and replan from live observed state. Record the original strict failure permanently and recovery_used. Never restore/rewind/clear timer state. Root integrates a helper at the current run-loop exception boundary; machine.py remains unmodified by this audit. Existing final acceptance remains mandatory. Actual SAT overlap diagnosis is separately owned by reachability.

## Case 218 collision audit

The terminal fault is a real wrong-tray finger collision, not a camera constraint or the previously tolerated speed transient. At frame 3408, retry 1, GRASP_TRAY/close, robot_geom_45 (left_gripper_finger_link1, box half-size 30/5/20 mm) contacts tray_0__tray_contact_012 at signed distance -0.205432 mm. Target is tray 1, slot 2. Original live nonallowed-pair threshold is -0.2 mm and remained enforced.

Planning anticipated exactly this pair: frame 3130 candidate 0 closure at 85 mm predicted -0.212714 mm; actual direct-grasp preflight frame 3199 predicted -0.241767 mm; frame 3238 candidate 0 closure at 88 mm predicted -0.441714 mm. Both reachability screens had no qualified candidates. The fallback returned an original width-rim approach after direct preflight rejection; the generic grasp method executes closure without repeating the same closure preview. This is a fallback coverage gap, not a collision detector failure.

At recorded frame 3407, command opening was 86.348 mm, wrong tray 0 left-finger force 0.245612 N while target tray 1 had zero force on both hands. All trays remained table-supported [4,8,4]. Terminal substep itself is not reconstructed here; terminal penetration is from the original event, not the previous recorded frame (which had max penetration 0.160952 mm).

Earlier retry 0 failed at frame 2976 in ADJUST_TRAY/open on planned tray0/tray1 contact -4.674 um, then existing continuous recovery completed at frame 3130. The final terminal wrong-tray collision occurs after this recovery and distinct regrasp. Do not attribute it directly to earlier overspeed.

Control recommendation: apply the same contact-closure feasibility check immediately before every physical bilateral grasp, including fallback routes; a known blocked closure must route to a genuinely different reachable rim/separation strategy. Merely refusing all unqualified candidates prevents this collision but does not by itself improve task completion. No source change, physical replay, new threshold, or new candidate test was performed.

Evidence: case218_terminal_events.txt and case218_collision_readonly.txt (original frozen XML ancestry, event records, three small H5 slices).

### Why alternate rims did not rescue the grasp

At frame 3238 all 24 bounded probes were rejected: 9 closure collisions, 11 IK-unreachable, 1 IK branch jump, 3 base-configuration collisions. qualified=[] and exhausted=False: the bounded prefix failed, not every possible geometric candidate. The alternating width/length lattice's length candidates 3/5/7/9/11/13/15/17 all failed left-arm IK (position residual roughly 108–273 mm); 19/21/23 failed base configuration collision. Width candidates mostly hit the same neighboring tray during closure; 8/16 instead had roughly 61 mm left IK residual, and 18 had branch jump 0.81661 rad. No already-qualified alternate was discarded.

Later lateral/along-rim offsets remain outside this probe budget. A future bounded, shadow-only additional qualification pass could test a fixed small set when the original pool has no qualified grasp, then require full live checks. There is currently no demonstrated collision-free executable alternative; neither a larger candidate pool nor converting collision to no_feasible_grasp can be advertised as a completion improvement. v30 geometry-only scope therefore remains appropriate.

### Authorized bounded 24-to-48 zero-motion qualification

Frozen v29 frame 3238 was restored from recorded integration state; qpos error and regenerated historical candidate-0 base error were exactly zero. RNG advancement was reconstructed from the five preceding screen calls. Original 24 rejection order/codes matched the recorded screen: 9 closure / 11 IK / 1 branch / 3 base; 7.813 seconds. Expanded first 48 candidates produced no qualified grasp (max_qualified=2): added 24 rejected as 14 IK / 2 base collision / 8 closure collision. Full 48 qualification took 12.776 seconds on one process with BLAS threads restricted to one.

Full live MuJoCo INTEGRATION was unchanged before/after screening, and time remained 161.90000000004494 s. No physical tick or episode was run. The larger prefix provides no evidence for adopting a larger screen budget. Source/config/state hashes and every rejection are in case218_screen48.json; server output is diagnostictools/support_forces_20260929_v1/v29_case218_screen48. Actual earlier 0.205432 mm collision evidence remains unmodified.

## v30b full400 multiple-tray audit

At the read snapshot, 55 actual attempts were complete. All 19 multiple_trays_lifted cases were complex: 0,1,3,84–87,168–171,352–355,396–399. Thus this early failure concentration reflects the complex cases, not a representative ordinary-scene failure rate.

| Case/front_count | Intended/other | Failure seconds | Other baseline min_z m | Other terminal min_z m | Rise mm | Other terminal vz m/s |
|---|---|---|---|---|---|---|
| 0 / 0 | 1 / 0 | 59.276 | .799990222 | .820061311 | 20.071 | +.155400 |
| 1 / 1 | 2 / 1 | 20.726 | .799974046 | .820256872 | 20.283 | +.154555 |
| 3 / 3 | 1 / 0 | 19.678 | .799971882 | .819996065 | 20.024 | +.155224 |

All three lower trays had never been moved by an earlier operation. Case 0 had previously moved only tray 2; cases 1 and 3 failed on their first operation. Their fixed episode baselines are therefore valid. Immediately preceding recorded samples show the unintended lower tray with table_contact=0/support_contact=0 and no hand force; the intended upper tray retains four support contacts with it and approximately 12 N force per hand. Terminal upper-tray vertical speeds are .155565/.154718/.155393 m/s, closely matching the lower tray. The two nested trays are rising together, rather than a stale baseline misclassifying a previously placed tray.

Terminal min_z was calculated using frozen MuJoCo mesh geometry and recorded terminal qpos via matrix transforms only. No MjData, forward call, step, or new rollout was used. Applying the same calculation to the recorded last pose reproduced logged min_z within 1.11e-16 m. The last 20 Hz frame is below 20 mm rise; the recorded terminal substep crosses the threshold. This is real coupled lifting; the original guard should remain hard.

Evidence: v30b_multitray_three.json, v30b_multitray_terminal_geometry.json, v30b_multitray_final_inventory.json. No further probe or code change undertaken.
