# Single late-suffix reserve candidate: negative result

One private server process, BLAS/OMP threads each set to1. Frozen v11 case5 final push, exact recorded entry frame2463; original comparison remains `../force_feedback/local_full_push_v11case5_force_baseline`. Production/v21 unchanged.

First1.50s is unchanged; its750 physical force records are exactly identical to the original. At1.50s the sole proposed C2 quintic connects original q/v/a to the unchanged original endpoint with zero terminal v/a. Motion budget increases only within the existing primitive allocation:2.75→2.90s, retaining the original.10s verification reserve. The suffix is accepted by exact derivative/joint bounds, original collision/camera/rigid checks, unchanged normal band [.8984700754,.9034700754]m, and inverse dynamics. Boundary q/v/a errors are0/5.42e-20/5.55e-17; v/a/j limit ratios .2601/.2436/.1258. Planning wall time.881s; entire diagnostic5.004s.

Actual execution fails **earlier**, at2.50s, with `retained_contact_lost`: table contact0, retained force10.7125N, close command0. Original fails at2.70s. The physical guard aborts execution; release, retreat and final acceptance are therefore not reached. No successful local operation is claimed.

| Same0–2.50s window | Original | Candidate |
|---|---:|---:|
| Support fraction |81.68%|82.56%|
| Mean table force |12.2278N|12.3997N|
| Peak table force |45.4149N|49.2063N|
| Longest physical missing support |6ms|8ms|
| Minimum tray-bottom height |.79984324m|.79981346m|

The slight support fraction increase does not overcome the earlier abort, increased force peak and longer real gaps. Candidate rejected; direction stopped with no extra timing or parameter scans.

`comparison.json`, `summary.json`, `events.json`, `forces.csv` and exact private source retain the evidence. The generic reused runner marks `force_feedback_suffix=true` because it uses that private injection hook; **this candidate uses no force feedback**. Its actual implementation is `scripts/diagnostic_suffix_reserve.py`; the authoritative intervention event is `diagnostic_late_suffix_reserve`.
