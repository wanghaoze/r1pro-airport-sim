# v18 feedback case 5 op4: free-arm rise 10 cm versus 8 cm

The operation is confirmed by its frozen events as retained-contact pushing with `free_retreat=True` and `withdraw_free=True`. The specification's 10 cm constraint refers to gripper opening; no acceptance condition requires the free TCP to rise exactly 10 cm. That rise is a trajectory geometry target. This private candidate changes only `p[2]+=.10` to `p[2]+=.08` in the frozen push function; the 6 cm horizontal withdrawal, original posture, feedforward, timing and all physical/camera/collision/dynamic/force checks remain unchanged.

| Private variant | Cruise required time | Blended required time | Available motion time | Result |
|---|---:|---:|---:|---|
| Original 10 cm | 5.70 s | 3.00 s | 2.90 s | Rejected before motion |
| Sole 8 cm candidate | 5.55 s | 2.95 s | 2.90 s | Rejected before motion |
| Subsequently authorized 6 cm candidate | 5.50 s | 2.95 s | 2.90 s | Rejected before motion |

The original reproduces the frozen event's two required durations exactly. The 8 cm candidate saves one 20 Hz frame for the faster path but remains one frame over budget. A subsequently authorized single 6 cm candidate has the same 2.95 s fastest duration, so this direction has plateaued. No motion, release, retreat or final acceptance was executed after these rejections. Neither candidate proves actual clearance because duration rejection occurs before downstream path validation. No height below 6 cm was tested; this direction was stopped as instructed. No production code was changed.

## Terminal-state reconstruction limitation

The zero-motion push begins at frame 3285, whereas raw1 contains states only through frame 3284. The first read correctly refused to index beyond the trace and executed no motion. The diagnostic then reconstructs the missing entrance by replaying the last **completed** 25-substep interval using the logged action/base-action and the frozen controller's exact actuator mapping. Before doing this, it validates the same reconstruction on intervals 3282 and 3283: reconstructed control arrays and next-frame qpos/qvel match exactly with zero error. State 3285 itself has no independent recorded endpoint, so it is identified as a deterministic reconstruction, not a directly recorded state. Reproducing the original exact planning rejection provides an additional consistency check.

The runner also refuses an incomplete terminal interval and requires the actual per-substep control journal for raw2, never a constant-control approximation. These restoration steps are private evidence reconstruction, not changes to a collection or resets during candidate execution.
