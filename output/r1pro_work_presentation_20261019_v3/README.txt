R1 Pro: From Lab to Policy - updated technical presentation
Revision 3 | 19 October 2026 | evidence snapshot 18:29 SGT

OPEN THE DECK
R1Pro_Real2Sim_VLA_Technical_Report_v3.pptx
27 English slides; editable text, diagrams, seven tables and four charts.
Click videos in Slide Show on slides 11, 25 and 27.
Standalone MP4 and English SRT files are provided alongside the deck.
The native PowerPoint application was not used to test playback.

CURRENT CONTENT
pi0.5 and robot interfaces; lab reconstruction; scene editing; training and
MSE navigation; single-policy evaluation; data lineage; mixed training;
ROS 2 camera-to-action pipeline; measured model readiness; fixed real Test19
MSE; strict closed-loop failure analysis; runtime optimization; next steps;
full user-provided real-robot recording.

RESULTS AND PROVENANCE
The per_joint_mse.csv and aggregate_and_action_mse.csv retain the earlier
three-model comparison exactly. Slide 22 separately reports the completed
latest automatic paired MSE, included in latest_paired_mse.csv. The latest
real-only baseline differs slightly from the archived baseline; its cause
has not been isolated. No baseline is silently substituted across runs.

Earlier Real90/Sim10: arm MSE -4.04%, gripper MSE -7.86% vs its paired baseline.
Latest Real50/Sim50: arm MSE +6.77%, gripper MSE -12.11% vs its paired baseline.
Initialization, simulated sources and weighting differ between training
recipes. These comparisons do not isolate the causal effect of ratio alone.

Latest strict VLA: Real50/Sim50,10000 updates,0/32 qualified Pick/Place pairs;
32 model failures,0 infrastructure failures,100% coverage. Mechanical range
rejection: left arm joint4 in29 rooms,right arm joint4 in3 rooms. These are
training-parent room diagnostics, not held-out-scene generalization.

Runtime: same Room000,Real90/Sim10 checkpoint,40 frames/2 simulated seconds,
identical robot limits. Rollout15.870699s ->4.744614s,3.34499x speedup.
Real-time factor0.12602x ->0.42153x; sustained real time is not achieved.
Protected output is excluded from pure-model success and training. Both
runs stopped at the time limit. One short pair does not establish long-run
stability; CPU/GPU physics and asynchronous observations can differ.

MEDIA
11: Scene editing walkthrough, GLB camera/color preview and native expert
    Pick/Place. Source captions distinguish preview from physical simulation.
25: Original wall-time baseline and optimized recordings shown together.
    Waiting time remains visible. The optimized final frame is explicitly
    held after its4.8s encoded clip while the baseline continues. No generated
    motion. Source footage is320x180; encoded timing is rounded to video frames.
27: Complete user-provided72.93s real-robot recording, original speed/audio.
    User identifies Real10/Sim90,10000 updates. Exact checkpoint and execution
    mode remain unverified. This is not the Real90/Sim10 MSE model.

READING THE WEBSITE
Data & training > Evaluation & MSE > Real TEST MSE > Figure.
Policy evaluation > room/checkpoint/duration > per-run results and downloads.
The latest runtime comparison and robot-limits default are on the offline
workstation; hosted frontend and workstation releases differ.
The dialogue currently uses a basic instruction parser; GPT is unconfigured.

VALIDATION
All27 slides rendered and reviewed. Package/layout, native table/chart,
embedded workbook and media-relationship checks are performed. All three MP4s
fully decode through FFmpeg. The current revision does not start training,
run a new simulation, modify frozen inputs or control physical hardware.

SOURCE RECORDS
runs/presentation_20261019_v3/workstation_bootstrap.json
runs/presentation_20261019_v3/automatic_evaluation.json
runs/web_realtime_optimization_20261019/comparison.json and audit.json
runs/presentation_20261019_v1/DELIVERY.md
Research references remain in slide notes: pi.website/blog/pi05;
arxiv.org/abs/2504.16054; github.com/Physical-Intelligence/openpi.
