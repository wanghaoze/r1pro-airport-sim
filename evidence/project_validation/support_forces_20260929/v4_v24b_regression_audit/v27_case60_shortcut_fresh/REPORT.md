# v27 case60 complete fresh Episode and first substantive differences

Frozen controller: robust_v27_20260929, SHA 485b5d47fa239cf5f402cd5d87e3676e125e4e9d7627b760576339eb067275cb. Collection: diagnostictools/support_forces_20260929_v1/v27_case60_shortcut_fresh. One selected preflight, one attempt, one worker. This is a fresh complete Episode, not restored local success.

Result: FAILED contact_handoff_aborted / retained_contact_lost, tray0/right/table0/grip10.8388349 N. 2679 frames, 133.90 s recorded simulation, Episode wall229.786 s; selected preflight10.824 s. Historical v4 was complete success145.35 s; v24b same-code baseline failed22.75 s. No success claim is justified for v27.

## Prefix restored by timing switch

Both normal empty-arm shortcuts exactly recover old37-frame intervals158→195 and239→276. First push starts377 and completes428 (2.55 s) in both. Action arrays match exactly through377; first difference378 is5.96e-8. This does not remain mere stored float32 rounding: first push max command difference4.059e-5 rad, max qvel difference0.286277, max tray_pose component difference0.000474617. New supported IK normal weight20 versus historical5 is active at this first push; this is a planning/reference policy change, not a changed measured contact guard. No isolated causal physical test has yet been run for that policy.

## First explicit geometric reference difference

At frame820 both start first place. Historical noncombined descent retains measuredXY/tilt, target[0.8515376733,0.3768985504,0.8020253049]. Current targets horizontal tray at[0.85,0.38,0.797]. Descent1.85→1.90 s; old then waits2 support frames, new immediately opens at858. Thus first phase difference857 originates here. Old place completes878, new877; later retreat/verification makes second operation begin993/994. Current prior placed tray positions differ by up to2.660mm by third operation.

## Third operation aligned comparison

Old direct closure preflight rejects at2214; new geometry closure preview passes2216. Old then withdraws/reapproaches, current directly approaches. Same lift candidate inward−0.06m, same1.45 s lift, same staging[.85,−.615,.8]. Compare old2661/current2582 before place: target tray COM differs only[2.04,1.24,−2.31]µm; largest arm command difference0.1068mrad. Current independent alignment planning rejects with no motion and uses original combined descent.

Both combined descents target[.85,−.615,.797] and last1.5 s. Historical combined retained-contact release commands free left gripper0.10m, current minimal release approximately0.0381924m. Opening lasts1.4 versus0.8 s, total place2.9 versus2.3 s. At next push old2719/current2628, target tray COM differs[−2.44,−3.89,+1.14]µm, min_z0.305µm; both table8, right contact13.31495 versus13.30567 N. Arm command difference≤0.1472mrad, but free gripper command differs61.8076mm. Thus withdrawal starts from materially different free-hand aperture despite nearly identical loaded tray pose.

Historical push completes2.9 s; current fails at2.5 completed seconds. This supports an isolated reference-geometry candidate, not a claim of sole root cause: retain current minimal-release default, privately compare historical full-open reference only for combined+retained place, with complete original planning,3-second budget, camera/contact/force/dynamics guards, and full local place→push→release→retreat→verify. If infeasible, preserve failure. Do not loosen normal accuracy or real support acceptance. The current normal IK policy remains a confounder and should be isolated separately rather than changed simultaneously.

Evidence: comparison.json, detailed_alignment.json (all original/current events, phase segments and prefix windows), third_stage_comparison.json (exact aligned states). H5 remained server-side. Failure-video agent received actual result path and frozen replay version.

## Approved single-candidate physical isolation: negative

Completed two sequential1-CPU local rollouts from exact recorded frame2582 integration state using frozenv27. Original control reproduced all recorded qpos/qvel/action exactly (max error0) and the same force10.838834912265341 N at retained_contact_lost. Because source ends at failure, endpoint qpos cannot independently compare; recorded-prefix match is exact, not an unqualified whole-endpoint claim.

Only candidate edit was private `_plan_place_descent`: for combined descent with retained hand, set released gripper endpoint to0.10. No controller/config/model file changed. Both descents are identical1.5-second CruiseJointPath. Original opening0.8s gives place2.3s, candidate opening1.4s gives place2.9s. Both following withdrawal push paths are BlendedJointPath planned2.8s plus original verification allowance. Current original fails at2.50 completed push seconds (2.55 physical interval), full-open fails at1.95 completed (2.00 physical interval). Neither reaches final release/retreat/verification; the physical guard terminates them. Candidate ends69.94mm from destination/table0/right11.62214N. Original ends25.05mm/table0/right10.83883N. Final geometry-only booleans are not acceptance success.

Matched first1.95s push contact window (975 real2ms samples): original support89.4359%, peak44.0105N, maxmissing6ms; full-open89.7436%, peak39.3123N, maxmissing4ms. This modest aggregate change does not overcome the20Hz actual support guard; full-open fails earlier. Whole-local statistics include the intentionally airborne descent and must not be used as push support evidence. Exact per-stage events and forces are saved in both directories; matched windows in full_open_contact_windows.json.

Conclusion: reject isolated full-opening restoration for production; no further aperture scan. Historical full-open difference is real but not sufficient cause. All negative evidence retained. This does not prove the supported IK policy is the remaining cause; that still requires a separately authorized controlled comparison.
