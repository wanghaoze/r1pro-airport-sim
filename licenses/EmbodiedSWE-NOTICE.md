# EmbodiedSWE experiment workflow attribution

Source: local EmbodiedSWE checkout, commit d34837e (README: link the arXiv paper).
Upstream project: EmbodiedSWE, https://github.com/EmbodiedSWE/EmbodiedSWE
License: Apache License 2.0; a copy is in EmbodiedSWE-Apache-2.0.txt.

The workflow and prompt structure are adapted from eval/prompts/tool_router.md,
eval/prompts/_contract.md and the roles of eval/tools/{checkpoint_tree,parameter_search,
sweep,assessment,scene_view}.py. Implementations under r1pro_teleop/experiments are
rewritten for this project's MuJoCo contracts: separate processes, JSON/NPZ checkpoints,
strict physics gates, immutable campaigns, diagnostic-only traces, and fixed scene splits.
No Isaac implementation, grasp-weld mechanism, external assets or upstream vendor tree
is incorporated. CMA-ES is supplied by the separately installed `cma` package.
