# v21 geometry case310 final push: sole8cm free-hand-rise candidate

Source: `robust_v21_20260929/runs/ablation/geometry`, frame2278, operation3, tray0, retainedright. One private process at a time, with BLAS/OMP thread counts1. Production and frozen release unchanged.

Original10cm-rise control first reproduces the zero-motion duration rejection: .30/.45/.60 retained-knot progress needs3.05/3.05/3.10s via BlendedJointPath, against the unchanged2.90s motion allowance. No path executes.

The sole candidate changes only free-hand vertical rise10cm→8cm. Backward withdrawal remains6cm, retained-hand goals and all original checks/budgets unchanged. The already-enabled frozen path search still tries the original bounded .30/.45/.60 alternatives; no new search values are introduced.

| Free-hand rise | .30 path duration | .45 | .60 | Physical execution |
|---|---:|---:|---:|---|
|10cm original|3.05s|3.05s|3.10s|None|
|8cm sole candidate|3.00s|3.00s|3.05s|None|

The best path improves by50ms but still exceeds2.90s, so `primitive_path_infeasible` remains. No push, release, retreat or verification occurs; no local physical success is claimed. There is no6cm candidate or further scan. Original/candidate planning wall times are .537/.594s.

Entry frame2278 is absent as a terminal recorded state. It is reconstructed by replaying the last completed interval using the original schema/control semantics. Two neighboring intervals2275/2276 reproduce qpos and qvel with exactly zero error. The reconstructed entry matches the original frozen planning rejection, but the terminal endpoint is not independently recorded; summary therefore correctly does not claim an independently exact terminal trajectory. It has4 actual table contacts, retained grip13.3059N and released hand0N.

Both subdirectories preserve summary, complete events and any generated private candidate source. The authoritative bounded search durations are in `push_withdraw_path_search`; summary reports the original .30 rejection. Direction stopped with no production change.
