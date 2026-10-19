# Scene Studio complete user guide

A step-by-step guide to scenes, datasets, training and evaluation. Updated 19 October 2026, Singapore time. Button names match the English interface.

**Saving or synchronizing a scene does not add it to training.** A scene describes the starting arrangement. Training needs actual robot demonstrations that have been collected, validated, exported and registered.

Workstation and hosted releases may differ. Follow the controls visible in your edition. Historical counts below describe named dataset versions, not a live server status check.

## 1. Understand the complete workflow

Think of a scene as the room arrangement, a dataset as recorded examples, and a checkpoint as a saved version of the model that learned from those examples.

```text
Edit room positions, orientations and colors
  → Save version
  → Sync to GPU
  → Server receives a draft: draft_synced

Maintainer steps — no one-click website button currently covers these:
  → Adapt the draft and check reachability
  → Execute Pick → Place in native physics
  → Validate the task, videos, trajectories and source identity
  → Export two action segments from each qualified pair
  → Freeze a dataset manifest and build training inputs
  → Register a new dataset version in the backend and website

Website steps:
  → Select Registered datasets
  → Create training job
  → Queue → data validation → initialization → gradient updates
  → Save a complete checkpoint
  → Run MSE, single-room policy evaluation or multi-room evaluation
  → Read results, stop reasons, videos and reports
```

If you only want to train using existing registered data, go straight to chapter 7. You do not need to edit a scene or regenerate the existing 300 pairs.

| What you want | Where to do it |
|---|---|
| Edit one of the existing 32 initial room states | Scene workspace |
| Save, restore or export scene settings | Save version / Version history / Export |
| Send scene settings to the server | Sync to GPU; this creates a draft only |
| Collect an arbitrary edited draft and add it to training | Maintainer workflow in chapter 5; no end-to-end website button |
| Train π0.5 using registered data | Data & training → Data & recipe |
| Trace source batches into training | 32-room batch lineage |
| Watch one room and checkpoint execute | Policy evaluation |
| Evaluate several registered rooms | Evaluation & MSE → Isaac VLA closed loop |
| Compare predictions against recorded real demonstrations | Fixed real-data MSE comparison |
| Enter arbitrary tasks, evaluate Flush, or train G0.5/GR00T | Not supported by the current training/evaluation forms |

## 2. Open the website and find the right page

### Two editions

| Edition | How to access it |
|---|---|
| Workstation | Open http://100.104.0.108:9080 from a device with access to that network. Offline workstation · No sign-in means ChatGPT login is not required |
| Hosted Site | Open https://r1pro-scene-agent-haoze.exactmyna128.chatgpt.site and sign in when prompted. GPU submissions and protected artifacts require the project owner identity |

Offline means the web application runs on the workstation. It still requires that workstation to be running and reachable. A working web page does not prove that the GPU worker is connected.

Before submitting anything:

1. Wait for rooms and dataset information to load.
2. Check the connection indicator and Server sample or Sample time. An old timestamp means you may be viewing a snapshot.
3. Open Run history and check whether the task you need is already there. Do not create another job just to check progress.

| Top navigation | Purpose |
|---|---|
| Scene workspace | Edit robot/tray starting positions and appearance |
| Policy evaluation | Watch one independent model rollout and download its recordings |
| Data & training | Select datasets, create training, compare MSE and run batch evaluation |
| Run history | Read job receipts, IDs, timestamps and server output directories |
| Help | Read this guide and access setup instructions and downloads |

Data & training is a long page. Scroll past downloads, Current training and After training to reach the Data & recipe, Evaluation & MSE and Job queue tabs. Reports can be farther down, below submission forms.

## 3. Learn the essential terms

| Term | Plain-language meaning | Important distinction |
|---|---|---|
| Room | A registered scene instance and starting state | 32 requested rooms do not mean 32 successful demonstrations |
| Draft | Edited scene configuration awaiting collection/validation | A good-looking preview is not a successful physical task |
| Pair | A qualified continuous Pick and Place source | One pair produces two action segments |
| Segment | One Pick or one Place sequence | 600 segments are not 600 pairs |
| Episode | One recorded sequence or execution | A real episode need not contain a complete Pick/Place pair |
| Dataset | Registered sources, segments and their manifest | It is not an arbitrary folder of videos |
| Train / Val / Test | Learning data / development validation / final testing | Val and Test are not fed back into training |
| Step | One actual model parameter update | Not one camera frame or one room |
| Checkpoint | A saved model state with required configuration | Registration does not prove successful model loading |
| Loss | The fitting objective measured during training | Not task success or test MSE |
| MSE / RMSE | Error between predicted and demonstrated actions | Low error does not guarantee a successful grasp |
| Closed loop | Observe, predict, execute, then observe again | Different from scoring a fixed recorded dataset |
| Simulation time | Time advanced by actual simulator action frames | Ten simulated seconds can take longer in real life |
| Wall time | Time you wait on a clock | Includes loading and inference waits |

## 4. Create and edit a scene draft

### Select a room and object

1. Click Scene workspace.
2. Under Rooms on the left, click 00. This corresponds to Room 000 on the evaluation page; 03 corresponds to Room 003.
3. For your first edit, leave Apply to all rooms unchecked.
4. Under Object, choose R1 Pro robot or Tray.
5. Check the room name above the 3D view before editing.

The editor modifies the existing 32 registered room instances. It does not offer unlimited room creation, arbitrary CAD import or table resizing.

### Change position and orientation

Transform fields contain **absolute coordinates**. Changing X from 0.30 to 0.31 moves it by 1 cm along X. Entering 0.01 sets X to 0.01 m; it does not add 1 cm.

| Object | Editable fields | Units |
|---|---|---|
| R1 Pro robot | X, Y, Yaw | Position in metres; yaw in degrees |
| Tray | X, Y, Z, Yaw | Position in metres; yaw in degrees |

0.01 m = 1 cm. 0.10 m = 10 cm. Yaw is horizontal rotation, not an arm joint angle. Individual robot joint angles are not editable here.

Numeric coordinates use scene axes. Chat instructions such as left/right use the robot's current heading. After rotating the robot, those directions may differ.

Start with a color change, then try small position changes as separate saved versions. Accepting a numeric value is not proof of reachability, collision clearance or task validity.

### Change colors and inspect the view

1. Select the robot for Shell color, or the tray for Tray color.
2. Pick a color using the color control or a swatch.
3. Restore original colors restores the robot and tray colors in the selected room scope.
4. Drag to orbit, use the wheel to zoom, and right-drag to pan.
5. Click Fit view if you lose sight of the scene. Hover over toolbar icons to identify them.

Toggle grid changes the visual reference grid. Moving the viewing camera does not move the robot. Browser materials and lighting are a preview; native Isaac cameras are the rendering evidence.

### Use Scene Agent commands

Select the room first, then send one clear instruction at a time:

```text
Make the tray blue
Move the robot left 1 cm
Rotate the robot 5 degrees
Set robot yaw to 0 degrees
Make the tray blue in all rooms
Restore original colors
What is the training progress?
```

Check the affected room, fields and preview after each command. Rotate adds a relative rotation. Yaw to sets an absolute heading. The current selection is used unless you explicitly target other rooms or all rooms.

Basic commands means the site is using explicit command parsing. Do not expect a complex paragraph to perform collection and training automatically. A progress question only reads status. Sending a scene command first saves pending manual edits; successful scene edits create a new version.

### Save, export and restore

| Action | Expected result |
|---|---|
| Save version | Version vN · Saved appears with the saved scene revision |
| Export | Downloads the current scene JSON: poses, colors and source references, not videos or training data |
| Version history → Restore | Creates a new revision using a historical state; older history remains |
| Reset selected rooms | Restores original poses and colors for the selection; save afterward |
| Reset all 32 rooms | Restores each room's own baseline; save afterward |

Save unsaved changes before restoring history. Undo can reverse a reset. Fit view only changes the view. The top-level vN is the scene revision, not the website release or model checkpoint.

### Synchronize to GPU

1. Confirm the intended room and revision.
2. Click Sync to GPU. Pending edits are saved first.
3. Open Run history.
4. Find Sync scene draft and record its ID, timestamp and artifact directory.
5. Wait for draft_synced or the corresponding successful receipt.

This confirms the server received a draft. It has not executed a robot episode or generated qualified training segments. Outputs can include native_config.draft.json and a visual color sidecar. Changed scenes require new native adaptation and preflight checks; earlier physical checks do not validate the edited draft.

## 5. Turn a new scene into training data

### What a website user should hand over

There is currently no Generate dataset or Add scene to training button that completes this process. Saving a scene does not create a Registered datasets card. Running an evaluation does not automatically convert its videos into training demonstrations.

After synchronization, give the maintainer these details:

```text
Purpose: collect fixed-base Pick/Place demonstrations from a new scene.
Edition: workstation or hosted.
Scene revision: v____.
Room IDs: ____.
Changes: exact robot/tray pose, orientation and color changes.
Scene JSON: saved using Export.
Sync job ID: ____.
Receipt: draft_synced or still pending.
Server artifact directory: ____.
Target: a new independent dataset version; preserve existing training inputs.
```

### Seven maintainer steps

These are server operations, not hidden website buttons. Use reviewed collection configurations rather than restarting historical commands unchanged.

| Step | Work required | Evidence before proceeding |
|---|---|---|
| 1. Bind the initial state | Adapt the draft to the collector; record parent scene, split and version | New configuration and source/initial-state identity |
| 2. Run preflight | Check front-of-table station, fixed base and full dual-arm path | Reachability report; still not physical success |
| 3. Collect natively | Execute Pick, then continue Place from the actual held-tray state | Actual exit receipt, physics result, state/control traces and native videos |
| 4. Validate qualification | Check opposite long-edge contacts, lifting, placement, release/support, fixed base and media alignment | Independent qualification report; preserve failures |
| 5. Export segments | Separate Pick and Place with exact task text, camera/action alignment and time windows | Two segments with source lineage; preparation footage retained separately |
| 6. Freeze and cache | Select qualified pairs, preserve parent splits, freeze manifest/SHA and build model inputs | New immutable dataset manifest and verified cache |
| 7. Register the version | Add the dataset to the backend registry, allowed website IDs and display metadata in a new release | New selectable ID and successful preparation validation |

**Placing a folder on the GPU is not enough.** The website has an explicit allowed dataset ID list. Backend registration, the selection contract and snapshots must agree. Do not replace the old isaac300_20261017 manifest with new data.

Implementation entry points for maintainers are collect_isaac_fixed_pickplace.py, run_isaac_parallel_pickplace.py, export_isaac_parallel_pickplace.py, supervise_isaac_pickplace300.py and studio_prepare_training.py. Registry and input contracts are in gpu/dataset_registry.json, lib/core.ts and lib/training.ts under apps/scene-agent. These names locate code; they are not ready-to-run commands for arbitrary drafts.

Changes to action flow, grasp method, base range, acceptance tolerances or training strategy must follow the project's decision process. Ordinary implementation failures can be repaired in new runs while retaining evidence. Do not relax success gates to increase the number of qualified samples.

### Data that must not be added directly

Unexecuted drafts, preflight-only scenes, failed sources, incomplete media/trajectory exports and diagnostic evaluation outputs are not qualified training sources. Place must have a real recorded starting state; positioning a tray in midair is not a replacement for the preceding Pick.

The fixed-base website branch uses exactly Pick up the tray and Place the tray. The wider project also defines Flush tray to the left, but this two-action dataset is not a complete three-action dataset.

## 6. Inspect dataset counts, lineage and structure

### Check what actually entered training

Open Data & training → Data & recipe → 32-room batch lineage.

| Column | Meaning |
|---|---|
| Batch | Collection batch; expand it to see its server source directory |
| Dataset / version | Dataset version receiving these sources |
| Split | Train, Val or Test source assignment |
| Requested rooms | Number of planned room executions |
| Qualified pairs | Complete Pick/Place sources that passed validation |
| In training | Pairs selected by this frozen training manifest |
| Action segments | Exported action-segment count |
| Qualified overflow | Qualified pairs excluded from this frozen training selection |

Expand Frozen source evidence for the manifest path and SHA256. SHA256 is a content fingerprint that identifies the exact file.

A recorded 19 October 2026 example has 313 qualified source pairs, 300 frozen training pairs and 600 action segments. The other 13 pairs did not enter that training release. Use the live manifest-derived table for current counts; do not report all 313 as training inputs.

### Read Registered datasets cards

| Display name | Dataset ID | Registered scope |
|---|---|---|
| Real Pick / Place | real_pickplace_v2 | User-provided real demonstrations: 134 episodes, Train 102 / Val 13 / Test 19 |
| Isaac · new 300 pairs | isaac300_20261017 | Frozen 300 pairs / 600 segments, simulation Train |
| Isaac · narrow distribution | isaac32_narrow_20261016 | Historical narrow distribution, 30 registered pairs |
| Isaac · wide distribution | isaac32_wide_20261016 | Historical wide distribution, 29 registered pairs |

These are version-specific counts, not proof of a running collection job. Real episodes and simulation pairs are different units. The historical 30 + 29 pairs do not count as new members of the separate 300-pair collection.

### Understand the file relationships

This is a logical diagram. Actual folder names differ by run; read exact paths from the batch table, frozen evidence and job receipt.

```text
Parent scene ID + split
└─ Collection batch
   ├─ Initial state, configuration, seed and source version
   ├─ Native results, events and actual process exit receipt
   ├─ Original camera videos and state/control traces
   └─ Qualified continuous Pick/Place pair
      ├─ Pick: images + states + actions + task text
      └─ Place: images + states + actions + task text
             ↓ frozen selection
Dataset manifest + content fingerprints
             ↓ alignment and caching
Training inputs + normalization derived from Train only
             ↓ independent training job
Recipe + progress/logs + checkpoints + evaluation reports
```

Video counts are larger because segments have multiple cameras. A presentation camera is not automatically a model input. The policy uses head and left/right wrist images; single-run evaluation also displays overview. The model state/action interface has 19 channels covering both arms, grippers and base, with bindings defined by the checkpoint protocol.

The website provides source tables and paths, not a general file browser or a neural-network layer viewer. To inspect architecture or LoRA layer settings, a maintainer must read that checkpoint's configuration. A dataset lineage diagram is not a network architecture diagram.

## 7. Train a model using registered data

### A form-filling example

The example below uses real data plus the new 300-pair simulation dataset, Real 50% / Sim 50%, and 10,000 updates. It demonstrates the controls; it is not a claim that this is the best recipe.

1. Open Data & training and scroll to Data & recipe.
2. Select Real Pick / Place and Isaac · new 300 pairs under Registered datasets.
3. Deselect narrow/wide datasets if they are selected and you do not intend to include them.
4. Find Real / simulation sampling mix in New training job.
5. Click the 50% preset. Confirm Real 50% and Sim 50% above the slider.
6. Enter 10000 in Training steps.
7. Keep Automatically evaluate the final checkpoint enabled if you want automatic evaluation afterward.
8. Optionally click Save recipe and inspect the saved ratio, steps and active dataset count.
9. Click Create training job once.
10. Open Job queue and find the new job by its ID, ratio and update target.

A job receipt proves submission. Increasing actual update counts prove gradient training. Save recipe alone does not start training.

### Set the sampling ratio

| Setting | Required selection | Meaning |
|---|---|---|
| Real 0% / Sim 100% | At least one simulation dataset | Train only from simulation sources |
| Real 10% / Sim 90% | Real and simulation datasets | Mostly simulation sampling |
| Real 50% / Sim 50% | Real and simulation datasets | Equal source-domain sampling proportions |
| Real 90% / Sim 10% | Real and simulation datasets | Mostly real sampling |
| Real 100% / Sim 0% | Real dataset | Train only from real Train data |

Preset buttons represent the **Real percentage**. The slider accepts integers from 0 to 100. This controls sampling, not the number of files on disk; it does not promise an exact ratio in every small batch.

A domain at 0% is excluded from training and normalization even if its card remains selected. Real above 0% requires the real dataset. Sim above 0% requires at least one registered simulation dataset.

### Read the remaining settings

| Field | Meaning |
|---|---|
| Training steps | Actual update target, integer 1–100000; not a duration in seconds |
| π0.5 · LoRA | The training family/method this form creates, not a generic family selector |
| Batch / horizon 8 / 20 | Training batch size and prediction window; currently displayed recipe settings |
| Action balanced · duration weighted | Within-domain action balancing and duration-related sampling |
| Warmup | Initial learning-rate warmup derived from the step target |
| Registered parent · new optimizer | Initialize from registered parent weights with a new optimizer state |

Each creation is an independent run. It does not alter a healthy running job or simply add steps to the current optimizer. Server jobs already received and running can continue after the browser closes; check their actual heartbeat and progress to establish health.

## 8. Track training and automatic evaluation

### Find your own job first

Current training is the server's registered training overview. Its 100% indicator does not prove that your newly submitted job is complete. Use the job ID, ratio and target steps in Job queue to track your independent training.

Run history contains receipts across job types. Job queue mainly lists independent training, MSE and batch VLA jobs. Single-room runs are available under Policy evaluation → Previous runs.

| Status | What has happened | What to do |
|---|---|---|
| Plan saved / planned | A recipe was saved | Click Create training job if execution is intended |
| Awaiting GPU receipt / queued | Request accepted by the website | Keep the ID and wait for the server receipt |
| Received by GPU / claimed | Worker received the request | Follow the next stage |
| Waiting for GPU / waiting_gpu | Resource/task lock unavailable | Do not resubmit |
| Validating data / preparing | Sources and inputs are being checked | No gradient training has been established yet |
| Model initialization / initializing | Loading, compiling or initializing | Update count may remain zero |
| Gradient training / training | Model parameters are being updated | Verify actual updates increase |
| Saving checkpoint | Model save is in progress | Wait for the save to close |
| Checkpoint saved | A milestone was saved | It may not be the final target |
| Finished / completed | This process ended | Read updates, final checkpoint, exit result and evaluations separately |
| Failed / blocked | Failure or intervention required | Record the error, ID and artifact directory |

### Read the progress card

- Steps shows actual updates / target and the corresponding percentage.
- Remaining training estimates the remaining gradient-compute time, usually as a range.
- Next checkpoint shows the next save milestone and its estimate.
- Measured throughput is recent seconds per update, not a future guarantee.
- Saved lists checkpoint update milestones.
- Training loss · recent samples is a recent training curve, not the test curve.
- Sample and Server sample identify when the displayed values were measured.

Training status normally refreshes about every 10 seconds. ETA excludes initialization, checkpoint saving, MSE and VLA evaluation. Zero remaining training time does not mean all evaluations are finished. When the heartbeat expires, ETA pauses and the last measurements remain visible; disconnection does not prove that the remote process stopped.

### After training

Automatic evaluation waits for the target update count, successful training exit and a fully saved final checkpoint. Open After training to follow:

1. 32-room VLA: registered-scene Pick/Place closed-loop diagnostics.
2. Paired real Test MSE: comparison with the registered real-only 10,000-update baseline.
3. MSE figure generation and artifact publication.

Enable for current training enables this for the currently registered training run. It is not a selector for any arbitrary historical model. Use manual evaluation for historical checkpoints. Queueing and evaluation take additional time after training ends.

## 9. Evaluate one room and watch the actual rollout

### Submit one independent run

1. Click Policy evaluation in the top navigation.
2. Under New independent run, select Room 000–031.
3. Select a fully saved Model checkpoint. Check its identity, training source and update count.
4. Explicitly inspect Action handling using the table below.
5. Set Maximum simulation duration (seconds), for example 10.
6. Keep the advanced limits unless you have a specific reason to change them.
7. Click Start policy evaluation once.
8. Wait through Queued and Initializing, then inspect measured frames and cameras.

**The run uses the registered room initial state, not your latest Scene workspace draft.** Matching room numbers do not mean edited settings were applied. A new draft needs adaptation and registration before it can become an evaluation initial state.

### Which task is selected?

The current form always executes **Pick → Place**, continuously, with a fixed base. It does not have a task-text selector. Place continues from the actual held-tray state after Pick.

You choose the room, checkpoint and budget. You cannot select Flush, an arbitrary new instruction or a standalone Place from an arbitrary starting state here.

### Choose Action handling deliberately

| Option | Behavior | Interpretation |
|---|---|---|
| Robot limits · bounded joints, speed and tracking guard | Explicit arm/gripper bounds plus existing speed, step and tracking protections | Protected diagnostic; excluded from pure-model success and automatic training |
| Strict · reject out-of-range actions | Reject an action outside the mechanical range and stop | Strict policy behavior on the registered diagnostic scenes |
| Limit-clipped diagnostic · excluded from pure model success | Clip complete finite predictions to bounds and retain raw/applied actions | Diagnostic continuation; excluded from pure-model success |

Newer workstation builds default to Robot limits. Older releases may default to Strict. Check the actual selection before every submission. Protected runs display PROTECTED POLICY DIAGNOSTIC. These modes do not silently fill missing gripper outputs.

### Understand the three time limits

| Setting | Allowed integer range | What it limits |
|---|---|---|
| Maximum simulation duration | 1–120 seconds | Total executed simulation time shared by Pick and Place |
| Single inference timeout | 1–300 seconds | Waiting for one model request |
| Overall wall-clock guard | 10–3600 seconds | Total real elapsed run time, including model/Isaac initialization |

One simulated second contains 20 action frames. A 10-second budget allows at most 200 frames across both actions. Waiting for model output does not spend simulated time. Task success, model errors or physical failures can stop execution earlier. Media finalization can continue after execution stops.

Increasing the time limit does not fix policy_action_outside_mechanical_joint_range. That means a predicted target violated a joint bound.

### Read live observations and the stop reason

The interactive 3D view uses measured native body poses with the website geometry. The four native camera views are overview, head_left, left_wrist and right_wrist. Browser geometry/materials may differ; native cameras show the simulator's actual rendering.

Read executed frames, simulation seconds, wall time, request latency, Pose sample age and Stop reason together. No new physical frame may be available while the simulator waits for inference. A stationary view alone does not mean the page crashed.

Ended means the view is showing the final recorded state. simulation_time_budget_reached means the budget ended, not that Pick/Place passed. Protected diagnostic completion must remain labeled as diagnostic, even when the motion looks successful.

### Download this run's recordings

1. Select the correct job in Previous runs.
2. Scroll to This run's result & downloads.
3. Wait for recording encoders to close, then download that run's MP4 files and JSON report.
4. Match the room, checkpoint and job ID. Static demo downloads are not results from this new run.

Zero executed frames means no motion video. Native videos normally play on the 20 Hz simulation timeline, while real waiting/timing is in the report. Files explicitly labeled actual wall-clock video have the stated wall-time playback. Smooth video playback is not evidence of sustained 20 Hz real-time inference.

## 10. Evaluate several rooms in a batch

Open Data & training → Evaluation & MSE → Isaac VLA closed loop.

1. Choose ROS 2 topics · isolated simulation under Policy transport. Native file transport · π0.5 is an alternative for π0.5; external families require ROS 2.
2. Choose one Model checkpoint.
3. Click the rooms in Room selection. Selected buttons are highlighted; click again to deselect.
4. Confirm the N/32 count and keep at least one room selected.
5. Set Frame budget per action. Default 200; allowed range 20–1200.
6. Click Create VLA evaluation.
7. Read the matching report in Job queue or below the evaluation forms.

Here 200 frames means 10 simulated seconds **per action**. Single-room policy evaluation uses a total duration shared across the two actions. These budgets are not interchangeable.

The current 32 rooms share a training parent scene. Results are training-scene closed-loop diagnostics, not held-out generalization. Testing a genuinely new parent scene requires an independently registered source; changing a room number or relabeling Train as Test does not create a holdout.

### Read success and coverage together

Record passed pairs, model failures, infrastructure failures, requested rooms and coverage. Automatic summaries compute model success as passed / (passed + model failures), with infrastructure failures separate. Some reports also show passedPairs / totalRooms; read the denominator label.

Example only: request 10 rooms; 4 pass, 4 have model failures and 2 fail before a valid model result. Success among evaluable rooms is 4/8 = 50%, coverage is 8/10 = 80%, and passes over all requests are 4/10. Reporting only 50% hides the incomplete coverage.

No evaluable result means Not measured, not 0% task success. Protected diagnostics must remain separate from strict pure-model success statistics.

## 11. Compare predictions with MSE and download charts

MSE does not move the robot. It feeds recorded real observations to the model and compares predicted actions with the recorded demonstration targets.

### Submit a paired comparison

1. Open Data & training → Evaluation & MSE.
2. Find Fixed real-data MSE comparison.
3. Select Val · 13 real episodes or Test · 19 real episodes under Evaluation split.
4. Select 1–4 fully saved π0.5 checkpoints. Select both old and new models for a comparison.
5. Verify their source and update counts. A 100-update checkpoint is not a 10,000-update checkpoint.
6. Click Run paired MSE.
7. Wait for the matching Real VAL MSE or Real TEST MSE report farther down the page.

Use Val for development decisions and Test for fixed final comparisons; do not repeatedly tune against Test. The current paired MSE interface supports registered π0.5 checkpoints only. Registering G0.5 or GR00T does not make those families compatible with this protocol.

| Result column | Meaning |
|---|---|
| H20 joints rad² | Error over valid 20-step targets for 14 arm joints |
| H20 grippers mm² | Corresponding left/right gripper error |
| First-step joints rad² | Arm error for the first action predicted at each observation |
| First-step grippers mm² | Gripper error for the first predicted action |

Lower is generally better under the same protocol. Do not add arm and gripper errors: their units differ. Base channels and tail padding are excluded. A negative Δ vs baseline means lower error than the baseline.

Keep initialization, update count, ratio, dataset version and split alongside comparisons. Differences cannot automatically be attributed to the simulation percentage alone. Low MSE can coexist with physical closed-loop failure.

### Locate the figures

Go to Data & training → Evaluation & MSE → completed Real TEST/VAL MSE → MSE figures & prediction traces. Run history's MSE comparison completed receipt is not the chart page. After opening the correct tab, browser Find can locate MSE figures.

1. Use Figure to select a chart.
2. Choose Joint MSE or Joint RMSE for arms; Gripper MSE or Gripper RMSE for grippers.
3. Choose an Episode entry for its 4×4 prediction traces.
4. Click the image for full resolution or use Download PNG.
5. Use Per-joint metrics (CSV) for numbers or Download all figures (ZIP) for the complete bundle.

Full Test19 normally produces 24 figures: five summaries plus 19 episode plots. Episode curves show first-step predictions; aggregate MSE uses valid H20 targets. Their statistical scopes differ.

Rendering → Uploading → Ready means plot generation, transfer and download readiness. A figure-export problem does not necessarily invalidate completed MSE numbers. Read Figure export needs attention separately from the model evaluation result.

## 12. Register checkpoints and identify downloads

### Register a model in the workstation edition

Go to Data & training → Evaluation & MSE → Model checkpoint paths.

1. Select π0.5, Galaxea AI G0.5 or NVIDIA GR00T under Model family.
2. Select the actual Gripper unit in checkpoint. Do not guess the mapping.
3. Enter an absolute path on the GPU workstation, not a Windows C: path on your laptop. This is not a file-upload control.
4. Click Register checkpoint path.
5. Read the validation status, then select the checkpoint in an evaluation form.

π0.5 needs a complete checkpoint, model specification, normalization and content bindings. G0.5 requires adjacent configuration and processor files. The project's specified G0.5 model uses 100% = 80 mm opening, but that mapping must not be assumed for every unknown checkpoint. GR00T needs compatible joint-space weights and mappings; a directory path does not convert an incompatible model.

Registration, loading, inference, execution and task success are separate stages. Missing gripper outputs, incomplete mappings or invalid actions can prevent execution. Preserve the G0.5 30 Hz training / 20 Hz diagnostic timing label. Use the workstation setup download for detailed requirements.

### Know what each download contains

| Entry point | Content |
|---|---|
| Scene workspace → Export | Edited scene configuration JSON |
| Policy evaluation → This run's result & downloads | Selected independent run's native videos and report |
| MSE figures → PNG / CSV / ZIP | Error charts, per-joint numbers and provenance |
| Existing demo/source downloads in Help or Data & training | Labeled demonstration, source or launch material, not your new run |
| Server directory displayed in a batch/job | A location reference, not a downloaded dataset |

The source package is not a model-weight package and does not contain all training videos. Full media and trajectories normally remain on the server. Export additional data for an explicit purpose rather than assuming every artifact is in the website download.

## 13. Troubleshoot by symptom

| Symptom | First check | Next action |
|---|---|---|
| Workstation connection refused | Network reachability and service heartbeat | Ask the maintainer to check process identity and exit logs; do not start duplicate services |
| Hosted controls disabled | Owner login, loaded snapshot and required selections | Use the correct account and complete the fields |
| Save version disabled | Is there an Unsaved changes indicator? | No edit needs no save; loading/busy states can also disable it |
| Scene changed / revision conflict | Another window may have saved a revision | Export your pending edits, then reload the latest version |
| Sync succeeded but no new dataset | Is the receipt only draft_synced? | Complete collection, qualification and registration from chapter 5 |
| Evaluation ignores edited positions | Was it a registered initial-state evaluation? | Draft edits are not automatically used by policy evaluation |
| 32 rooms but fewer than 32 pairs | Requested versus Qualified counts | Read qualification/failure evidence and retain actual counts |
| 313 qualified pairs but only 300 in training | Frozen manifest and overflow | That version selected 300; expansion needs a new version |
| Waiting for GPU for a long time | Existing jobs and snapshot freshness | Wait or ask for inspection; do not resubmit |
| Training remains at 0 updates | preparing or initializing stage | Wait for actual gradients; initialization is not training success |
| Current training finished but new job queued | Check job IDs | Follow your own Job queue entry |
| Progress stopped refreshing | Sample age and heartbeat | Retain the last timestamp; disconnection does not prove process termination |
| Evaluation stops after a few frames | Stop reason, especially mechanical limits | More time will not repair an invalid target; retain the strict failure evidence |
| Simulation time limit reached | Executed budget | Read physical outcome; budget exhaustion is not success |
| View frozen during inference | Frames, sample age and model stage | Wait for a new observation instead of inferring a page crash |
| View stationary after Ended | Final measured state label | This is the terminal pose; choose a prior run or create a new one |
| No video available | Zero executed frames, encoder finalization or mediaError | Zero frames have no motion video; otherwise read publication/report details |
| Cloud video missing | Size restriction or publication error | Locate the workstation artifact from the report; distinguish publication from physics failure |
| MSE numbers but no charts | Rendering / Uploading / figure export error | Wait for Ready or inspect the plot export separately |
| Job not visible | Edition, account and page | Receipts may list recent jobs only; retain the exact ID and artifact path |

There is no universal Stop all jobs button. To stop a task, provide the exact ID so a maintainer can verify PID, start time, command and directory. Do not stop unrelated services to clear one queued job.

## 14. Follow a short practical route

### Route A — watch an existing model

Policy evaluation → Room → Model checkpoint → Action handling → simulation duration → Start policy evaluation → Stop reason → this run's video and report.

Record job ID, room, model, handling mode, executed frames, stop reason and task outcome. Keep Robot limits / clipped results labeled as diagnostics.

### Route B — train from existing data

Data & training → Data & recipe → datasets → Real/Sim ratio → Training steps → automatic evaluation option → Create training job → Job queue → final checkpoint → After training or manual evaluation.

Confirm actual target updates, a complete checkpoint, the training exit result and separate evaluation outcomes. A loss screenshot alone is not a complete training/evaluation handover.

### Route C — train on your edited scene

Scene workspace → edit → Save version → Export → Sync to GPU → keep receipt → maintainer adaptation/preflight/collection/validation/freeze/registration → select the new Registered datasets version → Route B.

This route currently includes a maintainer handoff. The website does not expose a single continuous collection-to-training wizard.

### Copy this when reporting an issue

```text
Website edition and occurrence time:
Page and button:
Job ID (full if available):
Room IDs / scene revision:
Dataset version / Real-Sim ratio / target updates:
Model checkpoint:
Action handling, if evaluating:
Simulation budget / inference timeout / wall guard:
Stage / actual update count or executed frames:
Last Sample timestamp:
Exact error or Stop reason:
Artifact directory / report:
```

## 15. Setup references and scope

Use the Help resource area for the workstation and ROS 2 setup guide, the dedicated policy evaluation guide, and labeled source/demo downloads. Download this complete English guide for an offline copy.

For maintainers, repository references are docs/SCENE_TASK_SPEC.md, docs/site/WORKSTATION.md, docs/site/POLICY_EVALUATION.md, docs/project/DATA_CATALOG.md and docs/project/EXPERIMENT_STATUS.md. The task specification governs acceptance conditions; this guide does not change them.

The instructions follow the scene editor, training panel, batch lineage, policy evaluation, model registration and backend contracts. Historical counts are examples with version/date scope. Documentation does not establish current server availability or new physical/model success.
