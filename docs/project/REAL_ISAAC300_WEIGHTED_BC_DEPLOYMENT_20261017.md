# Real / Isaac 300 duration-weighted BC deployment

Verified 2026-10-17. Server root `B=/home/michelle/haoze/r1pro-airport-sim`.

## Actual deployment

- Frozen code: `B/releases/real_isaac300_timeweighted_training_20261017_v3`; SHA inventory `release_identity.json`.
- Run: `B/runs/real_isaac300_timeweighted_pi05_20261017_v1`.
- Guard PID 2020466 / start_ticks 43087432; supervisor PID 2020468 / start_ticks 43087434, both cwd B. These are a launch snapshot, not a perpetual liveness claim.
- Actual stage at deployment: `waiting_for_data`, training_started=false, completed updates=0. No GPU initialization or gradient smoke has been performed.
- Receipts: `deployment_receipt.json`, `guard_identity.json`, `guard_status.json`, `supervisor_attempt_0.launch.json`; logs `guard.log`, `supervisor_attempt_0.log`; progress `pipeline_status.json`.
- Separate guard actual-waits supervisor and bounds restarts to three attempts with backoff. Supervisor and training have separate single-instance locks; children have stage runner actual-wait receipts and PID/start/argv/cwd checks. Data production terminal failures are exposed as blocked_by_data_generation, not training.

## Conditional flow and source identity

New production manifest `B/runs/isaacsim_parallel_pickplace300_20261017_v1/dataset_v1/manifest.json`, minimum 300 complete native pairs / 600 Pick+Place clips. Old 59 pairs are not included in that threshold. Full source_room paths disambiguate repeated room numbers. Native exit, trace/result/video hashes, four original cameras and complete pair audit are verified before caching.

Flow: freeze 300 → sim uint8/FP32 cache → train-only normalization and exact balanced schedule → CPU official transforms check → dual-GPU 10/100/1000/10000 updates and saved checkpoints → real held-out 19-episode offline MSE. Native Isaac model rollout remains pending and is not represented by this MSE.

Real cache `B/runs/real_sim_pickplace_20261009_v3/cache` preserves train102/val13/test19; dataset+raw_file_name sets were actually checked disjoint. Manifest SHAs:

- train `a2ad881b010d357d201bd7e729885c6a108185fd18a75d370251be3f1a79b03f`
- val `4bfa3a37c82a5c6d311528f2b7cdac575528cb19884b5c7ffdd4933d1c9707f6`
- test `cd2e935be3dcb01bbfba09c886da0fa93d85ecf125f35c49ba84ee0ff452120c`

Parent status `B/runs/afford_pi05_pickup120_20261008_v2/pi05/training_status.json` points to actual checkpoint `B/runs/afford_pi05_pickup120_20261007_v1/pi05/checkpoints/pi05_pickup120/training/9999`. Its comparison-specific stage=trained, updates=10000, declared run/spec and positive finite parameter norm were checked; all 17 parameter files were SHA hashed. New optimizer, not parent optimizer, is used. Actual optimizer updates remain untested until the data gate opens.

## Method

Duration-weighted sampling BC, **not RL**: within each domain/action, each source receives clip(median training-source duration / duration, 0.5, 2); frames receive source_weight/number_of_frames. Each batch has real2Pick+2Place and sim2Pick+2Place. Full clips remain intact. No val/test durations enter weights or normalization. Equal three-second clips receive equal weights; this does not demonstrate a faster learned controller.

Sim measured base state is rebased to the episode's actual first native feedback; submitted base actions become zero hold, matching existing real cache semantics. Joint radians and gripper meters are preserved. Original trace and station command remain unchanged, with mapping in cache episode metadata. Three policy RGB inputs follow existing real camera names; all four native videos remain source evidence.

Cache estimate for 36,000 frames: 16,257,024,000 RGB bytes (~15.14 GiB), plus numeric data and metadata. Real cache is reused through paths/symlinks. Parent parameter files total ~5.45 GB; checkpoints additionally contain optimizer state and require further disk reserve.

## Executed tests and retained failures

Five local weighting/schedule tests passed, including shorter-source total probability, exact domain/action counts and train-only rejection. CPU smoke `B/runs/real_isaac300_timeweighted_adapter_smoke_20261017_v2`: 2 previously closed complete pairs / 4 clips / 240 frames; prepare actual exit 0. Official openpi normalization/model transforms and Observation construction passed on real first frame and sim first/terminal frames: actions [20,32], state [1,32], three images [1,224,224,3]. No model initialized, no gradients executed. It is explicitly not part of the formal 300 data.

Earlier smoke_v1 failures remain: generic airport serve verifier rejected comparison status schema; subsequent transform check exposed incompatible state_semantics text. Fixed by explicit comparison-parent evidence validation and matching the existing base-origin-offset semantic token with additional reference metadata. v3 also enforces dataset+raw_file_name split identity. Original failed logs and earlier releases remain intact.

Offline MSE output contract was inspected: `mse_parallel_real50_duration_bc.json`, real_test_episode_holdout=true, base_channels_excluded=true, per-action and episode error fields. This is a contract check, not a completed MSE result.
