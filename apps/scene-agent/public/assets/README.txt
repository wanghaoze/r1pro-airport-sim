Load assets/r1pro-scene.glb with Three.js GLTFLoader. Keep every r1pro-scene-buffer-N.bin
beside the GLB; the loader resolves them automatically. All files are below 8 MiB.

Top-level groups: robot, tray, tables, room. Geometry is shared-safe; clone materials
when applying room-specific colors. Only recolor meshes where
mesh.userData.editableColor equals 'robot' or 'tray'. The protectedAppearance flag
locks source grippers, fingers and head-camera shell. Existing authorized wrist
camera visual housings are absent; this does not modify any physical asset.

Coordinate conversion: source [X forward, Y left, Z up] -> glTF [X, Z, -Y].
robot.position.set(sourceX, 0, -sourceY); robot.rotation.y = sourceYaw;
tray.position.set(sourceX, sourceZ, -sourceY); tray.rotation.y = sourceYaw;
Positions replace the initial values; robot/tray geometry is local to their roots.
Tables are already in absolute room-local coordinates, with unchanged source layout.

The GLB binds to room 000 of the 2026-10-17 batch_001 registered configuration.
This is a visual preview, not live PhysX state. Exact imported server USD/XML was
not locally available; actual project parent geometry is used. Source SHA values,
render geometry counts, pose provenance and limitations: source-manifest.json.

The room group is optional photo-inspired background. It includes decorative office
desks and chairs, separate from the three physical task tables. For a clear orbit
view hide ceiling_* or set room.visible=false; this is a browser display setting.

Rebuild from the repository root with:
.conda/experiment/python.exe apps/scene-agent/tools/build_scene_assets.py
