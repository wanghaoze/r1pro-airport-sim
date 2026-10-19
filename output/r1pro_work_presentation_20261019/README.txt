R1 Pro: From Lab to Policy
English technical report, 19 October 2026

FILES
R1Pro_Real2Sim_VLA_Technical_Report_v2.pptx
  22 slides. Text, tables, pipeline diagrams and three MSE charts are editable.
  Videos are embedded on slides 10 and 22. Click the video in Slide Show.
demo_english.mp4
  Website walkthrough, camera/color preview, and native Isaac Pick/Place.
real_robot_english.mp4
  The complete user-provided 72.93-second recording at original speed.
*.srt
  Separate English caption files. Captions are also burned into the videos.
per_joint_mse.csv
  Original numerical MSE values for all 14 arm joints and both grippers.
aggregate_and_action_mse.csv
  Overall, Pick and Place breakdowns.
evaluation_protocol.json
  Evaluation denominator, provenance and summary values.

EVIDENCE
Real test set: 19 episodes (11 Pick, 8 Place), 3,653 frames at 20 Hz.
Horizon: 20. Tail padding is excluded, leaving 69,450 window timesteps.
Overlapping prediction windows are not independent observations.
Arms use rad^2. Grippers use mm^2. Base outputs are excluded.
Chart workbooks use 12 significant digits for Excel compatibility.
The CSV files retain the original report values.

The archived real-only and 90% real / 10% simulation models are a paired
comparison. The 50% real / 50% simulation model uses a fresh full-frame run
of the same evaluation protocol. These models differ in initialization,
simulation sources and training recipes. This is not a controlled causal
ablation of data ratio alone. Offline MSE is not a task success rate.

The real-robot video's training recipe is user-reported: 10% real data +
90% simulation, 10,000 updates. Its exact checkpoint hash and execution
mode have not been independently verified. It is a different recipe from
the archived 90% real / 10% simulation model in the MSE plots.

MEDIA SOURCES
Website screenshots: the actual English Scene Studio interface.
Camera/color recording: original website GLB and material rules in a
presentation viewer. It shows a static pose, not a physics rollout.
Isaac clip: actual expert-controlled physical Pick/Place recording from
isaacsim_reachable_fixedbase_20261016_v1/case_000/presentation.mp4.
Preparation lasts 3.3 seconds, followed by 3 seconds Pick and 3 seconds Place.
This expert demonstration does not establish VLA closed-loop success.
Real-robot clip: user-provided footage. Presentation exports omit location
metadata and preserve the visual sequence and audio at original speed.

RESEARCH AND AUTHORING
Primary model references are cited in the slide speaker notes:
https://www.pi.website/blog/pi05
https://arxiv.org/abs/2504.16054
https://github.com/Physical-Intelligence/openpi
Professional Presentations skill with Artifact Tool for editable slides.
Open-source FFmpeg for video encoding and subtitles.
Microsoft PresentationML video embedding specification:
https://learn.microsoft.com/en-us/office/open-xml/presentation/how-to-add-a-video-to-a-slide-in-a-presentation

VALIDATION
Every slide is rendered and visually reviewed. Package, layout, editable
chart data and embedded video relationships are checked programmatically.
Native Microsoft PowerPoint playback has not been exercised in this session.
Standalone MP4 copies provide a portable playback option.

LATEST WEBSITE UPDATE
Source: https://chatgpt.com/s/cx_6ad5ad23e2c88191b724e1988089716e
Read on 19 October 2026 and incorporated into slide 9 and slide 21.
Navigation: Data & training > Evaluation & MSE > Real TEST MSE >
MSE figures & prediction traces > Figure. Run history shows job status.
Select joint MSE/RMSE bars or episode 4x4 traces; download PNG, CSV or ZIP.
The 24 published historical figures use a 100-update mixed checkpoint versus
a 10,000-update baseline. They are UI examples, separate from the
10,000-update models compared in this presentation. Automatic final-checkpoint
jobs were queued in the shared record; no VLA success is inferred.
