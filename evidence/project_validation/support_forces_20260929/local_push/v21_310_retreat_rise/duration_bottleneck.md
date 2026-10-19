# Case 310 last push: original path duration bottleneck

Read-only diagnostic of frozen v21 geometry case 310, op3 last push frame 2278. Terminal entry is reconstructed from the last completed control interval, not an independently recorded final state. Neighbor frame 2275/2276 replay qpos/qvel errors are exactly zero. Original retained side is right. No motion is executed: original planner rejects all candidates on duration before geometric/path acceptance. No height scan, limit change, timing change, or production modification.

The diagnostic wraps only original path constructors to report their existing polynomial extrema and limits. Blended derivative extrema are calculated from each derivative polynomial's endpoints and real stationary roots, exactly the analytical procedure used by the original path's duration calculation. No sampled extrema substitute is used. The original .30/.45/.60 search is replayed unchanged; six path records (Cruise and Blended for each) are preserved in `v21_310_duration_audit/path_duration_audit.json`.

| Held midpoint progress | Blended native duration s | Rounded s | Primary limit |
|---|---:|---:|---|
| .30 | 3.021012229 | 3.05 | free left joint4 velocity, segment0 |
| .45 | 3.000646050 | 3.05 | left joint4 velocity; right joint4 segment1 jerk; right joint2 final jerk |
| .60 | 3.056868572 | 3.10 | left joint4 velocity; right joint4 segment1 jerk; right joint2 final jerk |

All exceed the unchanged 2.90-second movement budget. The 20 Hz rounding is not the main obstruction: even their unrounded native duration exceeds 2.90.

For original .30, free left arm joint4 moves -0.3931891024 to -1.1854693901 rad in the first segment, displacement -0.7922802877 rad, and then remains fixed for both remaining segments. Segment0 covers normalized progress [0,.5691337380], with zero endpoint tangent for this joint. Velocity peaks at progress .2845668690, magnitude 2.6101519559 / T rad/s. The unchanged effective joint limit is .864 rad/s, requiring T=3.0210092082 before the original 1.000001 multiplier. At 2.90 seconds velocity would exceed the limit by 4.1727%.

There is an independent held-arm bottleneck: right joint4 final segment jerk peak596.4161928 / T^3 rad/s^3 against24 rad/s^3 requires T=2.9181843774; right joint2 final jerk requires2.9040674128. Thus removing only the left-joint velocity obstruction cannot certify the original curve at2.90.

In .45, three bounds balance around3.0006430493 before the multiplier. At2.90 left joint4 velocity would exceed3.4704%, and worst jerk10.7769%. Right joint4 waypoints are[-.431567997,-.365443541,-.429568085,-.284624761]. The artificial early retained-hand joint blend progresses forward, then returns toward the next actual IK waypoint, then moves forward again. This reversal forces zero tangent at turning points and raises middle-segment jerk. Right joint2 also reverses[-.224151939,-.098730034,-.106247751,.054563406]. Increasing blend to.60 enlarges both reversals and raises duration rather than fixing it.

The free-hand endpoint is unchanged across all three: the initial left joint4 motion must finish early, while retained-hand artificial reversal consumes later time. The obstruction is the shape and shared segment timing of this whole joint curve; it is not proof that no geometrically valid control exists. A future structural candidate would need to retain true free clearance while avoiding retained-hand backtracking and still satisfy all geometry/normal/ID guards. This audit does not test or authorize such a candidate.

Cruise alternatives are considerably more conservative here:6.854938/8.975697/9.064811 seconds (rounded6.9/9.0/9.1), dominated by right joint4 acceleration bounds for .30/.45 and velocity for .60. These are the original Cruise conservative bounds, not a claim that the realized curve's actual maxima attain the bound.

The prior sole 8cm-rise candidate remains a preserved negative result (best3.00>2.90); it was not rerun or expanded. Original source has zero successful physical push frames at this entry.
