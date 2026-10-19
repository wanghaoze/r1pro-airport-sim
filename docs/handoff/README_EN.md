# R1Pro Airport Tray Manipulation

## Project Review and Operations Handover

**English edition | 16 October 2026 | Internal engineering handover**

This report first reviews the project's exploratory work, observed results and unresolved questions. It then documents the environment, data generation, training, inference services and robot-side operating procedures required for handover. The final appendices enumerate the applicable scripts and configuration files.

The project has established reproducible simulation assets, contact-aware expert collection, native camera recording, data provenance checks and several trained policy variants. A complete native Isaac Sim three-tray expert demonstration and a separate single-pose, three-second Pick/Place benchmark have been independently audited. Learned-policy reliability remains unresolved: the matched real-only versus mixed-policy closed-loop study did not complete either action successfully under its registered protocol.

**Evidence boundary.** This edition uses repository artifacts available at 13:16 SGT on 16 October 2026. The operational environment snapshot was captured at 12:44 SGT; the latest collection status cited here was captured at 13:13:54 SGT. This document is a dated handover, not a live status service. No training, simulation or robot motion was initiated to produce it.

**Reading convention.** A completed process, saved checkpoint, offline metric, expert demonstration and policy task success are distinct claims. References [R01]-[R18] identify the supporting files. All relative paths are relative to the project root. Command blocks marked as new-run recipes require reviewed inputs and a fresh output directory.

<!-- page -->
# 1. Exploration summary

The work progressed from MuJoCo task construction and expert control to policy comparisons, real-data transfer, real-command replay and native PhysX validation. These tracks share tooling but have different task contracts, datasets and success criteria. Their success rates must not be pooled.

| Workstream | Work performed and observed outcome | Interpretation |
|---|---|---|
| Historical MuJoCo control | Scene preparation, front-of-table reachability, bimanual contact transfer, timing and failure analysis; historical full runs reported 180/400 and 193/400 successful sources. | Historical task versions; no evidence of the proposed 70% full-task target. [R02] |
| Three-table, single-tray task | Three exact actions; qualified V4 data with 100/10/10 complete train/val/test sources and 300/30/30 action segments. | A reachable, preselected collection; not a success estimate over every scene. [R03] |
| Pickup120 policy comparison | pi0.5: 50/50 operational pickups; project AffordVLA adaptation: 0/50. Both: 0/50 under the separate 18 cm / 5 deg terminal check. | Pickup-only comparison on same-parent held-out poses; no full-task or architecture-wide conclusion. [R04] |
| Real-data and mixed BC | Real-only, 90/10 and 50/50 variants completed 10,000 updates. Matched offline prediction metrics and independent closed-loop tests were recorded. | Offline gains did not establish reliable contact-rich task execution. [R05]-[R08] |
| Real-command replay | Source trajectory, torso, joint limits, gripper semantics, collision geometry and estimated registration investigated. | Pick motion was reproduced in selected runs; stable initial holding and complete Place reproduction remain unresolved. [R09] |
| Native Isaac Sim | Imported assets and drives audited; complete three-tray expert demo passed with four native camera streams and recorded PhysX substeps. | Expert collection success; native learned-policy task success remains pending. [R10] |
| Fast contact stability | Interpolation, closure timing, pad orientation and preload investigated; recorded v9 center-pose Pick and Place passed at 3 seconds each. | One expert-controlled pose; preparation excluded; no multi-pose robustness claim. [R11] |
| Robot deployment | Model adapters, operator command stop, LAN transport, recording compatibility and SDK diagnostics implemented. | Operational infrastructure and historical trials; no verified complete real-robot task success. [R13] |

The most useful result of this exploration is a chain of inspectable evidence: source identity, physical trajectory, contact measurements, native media, split assignment, training inputs and real process exits. The next development decisions should use that chain rather than aggregate labels such as "complete".

<!-- toc -->
<!-- page -->
# 2. Historical control and task development

## 2.1 MuJoCo baseline and lessons

Early work established the robot and airport scene assets, multi-camera rendering, mobile-base operation, inverse-kinematics planning for expert control and a state machine for tray manipulation. Experiments varied base station and yaw, bimanual grasp feasibility, clearance, supported release, hand-to-hand transfer and action timing. The controller used physical contacts and preserved failures for diagnosis. [R01]-[R03]

Historical v36 and v64 campaigns reported 180/400 (45.00%) and 193/400 (48.25%) completed sources. These are results under their own task versions and acceptance rules. Changes to acceptance tolerances must be reported separately from control improvements. Neither result demonstrates 70% success under the current contract. The earlier v50 evidence covered only three scenes, with two successes, and is not the same scene version as the current local resources. [R02]

The legacy successful-source export contains 149 train, 22 validation and 22 test sources. Its eight-text segmentation produced 2,654 / 390 / 381 segments. These counts must not be reused as current three-action or native Isaac dataset counts. [R03]

## 2.2 Current three-action contract

The main MuJoCo task preserves the three-table layout and dimensions and uses one tray. Base position, base yaw and both grasp poses are searched jointly at the front of the source and destination tables. Movement between tables is allowed; side-of-table manipulation is excluded. The only task strings are:

- `Pick up the tray`
- `Place the tray`
- `Flush tray to the left`

For empty-tray Pick and Place, the arms grasp opposing long edges. The tray long axis is approximately parallel to the robot's horizontal forward direction while facing the table. Any necessary single-arm pre-adjustment remains part of Pick. After Place, the environment loads a backpack, coat and laptop; loading is not a training action.

Loaded Flush follows right push, stable left grasp, right release, physical leftward tray movement of at least 3 cm, then left release with stable support. Reaching the extreme left edge is no longer required. Existing authorized position, boundary and base-translation tolerances, release proximity and timing exclusions are defined by the task specification; this handover introduces no new thresholds. [R01]

Only the specifically authorized visual obstruction at the wrist cameras is removed. Gripper appearance, fingers, collisions, inertia and camera orientation remain preserved. Native four-camera evidence and source-based split assignment remain part of qualification.

<!-- page -->
# 3. Policy learning and simulation diagnostics

## 3.1 Single-tray V4 data and initial BC

V4 contains 120 qualified complete sources: 100 train, 10 validation and 10 test, corresponding to 300 / 30 / 30 three-action segments. The sources were selected for reachable initial conditions; collection completion does not imply universal scene reachability. The separate `three_actions_bc_20261008_v1` run saved a checkpoint after 10 new updates. A subsequent evaluation stage failed with `actual_zero_frame_initialization_evidence_required`. Later milestones were not established by that run. [R02, R03]

## 3.2 Pickup120 comparison

Both models used 120 training pickup episodes and a fixed 50-case, same-parent pose holdout. The pi0.5 model completed 10,000 action BC updates. The project AffordVLA adaptation completed 1,000 mask warmup updates followed by 10,000 action BC updates. Neither evaluation used a teacher, inverse-kinematics solver or inverse-dynamics fallback. [R04]

| Measure | pi0.5 | Project AffordVLA adaptation |
|---|---|---|
| Operational pickup result | 50 / 50 | 0 / 50 |
| Separate 18 cm / 5 deg terminal check | 0 / 50 | 0 / 50 |
| Recorded inference calls | 1,738 | 5,000 |
| Main observed behavior | Physical two-hand contact and table separation | No effective tray lift |

The AffordVLA branch uses Qwen3-VL-4B, visual-region pooling, a flow action head and text LoRA. Its mask supervision is the simulation-visible target-tray silhouette. It is not a complete reproduction of the original research method, does not use RAGNet and does not specifically label long-edge grasp regions. The failure mechanism has not been isolated; architecture, annotation, normalization and action-interface explanations remain hypotheses until tested.

An older evaluation implementation error and an earlier CUDA compatibility failure are retained as separate failed attempts. They must not be relabeled as model capability results. The final 50-case result supersedes intermediate progress snapshots such as 11/50.

## 3.3 Free-run diagnostic

The independent free-run diagnostic recorded 600 seconds, 12,000 frames, 2,400 inference calls and 300,000 physical substeps. The tray fell, opposed long-edge grasping was absent and base XY displacement reached approximately 0.952 m. The recording completed, but the task failed. This run is diagnostic evidence and is excluded from formal training and aggregate task-success reporting. [R02]

<!-- page -->
# 4. Real-data training and offline comparison

## 4.1 Provenance and representation

The supplied real dataset contains 134 independent action episodes: 79 Pick and 55 Place. Grouping by original recording hash yields 102 train, 13 validation and 19 test episodes. The action breakdown is 60/42, 8/5 and 11/8 respectively. At the common 20 Hz cache timeline, the splits contain 18,853 / 2,461 / 3,653 frames. Source data at 30 Hz are resampled using a shared time index; raw recordings remain preserved. [R03, R05]

The learned `mobile19` representation contains seven left-arm joints, left gripper, seven right-arm joints, right gripper and three base channels. Arm angles are radians and model gripper opening is meters. Hardware gripper opening is millimeters. Base channels are excluded from the reported real-data offline MSE; the policy representation does not predict the torso. Three 224 x 224 letterboxed views are model inputs; retaining four original camera streams is a separate data obligation.

## 4.2 Training variants

| Variant | Initialization and training scope | Verified state |
|---|---|---|
| Real-only | Official `pi05_base`; real training data only | 10,000 updates; final checkpoint index 9999; offline evaluation complete |
| 90/10 mixed | Verified simulation-trained parent; new optimizer; real-heavy sampling | 10,000 updates; saved final checkpoint; offline and registered simulation tests |
| 50/50 mixed | Same verified simulation parent as the 90/10 branch; new optimizer; batch 8 = 4 real + 4 simulation | 10,000 updates; prepare/train/evaluate exits 0; separate run and model |

Real-only and mixed models have different initialization histories. A comparison between them is not a strict one-factor mixing-ratio ablation. Sampling percentages refer to training draws, not episode counts or recording duration. Normalization statistics are computed from training inputs only. [R05, R08]

## 4.3 Matched full-frame offline study

The paired study used the same 19 test episodes, all 3,653 frames, horizon 20 and matched per-frame noise for each model. It contains 69,450 valid horizon targets per model. All 104 PNG and 104 PDF plots were generated and independently checked. [R06]

| Model | Pick arm RMSE, deg | Place arm RMSE, deg | Pick gripper RMSE, mm | Place gripper RMSE, mm |
|---|---|---|---|---|
| Real-only | 5.349 | 2.431 | 15.213 | 29.209 |
| 90/10 mixed | 5.235 | 2.405 | 14.118 | 28.666 |

The mixed model had lower aggregate errors on these reported measures. This supports a limited offline prediction comparison. It does not establish stable contact, task completion or real-robot reliability. Earlier stride-5 evaluation numbers have a different sampling protocol and must not be merged into this table.

<!-- page -->
# 5. Closed-loop transfer and the 50/50 branch

## 5.1 Matched independent-action simulation

The registered comparison used each saved 10,000-update real-only and 90/10 mixed model for ten Pick and ten Place cases. Models received paired recorded physical initial states and matched noise. Each independent action had a 50-second simulation budget. There were no teacher calls, IK calls, inverse-solver calls or online state resets. [R07]

| Model | Pick | Place | Completed test executions |
|---|---|---|---|
| Real-only | 0 / 10 | 0 / 10 | 20 |
| 90/10 mixed | 0 / 10 | 0 / 10 | 20 |

All 40 executions closed with 160 camera videos at 224 x 224 and 20 Hz and 40 traces. The delivery audit checked frame counts, hashes, paired initial conditions, finite model outputs and physical substeps. Typical failure labels were `no_stable_opposed_lift` and `no_stable_target_support_release_alignment`.

These were independent actions initialized from recorded states, not a continuous full-task rollout. Their result demonstrates a gap between offline action prediction and reliable closed-loop contact manipulation under this protocol. It does not identify a unique causal mechanism. An older mixed-model 2/10 pickup result used a different protocol and remains a separate historical result.

## 5.2 Completed 50/50 experiment

The 50/50 run reuses 102 real training episodes and ten qualified V4 simulation training sources, the latter providing 30 action segments and 13,401 frames. Across 10,000 updates, the sample schedule draws 40,000 real and 40,000 simulation samples. Sampling within each domain is action-balanced. Real data contain Pick/Place; simulation includes Pick/Place/Flush. [R08]

| Offline test subset | Arm MSE, rad squared | Gripper MSE, mm squared |
|---|---|---|
| Pick, 11 episodes | 0.0086941904 | 199.7232532 |
| Place, 8 episodes | 0.0018802719 | 755.9309904 |

These are the run's test-19, horizon-20 offline metrics. They should be interpreted with that run's evaluation sampling and normalization records. No closed-loop simulation or real-robot task-success result has been established for this model in the evidence used here. The robot service named `mixed` still refers to the earlier 90/10 model; the 50/50 checkpoint was not automatically deployed.

## 5.3 Decisions still requiring experimental evidence

Further work should distinguish perception and action prediction errors from initialization, timing, contact, calibration and execution differences. Offline MSE alone cannot determine which mechanism prevents stable grasping. Changes to training design, grasp strategy, base range or acceptance criteria require an explicit documented decision before a new experiment is treated as comparable.

<!-- page -->
# 6. Real-command replay and native simulation

## 6.1 Real2sim investigation

The replay track preserves the original 20-channel trajectory, including torso motion, and uses a source-specific URDF with explicit joint limits and gripper semantics. It investigates source timing, initial object registration, finger origin/axis mapping, collision decomposition and drive response. The four-finger collision package contains 332 convex components. Registration used in these experiments is estimated and source-bound; it is not a verified measurement of the physical workspace. [R09]

The execution-alignment and held-contact revisions reproduced a selected Pick tray-height increase of approximately 19.55 cm. Place still lost its initial grasp during the interval that should have remained supported by the hands. Reducing initial penetration and eliminating terminal snagging did not establish full Place reproduction. A final state with table support and released fingers cannot erase the earlier loss of the object.

Contacting the table before opening the grippers is not, by itself, a failure: normal placement can do that. The relevant failure evidence is loss of the intended initial grasp and an uncontrolled drop. Earlier probe classification errors were corrected and retained. Differences in drive response were observed, but actuator dynamics and sensor latency were not identified sufficiently to establish a single cause.

Replay completion and exit code 0 therefore indicate completed execution, not successful task reproduction. These diagnostic runs are not training data. Isaac and Genesis replay adapters initially received interface tests only; later native Isaac task results below belong to a separate branch. No native Genesis task-success result is claimed.

## 6.2 Native Isaac Sim three-tray demonstration

Native development included USD import, source mass/inertia checks, base drives, the second gripper finger's mimic behavior, table contact filtering, payload behavior and camera transforms. A source tray mass of 1.2 kg was restored after an incorrect import produced 27.733 kg. Import success and native stepping were treated as prerequisites, not task completion. [R10, R14]

The independently audited `demo_candidate_12` completed all three tray cycles. It produced one complete source and nine action segments, four native videos with 5,462 frames each at 20 Hz, and 136,550 recorded PhysX substeps. Actual leftward movements after handover were 3.248 / 3.120 / 3.359 cm. All three payload sets remained on their trays, final grippers were released and final boundaries passed. [R10]

The demonstration used an expert collection controller. Private teacher kinematics planned commands; physical motion and contact came from PhysX. It is evidence of native expert task execution, not learned-policy performance. The first registered training batch contains one complete source per train/validation/test split; nine segments per source imply 27 action segments and 108 four-camera clip files, subject to the frozen manifest and media audit.

<!-- page -->
# 7. Contact stability and the latest branch

## 7.1 What the fast Pick/Place attempts established

Earlier fast runs met endpoint checks while exhibiting substantial rotation during motion. Subsequent experiments investigated interpolation and coordinated rate limits, gradual closure, torsional contact, contact-pad centers, grasp offsets and pad-normal orientation. A pad-orientation revision alone still produced zero left-hand contact. The successful subsequent candidate combined aligned pad normals, an 8 mm closure target and two physical response frames. These are simulation control settings, not measured rubber calibration. [R11]

| Recorded v9 center-pose measure | Pick | Place |
|---|---|---|
| Action duration | 3.000 s | 3.000 s |
| Maximum tray inclination | 1.259 deg | 1.407 deg |
| Maximum angular velocity | 10.50 deg/s | 17.05 deg/s |
| Relative gripper/tray displacement | 4.75 mm | 5.33 mm |
| Contact/end-state evidence | 17.48 cm lift; 5.65 / 5.87 N finger forces | 4.674 mm release gap; 11.67 N table support; both fingers released |

The full native recording has five streams of 259 frames at 20 Hz and 6,475 physical substeps. The 6.95 seconds of navigation and arm preparation before Pick are excluded from the two three-second action budgets. Relative displacement includes both slip and compliance; it is not a calibrated material-slip measurement. The maximum target joint rate, including the first transition, was 1.5 rad/s.

This result is one independently passed center-pose expert case. It does not establish multi-pose robustness, a complete three-tray task or model success, and it is not eligible for training. Historical videos and failed candidates retain their original labels. Earlier human visual review covered keyframes, while full-motion stability was checked quantitatively from the trace; the record does not claim continuous human inspection of every video frame. [R11]

## 7.2 Latest recorded status at the evidence cutoff

The original native BC was restored in a separate `bc_resume_after_stable_20261016_v1` run after the recorded-video review. It retains the original frozen data and parent model, verifies normalization and sample-index hashes, and corrects the training subprocess path to the existing Conda CUDA compiler. The latest cited status remains initialization with zero actual updates. Native model evaluation remains pending. [R12]

A new fixed-base Pick/Place branch uses `runs/isaacsim_fixed_pickplace_20261016_v1/code35`. Each pair physically continues from Pick into Place without resetting to a canonical held pose. Formal clips use fixed base commands while varying arm state, tray XY/yaw and lift height. Initial candidates are 14 cm and 18 cm; a separate 20 cm / +5 deg candidate failed path preflight and remains recorded. This is expert collection, not VLA-generated data or DAgger.

At 13:13:54 SGT, the first candidate had 175 recorded progress frames and zero closed pairs. The two planned pairs inherit the train split of parent `airport_0004_20270920`; validation/test splits are not fabricated from them. No new two-action training is implied. This branch is independent of the three-action native BC. [R12]

<!-- page -->
# 8. Project layout, access and environments

## 8.1 Direct server access

From a Windows terminal, connect directly using either hostname or IP:

```powershell
ssh michelle@xinmatrix
# If hostname resolution is unavailable:
ssh michelle@100.104.0.108
```

The username is `michelle`, the host is `xinmatrix`, the address is `100.104.0.108` and the SSH port is 22. Enter the separately supplied password interactively when prompted. Verify host identity on first connection. Credentials are not embedded in this document or its command examples. The client must be able to reach the address. Distinguish name-resolution, network and authentication failures; loss of connectivity does not establish that remote work stopped.

## 8.2 Machines and working directories

| Machine | Directory and responsibility |
|---|---|
| Windows workspace | `C:/Users/HAOZEW/Documents/code/r1pro-airport-sim`; source, documentation and small JSON/TXT evidence |
| GPU workstation | `/home/michelle/haoze/r1pro-airport-sim`; physics, recordings, training, checkpoints and model services |
| Robot terminal | `/home/nvidia/GalaxeaVLA/experiments/r1pro`; deployed client, ROS/SDK environment and local recording |

The robot's current login address and hardware state were not reverified for this edition. Robot commands below assume an already logged-in, authorized on-site terminal.

## 8.3 Common server shell variables

```bash
export B=/home/michelle/haoze/r1pro-airport-sim
export CODE="$B"
export SIM_PY=/home/michelle/miniconda3/envs/r1pro-tray/bin/python
export VLA_ENV=/home/michelle/miniconda3/envs/r1pro-vla
export VLA_PY="$VLA_ENV/bin/python"
export ISAAC_PY=/home/michelle/miniconda3/envs/env_isaaclab6/bin/python
export AIRPORT_PROJECT="$B"
export PYTHONPATH="$CODE${PYTHONPATH:+:$PYTHONPATH}"
cd "$B"
```

`B` is the resource and data root. `CODE` is the reviewed code root for the chosen run. For a frozen experiment, use the code identity in its launch receipt rather than assuming the current checkout is equivalent.

Top-level responsibilities: `r1pro_teleop/` contains implementation; `scripts/` exposes workflows and diagnostics; `configs/` stores recipes; `resources/` and `outputs/r1pro_tray_scene/` contain project assets; `runs/` holds versioned evidence; deployed `releases/` are frozen code copies. `docs/SCENE_TASK_SPEC.md` is the task contract, while `docs/project/` provides module, data and experiment navigation. [R01, R14, R15]

<!-- page -->
# 9. Installation and reproducibility

## 9.1 Verified environment snapshot

The following versions were read from the workstation at 12:44 SGT on 16 October 2026. They describe separate environments, not one combined installation recipe. [R14]

| Environment | Python | Key installed packages | Use |
|---|---|---|---|
| `r1pro-tray` | 3.11.16 | MuJoCo 3.13.0; torch 2.8.0+cu129; LeRobot 0.4.4 | MuJoCo, preparation and media validation |
| `r1pro-vla` | 3.11.16 | JAX/jaxlib 0.5.3; torch 2.7.1; LeRobot 0.1.0 | Existing OpenPI training and inference |
| `env_isaaclab6` | 3.12.13 | Isaac Sim 6.0.1.0; torch 2.11.0+cu130; MuJoCo 3.8.0 | Native PhysX; MuJoCo only for private teacher kinematics/asset reading |

## 9.2 New MuJoCo environment

```bash
conda create -n r1pro-tray python=3.11 -y
conda activate r1pro-tray
cd /path/to/r1pro-airport-sim
bash scripts/setup_r1pro_server.sh --with-lerobot
python -m pip install -r requirements-experiments.txt
python -m pip check
python scripts/project.py check --compile
```

Install only inside a non-base Conda environment. The simulation requirements do not recreate OpenPI or Isaac. `pip install -e .` alone does not install the complete runtime. Windows supports asset inspection and some tests; production background collection relies on Linux facilities such as `/proc`, `fcntl` and EGL.

OpenPI needs project-local `third_party/openpi`, its `src` and `packages/openpi-client/src`, a matching JAX environment and verified parent weights. Isaac needs the existing native environment, imported USD assets and drive audits. There is no validated single-command rebuild of the entire workstation.

## 9.3 Migration package

Before migration, save each environment's `conda list --explicit` and `python -m pip freeze`, the OpenPI revision where Git metadata exists, and resource/model/data hashes. Recreate environments at the target prefix instead of copying Conda directories or modifying vendor code.

Preserve source, configs, scene assets, resources, OpenPI source, legal datasets, parent split registries, model weights, normalization, frozen releases, launch identities and actual exit receipts. Existing collections contain absolute paths; a relocated dataset requires a new collection identity rather than edited old source fingerprints. All required resources must remain within the project; execution must not depend on the original humanvideo directory.

Large video and trajectory artifacts remain on the server by default. Handover should include their exact path indexes and hashes, while transferring JSON/TXT metadata locally. The live robot environment remains governed by the deployed `start.sh` and the site's verified hardware procedure.

<!-- page -->
# 10. Preflight, job ownership and recovery

## 10.1 Read-only preflight

After setting the variables in Section 8, inspect the project and resources:

```bash
"$SIM_PY" scripts/project.py check
"$SIM_PY" scripts/sync_task_spec.py --check
nvidia-smi
ps -eo pid,lstart,etime,args | grep -E 'python|isaac|train|supervise'
ss -ltnp
```

For an existing job, match the PID, start ticks, command line and working directory to its launch record, then inspect the stage, heartbeat, logs and real child exit receipt. A PID, a busy GPU or a status file alone is insufficient. Healthy jobs must not be duplicated, and unrelated services must not be stopped.

## 10.2 Auditable stage execution

`isaacsim_stage_runner.py` accepts a JSON job with `argv` as an array, `cwd`, `log`, `launch`, `receipt` and optional `environment`. Copy `docs/handoff/examples/stage_job.example.json` into a fresh run, replace every placeholder, and create the log parent directory before launch.

```bash
: "${JOB:?set JOB to the reviewed new job.json}"
"$SIM_PY" "$CODE/scripts/isaacsim_stage_runner.py" --job "$JOB"
```

The runner waits for the actual child process and records its exit. It does not provide business-success validation or automatic single-instance protection. For detached operation, use the appropriate supervisor/guardian and its lock, with launch identity and independent logs. A successful `nohup` return or `$!` value is not task completion.

Use a new run for changed code, settings or resources. Preserve failed attempts. Existing bounded recovery is limited to three attempts with the supervisor's backoff policy; it is not permission to retry arbitrary physical candidates indefinitely. Resume only from a validated saved state with the original data and optimizer semantics.

## 10.3 CUDA compiler checks

The native BC branch encountered a subprocess path problem that selected the system CUDA compiler instead of the existing Conda compiler. Preserve the reviewed environment in both the parent shell and the job JSON:

```bash
export PATH="$VLA_ENV/bin:$PATH"
command -v ptxas
ptxas --version
"$VLA_PY" -c 'import jax; print(jax.devices())'
```

Verify the expected compiler from the output. Do not modify system CUDA. Preserve the run's visible-GPU and XLA allocation settings; do not silently convert a two-GPU recipe to one GPU or change batch size to work around memory exhaustion.

<!-- page -->
# 11. MuJoCo scene generation and collection

## 11.1 One new complete source

`run_three_table_single_tray.py` is an early empty-tray diagnostic. The full-data entry point is `collect_three_table_full_source.py`, or its registered campaign/workflow. The following recipe writes a new scene and runs physical simulation:

```bash
"$SIM_PY" scripts/generate_three_table_single_tray.py \
  --output "$B/runs/NEW_SINGLE_SCENE" --seed 42

# Use the generated scene JSON and reviewed task inputs.
: "${SCENE:?set SCENE}"
: "${TASK_CONFIG:?set TASK_CONFIG}"
: "${PUSH_REFERENCE:?set PUSH_REFERENCE}"
"$SIM_PY" scripts/collect_three_table_full_source.py \
  --scene "$SCENE" --config "$TASK_CONFIG" \
  --push-reference-scene "$PUSH_REFERENCE" \
  --output "$B/runs/NEW_SINGLE_SOURCE"
```

Default parent sources are registered under `resources/single_tray_three_table_v1/source_registry`. If replacing that lineage, explicitly provide `--parent-scene`, `--parent-manifest` and `--split-registry`. A random seed does not authorize split reassignment; the same parent scene cannot cross train/test boundaries. [R01, R03, R15]

## 11.2 Batch workflows

| Entry point | Role and required distinction |
|---|---|
| `plan_three_table_reachable_initial_poses.py` | Registers reachable candidates; planning is not physical success |
| `collect_three_table_campaign.py` | Requires selection, inventory, parent manifest, split registry and output; default is a plan; `--execute` with config and push-reference-scene runs physics; `--recover` is explicit |
| `supervise_three_table_workflow.py` | Runs a complete workflow from `--options`; validate the exact options schema and launch identity |
| `supervise_three_table_single_tray_training.py` | Data/training workflow from `--options`; `--data-only` suppresses training |
| `supervise_verified_three_action_training.py` | Qualified V4 three-action BC path; do not substitute historical eight-text data |

Options files are workflow-specific, not interchangeable. When copying a frozen recipe, inspect every input/output, source domain, camera, split, interpreter and parent checkpoint; changing only the output path is insufficient.

## 11.3 Qualified action export

```bash
: "${QUALIFIED_RECORDS:?set validated full-source JSONL}"
"$SIM_PY" scripts/export_three_table_single_tray_actions.py \
  --records "$QUALIFIED_RECORDS" \
  --destination "$B/runs/NEW_ACTION3_TRAIN" \
  --repo-id airport/new_action3_train --split train
```

Export validation and test separately. The records file is qualified complete-source JSONL, not an arbitrary list of episode paths. Exclude environment loading from action clips. Verify source count, segment count, four-camera file count, FPS, dimensions, frame alignment, hashes, train-only normalization and the intended dataset loader before training.

<!-- page -->
# 12. Native Isaac assets and complete episodes

## 12.1 Prepare and audit assets

The legacy 193 successful MuJoCo sources are inputs to discovery and conversion, not native Isaac training data. Use the reviewed payload template and a new asset run:

```bash
: "${PAYLOAD_TEMPLATE:?set reviewed payload-template JSON}"
"$SIM_PY" scripts/supervise_isaacsim_three_tray_assets.py \
  --run "$B/runs/NEW_ISAAC_ASSETS" --project "$B" \
  --legacy-root "$B/runs/vla_20261005/task_complete_actions_v1" \
  --payload-template "$PAYLOAD_TEMPLATE" \
  --isaac-python "$ISAAC_PY" --source-python "$SIM_PY"
```

The component checks include `isaacsim_scene_smoke.py --xml ... --output ...` and `isaacsim_control_preflight.py --usd ... --xml ... --output ...`. Inspect mass/inertia, joint mapping, finger mimic, base drives, table contacts, camera transforms and payloads. Optional asset flags must follow the registered conversion plan. Successful import is not successful control.

## 12.2 Execute and qualify a new native episode

```bash
: "${ISAAC_SCENE_ROOT:?set verified native scene root}"
"$ISAAC_PY" "$CODE/scripts/run_isaacsim_three_tray_task.py" \
  --scene-root "$ISAAC_SCENE_ROOT" \
  --output "$B/runs/NEW_ISAAC_EPISODE" \
  --seed 42 --episode-id new_unique_episode_id
```

For formal collection, wrap the command in the stage runner and write the actual child receipt to the episode's `process_exit.json`. Create the parent directory first; let the task create its new episode directory. `--no-video-diagnostic` intentionally omits media and must remain ineligible for training.

Expected artifacts include status/progress, `native_trace.npz`, native-step/contact logs, observer events, `episode.json`, `qualification.json`, four MP4 files, encoder exits and any failure evidence. Native trace timing distinguishes pre-action RGB/state from the completed physical interval. Preserve this convention when checking frame alignment.

```bash
: "${NATIVE_REGISTRY:?set parent split registry}"
"$SIM_PY" scripts/audit_isaacsim_three_tray_demo.py \
  --case "$B/runs/NEW_ISAAC_EPISODE" \
  --registry "$NATIVE_REGISTRY" \
  --output "$B/runs/NEW_ISAAC_AUDIT.json"
```

`supervise_isaacsim_three_tray_task.py --config ...` manages the registered workflow. Its guardian must adopt the real supervisor launch identity. Preserve the validated configuration's project, demo, receipt, registry, interpreters, parent checkpoint/status and case list. Without a valid learned-policy evaluation command, the workflow must report model evaluation as pending. [R10, R15]

<!-- page -->
# 13. Dataset freezing and specialized collection

## 13.1 Freeze, clip and cache

After complete native episodes pass independent qualification and cover legal train/validation/test parents, use an absolute-path JSON array of their episode directories:

```bash
: "${EPISODES_JSON:?set qualified episode-list JSON}"
: "${NATIVE_REGISTRY:?set registry}"
"$SIM_PY" scripts/prepare_isaacsim_dataset.py --mode freeze \
  --registry "$NATIVE_REGISTRY" --episodes "$EPISODES_JSON" \
  --output "$B/runs/NEW_ISAAC_DATA"
"$SIM_PY" scripts/prepare_isaacsim_dataset.py --mode clips \
  --registry "$NATIVE_REGISTRY" \
  --manifest "$B/runs/NEW_ISAAC_DATA/manifest.json" \
  --output "$B/runs/NEW_ISAAC_CLIPS"
"$SIM_PY" scripts/prepare_isaacsim_dataset.py --mode cache \
  --registry "$NATIVE_REGISTRY" \
  --manifest "$B/runs/NEW_ISAAC_DATA/manifest.json" \
  --output "$B/runs/NEW_ISAAC_CACHE"
```

Each complete three-tray source produces nine action segments. Count complete sources, clips and camera files separately. A single-source preview is not a three-split training batch. Later expansion uses a new frozen version and must not modify files or manifests being read by training.

## 13.2 Fast Pick/Place diagnostics

`run_isaacsim_fast_pickplace.py --config <case.json>` runs one case; `supervise_isaacsim_fast_pickplace.py --config <campaign.json>` dispatches a registered campaign. The case and campaign schemas differ. `audit_isaacsim_fast_pickplace.py --case ... --output ...` independently checks the result, and `finalize_isaac_fast_pickplace.py` assembles closed recordings.

Review output, scene root, seed, case ID, tray pose, lab assets and every registered control setting. With `record_cameras=false`, the output is a physics probe, not a completed video. Each three-second action has 60 native frames at 20 Hz; separately report navigation/preparation. Audit the complete trajectory, inclination, angular velocity, relative motion and contact, not only endpoint `passed` fields. [R11, R15]

## 13.3 Fixed-base continuous Pick/Place

`collect_isaac_fixed_pickplace.py` is the new independent branch. Use its reviewed code35 configuration and inspect its schema before launch. The output separates `dataset/pick_up_the_tray/train/case_NNN` and `dataset/place_the_tray/train/case_NNN`, while preserving the physical continuity and common parent of each pair.

Place must begin from the actual Pick endpoint, with recorded 19-channel robot state, 7D tray pose, grasp forces and frame identity. Do not reset to a canonical held pose or invent validation/test data. Freeze each pair only after independent audit and complete media export. The cited branch had no closed pair at the evidence cutoff; this manual does not turn that status into data readiness. [R12]

<!-- page -->
# 14. Training entry points and new runs

## 14.1 Select the correct training scope

| Script | Interface and purpose |
|---|---|
| `train_pi05_airport.py` | `--config <TrainingSpec.json>`; `--normalize-only` computes normalization; historical mobile19 LoRA recipes |
| `train_pi05_accelerated.py` | `--spec ... --parent-status ... --prepare-cache`, then `--stop-after N`; `--resume` has explicit saved-state semantics |
| `train_pi05_isaac_three_tray.py` | `--run <training> --mode prepare/train --stop N`; native frozen inputs; two visible GPUs |
| `run_pi05_real_only.py` | `--run ... --mode prepare/train/evaluate/supervise`; real-only branch initialized from `pi05_base` |
| `run_real_sim_pickplace.py` | `--run ... --mode prepare/mse/train/simulate/supervise`; historical 90/10 workflow; includes older comparison stages |
| `train_pi05_real_sim50.py` | `--run ... --mode prepare/train/evaluate/supervise`; 4+4 batch; supervisor fixes GPU 0 |
| `compare_pickup120.py` and `resume_afford_pi05_comparison.py` | Pickup120 comparison only; inspect fixed server paths and original identities |

These scripts are not interchangeable general-purpose trainers. Several resolve previously frozen caches and parent models through source constants. `--run` alone does not bind arbitrary new data. Before migration or reuse, inspect inputs, integrity records, frozen selections and fixed paths. [R05, R08, R15]

## 14.2 New real-only experiment template

Use only when a new experiment is intended and the existing data/checkpoint hashes and GPU allocation have been verified:

```bash
export PATH="$VLA_ENV/bin:$PATH"
export XLA_PYTHON_CLIENT_PREALLOCATE=false
export WANDB_MODE=disabled
: "${GPU_ID:?set allocated GPU}"
export CUDA_VISIBLE_DEVICES="$GPU_ID"
"$VLA_PY" scripts/run_pi05_real_only.py \
  --run "$B/runs/NEW_REAL_ONLY" --mode supervise
```

For the 50/50 supervisor, verify that GPU 0 is available and approved, then create a new run before launch:

```bash
mkdir "$B/runs/NEW_MIX50"
"$VLA_PY" scripts/train_pi05_real_sim50.py \
  --run "$B/runs/NEW_MIX50" --mode supervise
```

Do not restart the already completed historical runs. Keep source domains explicit: `real_world/user_provided` and `simulation/program_generated`. Never relabel simulation as human teleoperation or real user recordings as simulation. Record actual updates, checkpoint save receipts and evaluation separately from finite loss or supervisor completion.

<!-- page -->
# 15. Native BC restoration and policy evaluation

## 15.1 Native training inputs

The native trainer's `training/inputs.json` binds five absolute paths: `cache`, `manifest`, `registry`, `parent_checkpoint` and `parent_status`. Preparation validates the three splits, action labels and parent weights and writes normalization, sample indices, integrity and preparation status.

```bash
: "${TRAIN_RUN:?set reviewed new training directory}"
"$VLA_PY" scripts/train_pi05_isaac_three_tray.py \
  --run "$TRAIN_RUN" --mode prepare
# Confirm both GPUs and the reviewed compiler environment first.
"$VLA_PY" scripts/train_pi05_isaac_three_tray.py \
  --run "$TRAIN_RUN" --mode train --stop 10
```

The registered milestones are 10 / 100 / 1,000 / 10,000 / 100,000 actual updates. Later stages reuse the saved state within the same training run. Checkpoint numbering is zero-based in these recipes: index 9999 corresponds to 10,000 updates only when the status and metadata agree.

## 15.2 Restoration after recorded-video review

`resume_isaacsim_bc_after_video.py --config <reviewed-config>` waits for explicit native-video review, checks evidence hashes and preserves the original frozen inputs, normalization and sample indices. Required configuration includes `run`, `training`, `original_training`, `review`, `project`, `compiler_bin`, `vla_python` and `training_code`.

The restoration directory is under `runs/isaacsim_three_tray_workflow_20261015_v1/bc_resume_after_stable_20261016_v1`. The original `pipeline_v15` deferred state is historical coordinator state; read `CURRENT_NATIVE_BC_RESUME.json` and the restoration run to determine actual training status. At this edition's cutoff the cited actual-update count was still zero. Do not duplicate a healthy restoration process or fabricate `approved_for_original_BC_resume`. The fast diagnostic recording is excluded from training. [R12]

## 15.3 Evaluation rules

`evaluate_three_table_single_tray_pi05_batch.py` uses a registered protocol, checkpoint identity, simulation/model interpreters and output path; distinguish plan mode from `--execute`. `run_vla_fixed_scene.py` and `run_three_table_pi05_free_run.py` are diagnostics. `compare_pi05_closed_loop.py` is the registered paired-model test and must retain the actual model identity.

A policy test must execute the policy without hidden teacher, IK, inverse-dynamics or corrective fallback. BC is not DAgger unless DAgger was actually performed. An independent-action test is not a full continuous task. Report simulation and real-robot results separately. Native three-tray learned-policy success remains pending until actual execution, qualification, native media and exit receipts close. [R01, R07, R15]

<!-- page -->
# 16. Start the workstation inference services

## 16.1 Endpoint and model identity

| Role | Workstation endpoint | Robot LAN endpoint |
|---|---|---|
| `mixed`: completed 90/10 model | `100.104.0.108:8095` | `10.42.0.191:8095` |
| `real_only`: completed real-only model | `100.104.0.108:8096` | `10.42.0.191:8096` |

The deployed adapter is `releases/galaxea_robot_deploy_20261013_v3/scripts/serve_pi05_galaxea_robot.py`. The simulation server `serve_pi05_airport.py` implements a different protocol. The 50/50 model is not automatically selected by the `mixed` endpoint. [R13, R14]

At the 12:44 SGT inventory snapshot, the LAN relay was listening, but the two model backends and keyboard controller were not found. This is a dated observation; recheck processes, addresses and GPU availability before starting anything.

## 16.2 Fresh output directories

The old deployment run already contains raw action chunks. Counters restart from zero, so restarting into those directories could overwrite evidence. Create a new run and copy the reviewed configurations:

```bash
export DEPLOY_CODE="$B/releases/galaxea_robot_deploy_20261013_v3"
export ROBOT_RUN="$B/runs/galaxea_robot_REPLACE_NEW_ID"
export OLD_ROBOT_RUN="$B/runs/galaxea_robot_deploy_20261013_v3"
mkdir "$ROBOT_RUN"
mkdir "$ROBOT_RUN/mixed" "$ROBOT_RUN/real_only"
cp "$OLD_ROBOT_RUN/mixed/server_config.json" \
  "$ROBOT_RUN/mixed/server_config.json"
cp "$OLD_ROBOT_RUN/real_only/server_config.json" \
  "$ROBOT_RUN/real_only/server_config.json"
```

Keep `training_status` bound to the verified model, `execute_steps=5`, `gripper_range_mm=[0,80]`, and matching host/port settings. Both servers use the same absolute operator-control file under `runs/galaxea_robot_deploy_20261013_v2/operator_control.json`. If that location is changed, both servers and the control terminal must be changed together. Complete examples are in `docs/handoff/examples/`.

```bash
: "${GPU_ID:?set allocated GPU}"
CUDA_VISIBLE_DEVICES="$GPU_ID" "$VLA_PY" \
  "$DEPLOY_CODE/scripts/serve_pi05_galaxea_robot.py" \
  --config "$ROBOT_RUN/mixed/server_config.json"
```

Start only the needed model; use a separate terminal or fully stop it before starting the other configuration. Two simultaneous models require verified memory capacity. Readiness requires completed warmup, matching checkpoint/norm identity in `server_status.json`, the actual listener and the expected process. `ready_operator_stop_latched` means ready with command stop still engaged. Background services require the same launch/exit evidence discipline as other jobs.

<!-- page -->
# 17. Operator control and robot LAN transport

## 17.1 Persistent command-stop terminal

Open one interactive server terminal from Windows:

```powershell
ssh -t michelle@xinmatrix
# Alternatively: ssh -t michelle@100.104.0.108
```

In that server terminal, set the absolute paths and run the controller:

```bash
B=/home/michelle/haoze/r1pro-airport-sim
VLA_PY=/home/michelle/miniconda3/envs/r1pro-vla/bin/python
CONTROL_CODE="$B/releases/galaxea_keyboard_control_20261013_v3"
CONTROL_FILE="$B/runs/galaxea_robot_deploy_20261013_v2/operator_control.json"
"$VLA_PY" "$CONTROL_CODE/control_galaxea_servers.py" \
  --control-file "$CONTROL_FILE"
```

The default state is STOP. Only the on-site operator should press `R` after the setup is ready. `E` or Space engages stop; `Q` and terminal exit engage stop. A heartbeat older than one second causes the servers to reject commands. After rejection, rearming does not automatically restart the client; restart it deliberately.

This mechanism stops command acceptance. It cannot retract an in-flight command or the last submitted target. The hardware emergency stop remains a separate on-site control. Use one operator-control terminal and one active robot client. [R13]

## 17.2 LAN transport

The workstation relay listens on `10.42.0.191:8095/8096` and forwards to the model services at `100.104.0.108` on the corresponding ports. A listening TCP port does not establish model readiness. Reuse an existing healthy relay.

Only if the previous relay has exited, the address belongs to the workstation and the ports are free, create a fresh relay run. The script writes lock/status files next to itself, so execute a copy in the new run:

```bash
export RELAY_RUN="$B/runs/galaxea_robot_lan_REPLACE_NEW_ID"
mkdir "$RELAY_RUN"
cp "$B/scripts/forward_galaxea_lan.py" \
  "$RELAY_RUN/forward_galaxea_lan.py"
"$SIM_PY" "$RELAY_RUN/forward_galaxea_lan.py"
```

Changing the LAN requires a new explicitly configured transport version and protocol/latency verification. Do not assume a historical address is still assigned. The robot configuration files are `config_pi05_mixed_gripper80_lan_20261013.toml` and `config_pi05_real_only_gripper80_lan_20261013.toml`. Their handover copies represent the previously deployed configuration, not a fresh comparison against today's robot filesystem.

The configured client rate is 20 Hz with five action steps per inference response. Actual control cadence must be derived from recorded timestamps; the configuration alone is not a latency or throughput measurement.

<!-- page -->
# 18. Robot-side startup and recorded execution

## 18.1 Hardware and environment prerequisite

The project does not contain a verified single command for cold boot through complete robot-driver and camera startup. The site must use its established vendor/SDK startup procedure. `source start.sh` initializes the client environment and does not prove that hardware drivers are running.

In the already logged-in robot terminal, inspect the environment and topics:

```bash
cd /home/nvidia/GalaxeaVLA/experiments/r1pro
source ./start.sh
export FASTRTPS_DEFAULT_PROFILES_FILE=/opt/galaxea/find_server/super_client_configuration_file.xml
ros2 topic list --no-daemon
./vla status
```

A fresh shell without the DDS configuration can fail to discover topics even when the SDK exists. Verify live feedback, valid camera frames, backend readiness, the original command filter, the intended initial state and on-site stop controls before starting a client. This document records the procedure; its preparation did not authorize or execute robot motion. [R13]

## 18.2 Task/model selection

The diagnostic wrappers record SDK feedback and are preferred when investigating hardware faults:

```bash
./vla_sdk_diagnostics pick        # 90/10 mixed, Pick up the tray
./vla_sdk_diagnostics place       # 90/10 mixed, Place the tray
./vla_sdk_diagnostics pick real   # real-only
./vla_sdk_diagnostics place real
```

Regular recording-compatible entries remain `./vla pick`, `./vla place`, `./vla pick real` and `./vla place real`. These commands run inside the deployed robot directory. Do not run the repository's undeployed one-click script from the workstation as though it were the robot client.

If an alias is absent, first verify the deployed files. The v5 wrapper can be invoked directly:

```bash
python run_pi05_record_compat_20261013_v5.py \
  --config config_pi05_mixed_gripper80_lan_20261013.toml --record
```

Direct wrapper invocation does not switch the instruction. With no active client, set `scheduler/instruction/instruction.txt` to the exact task string. The one-click entry is preferable because it checks single-instance ownership before writing that text. Never change instructions during an active client run.

To change task/model, stop the current client with Ctrl+C, wait for recording finalization, verify exit, check stop state and the new task, then let the operator decide whether to rearm and restart. Preserve rejected commands and SDK errors; do not automatically retry physical motion.

<!-- page -->
# 19. Robot execution contract and troubleshooting

## 19.1 Units, filters and records

The original `run.py`, `scheduler/scheduler.py` and `scheduler/joint_command_filter.py` remain the execution contract. The approved filter settings are a 0.1 rad maximum joint step, 1.5 rad/s velocity, 0.25 rad tracking threshold and 0.5 s maximum observation age. Gripper opening is limited to 0-80 mm. These are inherited settings, not new limits introduced by this handover. [R13]

The model emits gripper opening in meters; the server converts to millimeters and clamps to the allowed range. It does not rescale 100 mm into 80 mm. Preserve raw model output and submitted values so saturation remains visible. Policy base channels are not deployed as hardware base commands. SDK effort units are not calibrated here and must not be reported as measured torque.

Retain server `commands.jsonl`, `raw_chunk_*.npz` and `server_status.json`; client recording directories; `joint_filter_diagnostics.jsonl`; v5 `sdk_fault_window.json`; exception logs and actual exits. NumPy recording compatibility, transport fixes and fault windows improve diagnosability but do not establish successful manipulation.

## 19.2 Fault isolation sequence

| Symptom | First evidence to inspect | Interpretation/action |
|---|---|---|
| SSH connection fails | Host resolution, direct IP reachability, authentication response | Distinguish access failure from remote process state; retain last verified time |
| Port responds but inference fails | Backend process, warmup log, model identity, stop/heartbeat state | TCP transport may be healthy while model service is absent or stopped |
| ROS topics absent in a fresh shell | `start.sh`, DDS profile and discovery output | Check environment before concluding the SDK is down |
| Commands rejected | Observation age, joint deltas, tracking error, operator heartbeat | Preserve filter evidence; do not weaken thresholds to obtain motion |
| Robot stops or SDK faults | Timestamped feedback, filter diagnostics, SDK fault window, raw/submitted action | Root cause remains unproven until these signals are correlated |
| Recording fails | Deployed wrapper version, dependency versions and exception | Verify the compatibility wrapper; retain the failed recording attempt |

## 19.3 Known handover gaps

The cold hardware-start procedure, today's robot-side file hashes and current sensor/SDK readiness were not revalidated for this edition. Historical filter tracking errors do not yet have a confirmed single cause. Real2sim drive and initial-grasp consistency also remain unresolved. A successor should validate these specific gaps before treating the system as unattended or production-ready.

<!-- page -->
# 20. Replay, monitoring and maintenance

## 20.1 Offline real-command replay

The replay entry point operates on recorded trajectories and does not connect to the robot. Use a new output directory, the reviewed scene and the source-specific URDF:

```bash
: "${REAL_MANIFEST:?set source manifest}"
: "${SCENE_XML:?set scene XML}" "${ROBOT_URDF:?set source URDF}"
"$SIM_PY" scripts/replay_real2sim.py \
  --source-manifest "$REAL_MANIFEST" --scene-xml "$SCENE_XML" \
  --urdf "$ROBOT_URDF" --output "$B/runs/NEW_REAL2SIM_REPLAY" \
  --per-task 1 --video
```

Use `--registration` and `--finger-collision-bundle` only with the reviewed source-bound assets. Companion tools include `validate_real2sim.py`, `audit_real2sim.py`, `fit_real2sim_registration.py`, `fit_real2sim_torso.py` and `diagnose_real2sim_held_pose.py`. Inspect their exact arguments and side effects. A 640 x 360, 30 fps preview is not native-resolution training media. [R09, R15]

## 20.2 Server-side monitoring

After direct SSH and the Section 8 setup, run the applicable read-only monitor. Omit `--watch` for one snapshot or add `--watch 10` for periodic output:

```bash
"$SIM_PY" scripts/watch_pi05_mix50.py \
  --run "$B/runs/real_sim50_pi05_20261015_v1"
"$SIM_PY" scripts/watch_pi05_real_only.py \
  --run "$B/runs/real_only_pi05_20261012_v1"
"$SIM_PY" scripts/watch_real_sim_transfer.py \
  --run "$B/runs/real_sim_pickplace_20261009_v3"
"$SIM_PY" scripts/watch_vla_comparison.py \
  --run "$B/runs/afford_pi05_pickup120_20261008_v2"
```

For native work, read `CURRENT_NATIVE_PIPELINE.json` and `CURRENT_NATIVE_BC_RESUME.json` under the three-tray workflow run, then inspect the selected run's status and training status. For fast diagnostics, read `runs/ISAAC_FAST_PICKPLACE_CURRENT.json` and distinguish active probes from older videos. Fixed-pair collection uses its own `collection_status.json`, producer receipt and logs. Stopping a monitor with Ctrl+C does not stop the job.

## 20.3 Media and historical tools

`serve_isaacsim_media.py --root <approved-run-root> --state-dir <new-state-dir> --bind 100.104.0.108 --port <free-port>` serves read-only media with Range/HEAD support. Reuse a healthy existing service. Limit its root to the intended run; do not expose the project root or credential directories.

Legacy `project.py fourcam`, `r1pro_teleop.airport_fsm` prepare/preflight/generate/export/report, action8 trainers and pickup120/200 workflows retain their original scopes. Many historical diagnostic scripts write output or execute at import time. Do not bulk-run them, including for `--help`. Use the static catalog and read source first.

<!-- page -->
# 21. Acceptance, ownership and continuing the project

## 21.1 Evidence required for each claim

| Claim | Minimum supporting evidence |
|---|---|
| Job is initializing/waiting | Matching process identity, current phase/heartbeat and logs; actual updates explicitly zero where applicable |
| Data are ready | Qualified complete sources, native media/trace alignment, legal splits, frozen manifest and hashes |
| Training occurred | Actual updates greater than zero, finite metrics and timestamped process/log evidence |
| Model was saved | Checkpoint parameters/metadata, normalization, saved-state semantics and save receipt |
| Policy task succeeded | Actual policy execution, no hidden fallback, task qualification, media/trace and process exit |
| Workflow finished | Every required stage has a real exit and delivery audit; task outcome reported separately |

Frozen collections, releases, manifests and checkpoints are immutable evidence. Use new run directories for implementation, configuration and resource changes. Preserve failure artifacts and old success labels. After core control checks, complete the relevant physical episode; static tests or low loss do not replace server execution. [R01, R16]

## 21.2 Recommended continuation order

First inspect the current native BC restoration and fixed-pair collection without starting duplicates. Confirm whether initialization progressed into actual updates and whether continuous Pick/Place pairs closed with full media and correct source lineage. Then assess the registered native learned-policy evaluation when its checkpoint exists. Separately resolve the real2sim initial holding state and the hardware-start/feedback gaps before extending real-robot execution.

The ordering above is a handover recommendation, not a statement that those experiments have been run or an authorization to change their design. Any proposed change to action sequence, grasping, base range, tolerances or training strategy should state the observed failure, established evidence, hypotheses and alternatives before a decision is recorded.

## 21.3 Documentation and interaction records

Read the root README, documentation index, task specification, current memory, decisions and module/data/experiment pages when resuming work. Implementation changes affecting generation, state machines, contacts, cameras or export require a corresponding human-reviewed task-spec update and non-base `sync_task_spec.py --write` followed by `--check`.

Refresh the static handover catalog with `scripts/build_handoff_catalog.py --write`; check it with `--check`. It parses source without importing or executing historical scripts. The English PDF is generated from this editable English source and a frozen inventory snapshot. Its source hashes and validation receipt accompany the output.

At the end of meaningful work, update the relevant topic page and current snapshot, append decisions with replacement relationships, and run `scripts/export_project_interactions.py` using the non-base project interpreter. Preserve the current project thread and its parent thread IDs. The export is an explicit invocation, not a permanently running service; credentials and private keys must not enter the archive. [R16]

<!-- page -->
# 22. Reference register

References below distinguish primary artifacts from derived navigation. Paths identify the evidence used in this edition; they are not instructions to run historical experiments. The companion source manifest records SHA-256 hashes at capture. Current operational status must be rechecked on the server.

| ID | Evidence / navigation path | Role |
|---|---|---|
| R01 | `docs/SCENE_TASK_SPEC.md` | Current task contract; use the captured hash/version for this edition |
| R02 | `docs/project/EXPERIMENT_STATUS.md` and `docs/governance/README_20261016_BEFORE.md` | Derived historical experiment summaries; old large-run results are reported as historical records |
| R03 | `docs/project/DATA_CATALOG.md` | Source lineage, split and count definitions |
| R04 | `runs/afford_pi05_pickup120_20261008_v2_reference/final_motion_audit.json`; `AFFORD_PI05_120_TRAINING.txt` | Final pickup motion audit and result history |
| R05 | `runs/real_only_pi05_20261012_v1_reference/final_closure.json`; `docs/project/REAL_SIM_TRANSFER.md` | Real-only closure and mixed-training provenance |
| R06 | `runs/pi05_real_mixed_comparison_20261012_v1/real_only/metrics.json`; corresponding `mixed/metrics.json` | Matched full-frame offline metrics; accompanying identities/progress/plots |
| R07 | `runs/pi05_real_mixed_closed_loop_20261012_v1_reference/comparison_summary.json`; `delivery_report.json` in the same directory | Per-case outcomes and delivery audit |
| R08 | `runs/real_sim50_pi05_20261015_v1_reference/latest_status_snapshot.json` | Actual 50/50 training and offline evaluation snapshot |
| R09 | `runs/real2sim_held_contact_20261012_v2_reference/summary.json`; `delivery_validation.json` in the same directory; `docs/project/REAL2SIM.md` | Latest held-contact replay artifacts and explanatory history |
| R10 | `runs/isaacsim_three_tray_workflow_20261015_v1_reference/demo12_independent_closure_audit_v1.json`; `demo12_audit_exit.json` | Complete native expert demo and actual audit exit |
| R11 | `runs/isaacsim_fast_stability_20261016_v9_recorded_reference/audit_summary.json`; `case_000/path_stability.json` | Recorded single-pose result and complete-path stability measures |
| R12 | `runs/isaacsim_fixed_pickplace_20261016_v1_reference/efficiency_snapshot_20261016T131354.json`; captured `memory/CURRENT.md` | Dated fixed-pair status; BC restoration and branch navigation |
| R13 | `docs/project/REAL_ROBOT_DEPLOYMENT_20261013.md`; `docs/handoff/examples/` | Deployment history and reviewed server/robot configuration copies |
| R14 | `runs/documentation_handoff_20261016/server_inventory.json` | 12:44 SGT read-only environment, configuration and process inventory |
| R15 | `docs/handoff/script_catalog.json`; `docs/project/MODULE_MAP.md`; `docs/handoff/README.md` | Static CLI/source identities and operational navigation |
| R16 | `AGENTS.md`; `docs/governance/MEMORY_POLICY.md` | Collaboration, evidence preservation and archive policy |
| R17 | `runs/documentation_handoff_20261016/validation.json` | Earlier handover link, configuration and CLI checks |
| R18 | `output/pdf/R1Pro_Project_Review_and_Operations_Handover_EN.validation.json` | This edition's PDF, source, inventory and rendering checks |

<!-- inventory -->
