"""Explicit integration helpers. Not installed into the running Isaac producer.

materialize_config is CPU-only. apply_visual_colors requires Isaac's USD SDK
and a server-owned allowlist of visual mesh paths discovered from the real stage.
"""
import copy
import math
from pathlib import Path

from executor import PROFILE, VERSION, validate


def materialize_config(source_config, command, new_output):
    """Return a new config + visual sidecar; never mutate the original input.

    The caller must rerun private path qualification and write into a new run.
    Never feed this result straight to production: stale precheck attestations
    are invalidated and native collection requires independent qualification.
    """
    validate(command)
    if command["op"] != "scene.patch":
        raise ValueError("scene_patch_required")
    if source_config.get("rooms") != 32 or len(source_config.get("cases", [])) != 32:
        raise ValueError("registered_32_room_config_required")
    if not new_output or str(new_output) == str(source_config.get("output")):
        raise ValueError("new_output_required")
    if Path(new_output).exists():
        raise ValueError("output_already_exists")
    config = copy.deepcopy(source_config)
    config["output"] = str(new_output)
    changes = command["args"]["changes"]
    for room in command["args"]["rooms"]:
        case = config["cases"][room]
        if "robot_base_pose" in changes:
            case["initial_base_world"] = changes["robot_base_pose"][:]
            case["fixed_base_world"] = changes["robot_base_pose"][:]
        if "tray_pose" in changes:
            x, y, z, yaw = changes["tray_pose"]
            case["tray_pose"] = [x, y, z, math.cos(yaw / 2), 0., 0., math.sin(yaw / 2)]
        case.pop("private_precheck_report", None)
        case["private_path_available"] = False
    # Kept separate: current native script ignores unknown visual config fields.
    visual = dict(version=VERSION, profile=PROFILE, rooms=command["args"]["rooms"],
                  colors={k: v for k, v in changes.items() if k.endswith("_color")})
    return dict(status="requires_native_adapter_and_preflight", config=config, visual_overrides=visual,
                native_launchable=False, note="Do not run current producer until visual hook and fresh preflight are wired")


def linear_rgb(hex_color):
    values = [int(hex_color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    return [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]


def apply_visual_colors(stage, visual, trusted_visual_paths, *, before_first_step):
    """Session-layer render materials only. Use a disposable NEW native stage.

    trusted_visual_paths = {room_index: {'robot_color': [mesh paths],
                                       'tray_color': [mesh paths]}}.
    Discover paths server-side; never accept arbitrary prim paths from the LLM.
    Exclude the entire gripper, fingers and camera parts from robot_color paths.
    """
    if before_first_step is not True:
        raise ValueError("initialization_only_before_first_step")
    command = dict(version=VERSION, request_id="visual-validation", op="scene.patch",
                   args=dict(profile=PROFILE, rooms=visual["rooms"], changes=visual["colors"]))
    if not visual["colors"]:
        return dict(status="no_visual_change")
    validate(command)
    from pxr import Usd, UsdGeom, UsdPhysics, UsdShade, Sdf, Gf
    from r1pro_teleop.real2sim.isaac_lab_visuals import physics_fingerprint
    targets = []
    for room in visual["rooms"]:
        for kind, color in visual["colors"].items():
            paths = trusted_visual_paths.get(room, {}).get(kind, [])
            if not paths:
                raise ValueError("registered_visual_meshes_missing")
            for path in paths:
                prim = stage.GetPrimAtPath(path)
                if not str(path).startswith(f"/World/envs/env_{room}/Scene/"):
                    raise ValueError("visual_target_outside_room")
                if any(word in str(path).lower() for word in ("gripper", "finger", "camera", "zed")):
                    raise ValueError("preserved_gripper_or_camera_visual")
                if (not prim or not prim.IsA(UsdGeom.Mesh) or prim.IsInstanceProxy()
                        or prim.HasAPI(UsdPhysics.CollisionAPI) or prim.HasAPI(UsdPhysics.RigidBodyAPI)):
                    raise ValueError("render_only_editable_mesh_required")
                targets.append((room, kind, color, prim))
    before = physics_fingerprint(stage)
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        for room, kind, color, prim in targets:
            base = f"/WebAgentVisuals/room_{room}/{kind}"
            material = UsdShade.Material.Define(stage, base)
            shader = UsdShade.Shader.Define(stage, base + "/Surface")
            shader.CreateIdAttr("UsdPreviewSurface")
            shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*linear_rgb(color)))
            shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(1.)
            material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(material, materialPurpose="preview")
    after = physics_fingerprint(stage)
    if before != after:
        raise ValueError("visual_patch_modified_physics_or_original_cameras")
    return dict(status="session_colors_applied", mesh_count=len(targets),
                physics_and_original_camera_fingerprint=after, native_render_verified=False)
