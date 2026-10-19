"""Project-owned openpi extension; vendor files and system Python are untouched.

BC updates pi0.5 LoRA weights. Simulation-expert DAgger aggregates fresh expert
labels; neither is represented as Microsoft's latent-steering FlowDAgger.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import importlib
import json
import math
import os
from pathlib import Path
import sys
import numpy as np


MODEL_CAMERAS = {"base_0_rgb": "head_left", "left_wrist_0_rgb": "left_wrist",
                 "right_wrist_0_rgb": "right_wrist"}


class AirportInputs:
    """Same adapter for dataset repacking and live policy observations."""
    def __init__(self, prompt_mode="legacy"):
        from .prompts import validate_prompt_mode
        self.prompt_mode = validate_prompt_mode(prompt_mode)

    def __call__(self, data):
        state = np.asarray(data["state"], dtype=np.float32)
        if state.shape != (19,) or not np.isfinite(state).all():
            raise ValueError("mobile19 requires finite 19-dimensional state")
        if self.prompt_mode == 'single_tray_action3_v1' and np.any(state[16:] != 0):
            raise ValueError('Fixed-front state base offsets must be explicitly zero')
        images = {}
        for target, source in MODEL_CAMERAS.items():
            value = np.asarray(data["image/" + source])
            if value.ndim != 3:
                raise ValueError("Camera image must have three dimensions")
            if value.shape[0] == 3 and value.shape[-1] != 3:
                value = np.transpose(value, (1, 2, 0))
            if value.shape[-1] != 3 or not np.isfinite(value).all():
                raise ValueError("Camera image must be finite RGB")
            if np.issubdtype(value.dtype, np.floating):
                if value.min() < 0 or value.max() > 1:
                    raise ValueError("Floating RGB must be in [0,1]")
                value = (value * 255).astype(np.uint8)
            elif value.dtype != np.uint8:
                raise ValueError("RGB must be uint8 or normalized float")
            images[target] = value
        out = {"state": state, "image": images,
               "image_mask": {key: np.True_ for key in images}}
        if "actions" in data:
            actions = np.asarray(data["actions"], dtype=np.float32)
            if actions.ndim != 2 or actions.shape[-1] != 19 or not np.isfinite(actions).all():
                raise ValueError("Expert action chunks must be finite H x 19")
            if self.prompt_mode == 'single_tray_action3_v1' and np.any(actions[..., 16:] != 0):
                raise ValueError('Fixed-front expert base commands must be zero')
            out["actions"] = actions
        if "prompt" in data:
            if self.prompt_mode == "legacy":
                out["prompt"] = data["prompt"]
            else:
                from .prompts import normalize_prompt
                out["prompt"] = normalize_prompt(data["prompt"], self.prompt_mode)
        return out


class AirportOutputs:
    def __init__(self, prompt_mode="legacy"):
        from .prompts import validate_prompt_mode
        self.prompt_mode = validate_prompt_mode(prompt_mode)

    def __call__(self, data):
        actions = np.asarray(data["actions"])[..., :19]
        if actions.ndim != 2 or actions.shape[-1] != 19 or not np.isfinite(actions).all():
            raise ValueError("Policy action chunk is invalid")
        if self.prompt_mode == "single_tray_action3_v1":
            raw = actions.copy()
            masked = actions.copy(); masked[..., 16:] = 0
            return {"actions": masked, "raw_actions": raw,
                    "model_action_mask": np.asarray([True] * 16 + [False] * 3)}
        if self.prompt_mode == "three_table_single_tray_action3_v1":
            return {"actions": actions.copy(), "raw_actions": actions.copy(),
                    "model_action_mask": np.asarray([True] * 19)}
        return {"actions": actions}


@dataclass(frozen=True)
class TrainingSpec:
    dataset_root: str
    dataset_repo_id: str
    openpi_root: str
    base_params: str
    run_dir: str
    name: str = "pi05_airport_mobile19_lora"
    action_horizon: int = 20
    batch_size: int = 8
    num_train_steps: int = 1000
    save_interval: int = 250
    seed: int = 42
    num_workers: int = 2
    fsdp_devices: int = 1
    lora: bool = True
    aggregation_manifest: str | None = None
    dagger_mix_ratio: float = .5
    parent_trained_status: str | None = None
    lr_warmup_steps: int | None = None
    lr_peak: float = 2.5e-5
    lr_end: float = 2.5e-6
    bc_skill_balance: bool = False
    bc_warmstart_parent_status: str | None = None
    bc_warmstart_parent_checkpoint_id: str | None = None
    bc_warmstart_source_audit: str | None = None
    normalization_policy: str = "default_train_only"
    prompt_mode: str = "legacy"

    def validate(self):
        from .prompts import validate_prompt_mode
        validate_prompt_mode(self.prompt_mode)
        if type(self.lora) is not bool:
            raise ValueError("lora must be boolean")
        if type(self.bc_skill_balance) is not bool:
            raise ValueError("bc_skill_balance must be boolean")
        for field in ("action_horizon", "batch_size", "num_train_steps", "save_interval", "fsdp_devices"):
            value = getattr(self, field)
            if type(value) is not int or value <= 0:
                raise ValueError(field + " must be a positive integer")
        resolved_lr_schedule(self)
        if not self.dataset_repo_id or self.dataset_repo_id == "fake":
            raise ValueError("A real dataset is required")
        root = Path(self.dataset_root).resolve()
        info = json.loads((root / "meta/info.json").read_text(encoding="utf-8"))
        if float(info["fps"]) != 20:
            raise ValueError("Dataset must be 20 Hz")
        if int(info.get("total_frames", 0)) < self.batch_size:
            raise ValueError("Dataset needs at least one complete training batch")
        for key in ("observation.state", "action"):
            if info["features"][key]["shape"] != [19]:
                raise ValueError("Dataset must use mobile19 absolute actions/state")
        for camera in MODEL_CAMERAS.values():
            if "observation.images." + camera not in info["features"]:
                raise ValueError("Dataset missing model camera " + camera)
        manifest = json.loads((root / "airport_training_manifest.json").read_text(encoding="utf-8"))
        if manifest.get("split") != "train" or not manifest.get("episodes"):
            raise ValueError("Only nonempty prepared train split may be optimized")
        if (manifest.get("action_semantics") != "absolute_mobile19" or manifest.get("fps") != 20
                or manifest.get("state_semantics") != "measured_joint16_plus_base_origin_offset3"):
            raise ValueError("Training provenance/action semantics not verified")
        if any(row.get("split") != "train" for row in manifest["episodes"]):
            raise ValueError("Validation/test scene leaked into training")
        source = Path(self.openpi_root).resolve()
        if not (source / "src/openpi/training/config.py").is_file():
            raise ValueError("Official openpi source checkout is missing")
        weights = Path(self.base_params).resolve()
        if not weights.is_dir() or not any(p.is_file() for p in weights.rglob("*")):
            raise ValueError("Real local pi05 parameter checkpoint is required")
        if self.bc_warmstart_parent_status is not None:
            if self.aggregation_manifest is not None or self.parent_trained_status is not None:
                raise ValueError("BC warmstart and DAgger parent modes are mutually exclusive")
            if self.normalization_policy != "preserve_verified_parent_train_stats":
                raise ValueError("BC warmstart requires explicit preserved parent normalization")
            verified_bc_warmstart(self)
        elif self.normalization_policy != "default_train_only" or self.bc_warmstart_parent_checkpoint_id is not None or self.bc_warmstart_source_audit is not None:
            raise ValueError("BC warmstart normalization/identity requires a parent status")
        if self.aggregation_manifest is not None:
            if isinstance(self.dagger_mix_ratio, bool) or not 0 < self.dagger_mix_ratio < 1:
                raise ValueError("DAgger mixture ratio must be in (0,1)")
            if not self.parent_trained_status:
                raise ValueError("DAgger requires a trained parent checkpoint status")
            parent = json.loads(Path(self.parent_trained_status).read_text(encoding="utf-8"))
            if (parent.get("status") != "checkpoint_saved" or parent.get("checkpoint_verified") is not True
                    or parent.get("model") != "pi05" or parent.get("training_steps", 0) <= 0
                    or parent.get("fps") != 20 or parent.get("action_semantics") != "absolute_mobile19"):
                raise ValueError("DAgger parent has not actually completed pi05 training")
            if weights != (Path(parent["checkpoint"]) / "params").resolve():
                raise ValueError("DAgger must load the parent trained parameters, not base weights")
            for key in ("action_horizon", "lora", "dataset_repo_id", "dataset_root", "prompt_mode"):
                actual = parent["spec"].get(key, getattr(TrainingSpec, key, None))
                if actual != getattr(self, key):
                    raise ValueError("DAgger parent model/data semantics changed: " + key)
            if not Path(parent["normalization"]).is_file():
                raise ValueError("DAgger parent train-only normalization is missing")
            aggregate = json.loads(Path(self.aggregation_manifest).read_text(encoding="utf-8"))
            if aggregate.get("status") != "aggregation_manifest_not_trained" or not aggregate.get("interventions"):
                raise ValueError("DAgger aggregate is missing verified intervention samples")
        elif self.parent_trained_status is not None:
            raise ValueError("Parent trained status is only used with explicit DAgger aggregation")
        return self


def _sha256_file(path):
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def verified_bc_warmstart(spec):
    """Bind a new BC dataset to real parent parameters and source-level superset."""
    import hashlib
    path = Path(spec.bc_warmstart_parent_status).resolve()
    parent = json.loads(path.read_text(encoding='utf-8'))
    old = parent['spec']
    from .prompts import validate_prompt_mode
    parent_prompt_mode = validate_prompt_mode(old.get('prompt_mode', 'legacy'))
    checkpoint = Path(parent.get('checkpoint', '')).resolve()
    steps = parent.get('training_steps')
    expected = Path(old['run_dir']).resolve() / 'checkpoints' / old['name'] / 'training'
    if (parent.get('status') != 'checkpoint_saved' or parent.get('checkpoint_verified') is not True
            or parent.get('model') != 'pi05' or parent.get('fps') != 20
            or parent.get('action_semantics') != 'absolute_mobile19'
            or parent.get('source') != 'simulation/program_generated'
            or type(steps) is not int or steps <= 0 or steps != old['num_train_steps']
            or checkpoint.parent != expected or not checkpoint.name.isdecimal()
            or parent.get('checkpoint_step') != int(checkpoint.name) or int(checkpoint.name) >= steps):
        raise ValueError('BC warmstart requires a real completed parent checkpoint')
    if Path(spec.base_params).resolve() != checkpoint / 'params':
        raise ValueError('BC warmstart must load the exact parent trained parameters')
    for key in ('action_horizon', 'lora'):
        if old.get(key, getattr(TrainingSpec, key)) != getattr(spec, key):
            raise ValueError('BC warmstart model semantics changed: ' + key)
    for name in ('params', 'train_state'):
        if not any(p.is_file() and p.stat().st_size for p in (checkpoint / name).rglob('*')):
            raise ValueError('BC warmstart parent checkpoint is incomplete: ' + name)
    norm = checkpoint / 'assets' / old['dataset_repo_id'] / 'norm_stats.json'
    if not norm.is_file() or not norm.stat().st_size:
        raise ValueError('BC warmstart checkpoint normalization is missing')
    if _sha256_file(norm) != _sha256_file(parent['normalization']):
        raise ValueError('BC warmstart parent normalization bytes disagree')
    files = sorted(p for p in (checkpoint / 'params').rglob('*') if p.is_file()) + [norm]
    inventory = [{'path': p.relative_to(checkpoint).as_posix(), 'sha256': _sha256_file(p),
                  'bytes': p.stat().st_size} for p in files]
    identity_material = {'training_status_sha256': _sha256_file(path), 'files': inventory}
    identity = 'sha256:' + hashlib.sha256(json.dumps(identity_material, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    if spec.bc_warmstart_parent_checkpoint_id != identity:
        raise ValueError('BC warmstart parent checkpoint content identity mismatch')
    manifests = [Path(old['dataset_root']) / 'airport_training_manifest.json',
                 Path(spec.dataset_root) / 'airport_training_manifest.json']
    if not spec.bc_warmstart_source_audit:
        raise ValueError('BC warmstart requires a verified source-frame/XML lineage audit')
    audit_path = Path(spec.bc_warmstart_source_audit).resolve()
    lineage = json.loads(audit_path.read_text(encoding='utf-8'))
    coverage_mode=lineage.get('schema')=='airport_vla_source_coverage_superset/1'
    if (lineage.get('schema') not in ('airport_vla_source_superset/1','airport_vla_source_coverage_superset/1') or lineage.get('verified') is not True
            or lineage.get('source_frame_values_verified') is not True
            or lineage.get('source_scene_xml_verified') is not True):
        raise ValueError('BC warmstart source lineage audit is not verified')
    if coverage_mode and lineage.get('constituent_phase_coverage_verified') is not True:
        raise ValueError('BC warmstart constituent phase coverage is not verified')
    sets = []
    coverage_sets=[]
    child_coverage_mappings=[]
    trace_hashes = {}
    datasets = lineage.get('datasets', [])
    if len(datasets) != 2 or {item.get('role') for item in datasets} != {'parent', 'child'}:
        raise ValueError('BC warmstart lineage dataset roles are invalid')
    for side, manifest_path in zip(('parent', 'child'), manifests, strict=True):
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        dataset = next(item for item in datasets if item['role'] == side)
        expected_repo = old['dataset_repo_id'] if side == 'parent' else spec.dataset_repo_id
        scene_ids = {row['scene_id'] for row in manifest['episodes']}
        if (Path(dataset['dataset']).resolve() != manifest_path.parent.resolve()
                or dataset['repo_id'] != expected_repo or manifest.get('repo_id') != expected_repo
                or Path(dataset['training_manifest']).resolve() != manifest_path.resolve()
                or Path(dataset['source_manifest']).resolve() != Path(manifest['source_manifest']).resolve()
                or set(dataset['scenes']) != scene_ids or dataset['scene_count'] != len(scene_ids)):
            raise ValueError('BC warmstart lineage dataset/path/repo/scene binding mismatch')
        if lineage.get(side + '_training_manifest_sha256') != _sha256_file(manifest_path):
            raise ValueError('BC warmstart lineage training manifest identity mismatch')
        if (lineage.get(side + '_source_manifest_sha256') != _sha256_file(manifest['source_manifest'])
                or manifest['source_manifest_sha256'] != lineage[side + '_source_manifest_sha256']):
            raise ValueError('BC warmstart lineage source manifest identity mismatch')
        if (manifest.get('split') != 'train' or manifest.get('normalization_split') != 'train_only'
                or manifest.get('fps') != 20 or manifest.get('action_semantics') != 'absolute_mobile19'
                or manifest.get('state_semantics') != 'measured_joint16_plus_base_origin_offset3'
                or manifest.get('environment_source') != 'simulation'
                or manifest.get('controller_source') != 'program_generated'
                or manifest.get('human_demonstration') is not False
                or manifest.get('official_loader_every_episode_first_last') is not True
                or manifest.get('training_video_encoding_verification', {}).get('verified') is not True
                or not manifest.get('episodes')):
            raise ValueError('BC warmstart requires officially verified train-only source datasets')
        if coverage_mode:
            from .data_skill_merge import record_sha256
            resources=dataset.get('derived_resource_inventory')
            if (not isinstance(resources,list) or not resources
                    or dataset.get('derived_resource_inventory_sha256')!=record_sha256(resources)):
                raise ValueError('BC warmstart derived resource inventory is not verified')
            actual_files=[]
            for subdir in ('data','meta','videos'):
                for resource in (manifest_path.parent/subdir).rglob('*'):
                    if resource.is_file():actual_files.append(resource.relative_to(manifest_path.parent).as_posix())
            if sorted(actual_files)!=sorted(item['path'] for item in resources):
                raise ValueError('BC warmstart derived resource set changed after audit')
            for resource in resources:
                target=(manifest_path.parent/resource['path']).resolve()
                if (not target.is_relative_to(manifest_path.parent.resolve())
                        or target.stat().st_size!=resource['bytes']
                        or _sha256_file(target)!=resource['sha256']):
                    raise ValueError('BC warmstart derived resource bytes changed after audit')
        identities = set()
        covered_source_records=set()
        source_rows = {row['segment_id']: row for row in
            (json.loads(line) for line in Path(manifest['source_manifest']).read_text(encoding='utf-8').splitlines())}
        checked_scenes = set()
        for row in manifest['episodes']:
            trace = Path(row['source_trace']).resolve()
            sid = row['scene_id']
            source = source_rows[row['segment_id']]
            xml = Path(source['collection']).resolve() / 'scenes' / sid / 'mobile.xml'
            scene = dataset['scenes'][sid]
            if (source['scene_id'] != sid or Path(scene['trace']).resolve() != trace
                    or Path(scene['scene_xml']).resolve() != xml):
                raise ValueError('BC warmstart lineage scene source paths changed')
            if sid not in checked_scenes:
                for resource, expected_hash in ((xml, scene['scene_xml_sha256']),
                        (xml.with_name('scene.json'), scene['scene_json_sha256']),
                        (trace, scene['trace_sha256'])):
                    if _sha256_file(resource) != expected_hash:
                        raise ValueError('BC warmstart scene XML/JSON/trace changed after audit')
                checked_scenes.add(sid)
            if trace not in trace_hashes:
                trace_hashes[trace] = _sha256_file(trace)
            if row.get('split') != 'train' or trace_hashes[trace] != row['source_trace_sha256']:
                raise ValueError('BC warmstart source trace identity or split mismatch')
            a, b = row['source_start_frame'], row['source_end_frame']
            if type(a) is not int or type(b) is not int or not 0 <= a < b or row['frames'] != b-a:
                raise ValueError('BC warmstart source segment interval is invalid')
            if coverage_mode:
                from .data_skill_merge import record_sha256 as record_hash, eligible as source_eligible, coverage_span_identity
                if side=='parent':
                    if not source_eligible(source):raise ValueError('BC warmstart parent source is not eligible')
                    covered_source_records.add(coverage_span_identity(source,row['base_qpos_indices'],scene))
                else:
                    spans=row.get('constituent_phase_spans',[])
                    hashes=row.get('constituent_record_sha256',[])
                    if (source.get('schema')!='airport_vla_skill_contiguous_segments/1'
                            or row['phase']!='skill_contiguous' or not spans or len(spans)!=len(hashes)
                            or spans!=source.get('constituent_phase_spans')
                            or hashes!=source.get('constituent_record_sha256')):
                        raise ValueError('BC warmstart merged constituent inventory differs')
                    cursor=a
                    for span,digest in zip(spans,hashes,strict=True):
                        if (record_hash(span)!=digest or span['scene_id']!=sid
                                or span['start_frame']!=cursor or type(span['end_frame']) is not int
                                or span['end_frame']<=cursor or span['end_frame']>b
                                or span['skill']!=row['skill'] or span['language_prompt']!=row['language_prompt']
                                or span['operation_index']!=row['operation_index']
                                or Path(span['collection']).resolve()!=Path(source['collection']).resolve()
                                or not source_eligible(span)):
                            raise ValueError('BC warmstart constituent continuity/quality/hash changed')
                        identity_span=coverage_span_identity(span,row['base_qpos_indices'],scene)
                        if identity_span in covered_source_records:
                            raise ValueError('BC warmstart duplicate source constituent coverage')
                        covered_source_records.add(identity_span)
                        child_coverage_mappings.append(dict(identity=identity_span,merged_segment_id=row['segment_id'],
                                                            merged_episode_index=row['episode_index']))
                        cursor=span['end_frame']
                    if cursor!=b:raise ValueError('BC warmstart merged source interval has a gap')
            identities.add((row['scene_id'], row['segment_id'], row['source_trace_sha256'], a, b,
                row['skill'], row['phase'], row['operation_index'], row['language_prompt'], tuple(row['base_qpos_indices']),
                row['state_semantics'], row['action_semantics'], row['fps']))
        if len(identities) != len(manifest['episodes']):
            raise ValueError('BC warmstart duplicate source segment identities')
        sets.append(identities)
        coverage_sets.append(covered_source_records)
    if coverage_mode:
        from .data_skill_merge import coverage_binding_hash
        coverage_hash=coverage_binding_hash(coverage_sets[0],child_coverage_mappings)
        if lineage.get('coverage_identity_sha256')!=coverage_hash:
            raise ValueError('BC warmstart coverage content identity mismatch')
        if not coverage_sets[0].issubset(coverage_sets[1]):
            raise ValueError('BC warmstart child constituents do not cover exact parent source records')
    elif not sets[0].issubset(sets[1]):
        raise ValueError('BC warmstart new dataset is not a verified source-segment superset')
    return {'parent_checkpoint_id': identity, 'parent_checkpoint': str(checkpoint),
            'parent_prompt_mode': parent_prompt_mode, 'prompt_mode': spec.prompt_mode,
            'parent_status': str(path), 'normalization_source': str(norm),
            'normalization_sha256': _sha256_file(norm), 'parent_dataset_repo_id': old['dataset_repo_id'],
            'dataset_repo_id': spec.dataset_repo_id, 'parent_manifest_sha256': _sha256_file(manifests[0]),
            'dataset_manifest_sha256': _sha256_file(manifests[1]),
            'source_lineage_audit': str(audit_path), 'source_lineage_audit_sha256': _sha256_file(audit_path),
            'verified_parent_segments': len(sets[0]), 'verified_new_segments': len(sets[1]),
            'source_lineage_schema':lineage['schema'],
            'verified_constituent_coverage':coverage_mode,
            'verified_parent_constituents':len(coverage_sets[0]) if coverage_mode else None,
            'verified_child_constituents':len(coverage_sets[1]) if coverage_mode else None,
            'coverage_identity_sha256':lineage.get('coverage_identity_sha256') if coverage_mode else None,
            'normalization_policy': 'preserve_verified_parent_train_stats',
            'optimizer_policy': 'new_optimizer_weights_only_warmstart'}


def copy_verified_warmstart_stats(audit, destination):
    import shutil
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = Path(audit['normalization_source'])
    if _sha256_file(source) != audit['normalization_sha256']:
        raise ValueError('BC warmstart normalization changed after verification')
    shutil.copyfile(source, destination)
    if _sha256_file(destination) != audit['normalization_sha256']:
        raise ValueError('BC warmstart copied normalization hash mismatch')


def resolved_lr_schedule(spec):
    """Short smoke runs reach their peak; long runs retain <=1000 warmup steps."""
    total = spec.num_train_steps
    if type(total) is not int or total <= 0:
        raise ValueError("num_train_steps must be a positive integer")
    warmup = min(1000, total // 10) if spec.lr_warmup_steps is None else spec.lr_warmup_steps
    if type(warmup) is not int or not 0 <= warmup < total:
        raise ValueError("lr_warmup_steps must be a nonnegative integer below num_train_steps")
    for key in ("lr_peak", "lr_end"):
        value = getattr(spec, key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(key + " must be finite and positive")
    if spec.lr_end > spec.lr_peak:
        raise ValueError("lr_end cannot exceed lr_peak")
    return {"warmup_steps": warmup, "peak_lr": spec.lr_peak,
            "decay_steps": total, "decay_lr": spec.lr_end}


def project_jax_cache_dir(spec):
    """Canonical project checkout owns compiler artifacts, independent of HOME."""
    source = Path(spec.openpi_root).resolve()
    project = source.parent.parent if source.parent.name == 'third_party' else Path(spec.run_dir).resolve().parent
    cache = (project / 'resources' / 'jax_cache').resolve()
    if not cache.is_relative_to(project):
        raise ValueError('JAX compilation cache must remain inside the project')
    return cache


@contextmanager
def redirect_jax_compilation_cache(config, cache_path):
    """Redirect only the upstream hard-coded cache update, then restore API."""
    cache_path = Path(cache_path).resolve()
    original = config.update
    had_instance_update = 'update' in getattr(config, '__dict__', {})
    previous_instance_update = getattr(config, '__dict__', {}).get('update')
    def project_update(name, *args, **kwargs):
        if name == 'jax_compilation_cache_dir':
            if args:
                args = (str(cache_path), *args[1:])
            elif 'val' in kwargs:
                kwargs = {**kwargs, 'val': str(cache_path)}
        return original(name, *args, **kwargs)
    config.update = project_update
    try:
        yield
    finally:
        if had_instance_update:
            config.update = previous_instance_update
        else:
            del config.update


def build_openpi_config(spec: TrainingSpec):
    """Uses openpi's custom DataConfigFactory and official trainer without edits."""
    spec.validate()
    source = Path(spec.openpi_root).resolve()
    sys.path.insert(0, str(source / "src"))
    from openpi.training import config as oc
    from openpi.training import weight_loaders
    from openpi.training import optimizer
    from openpi.models.pi0_config import Pi0Config
    from openpi import transforms

    @dataclass(frozen=True)
    class AirportDataConfig(oc.DataConfigFactory):
        def create(self, assets_dirs, model_config):
            import dataclasses
            return dataclasses.replace(
                self.create_base_config(assets_dirs, model_config),
                repack_transforms=transforms.Group(inputs=[transforms.RepackTransform({
                    "state": "observation.state", "actions": "action", "prompt": "prompt",
                    **{"image/" + name: "observation.images." + name for name in MODEL_CAMERAS.values()},
                })]),
                data_transforms=transforms.Group(inputs=[AirportInputs(spec.prompt_mode)], outputs=[AirportOutputs(spec.prompt_mode)]),
                model_transforms=oc.ModelTransformFactory()(model_config),
                action_sequence_keys=("action",), prompt_from_task=True,
            )
    model = Pi0Config(pi05=True, action_dim=32, action_horizon=spec.action_horizon,
                      **({"paligemma_variant": "gemma_2b_lora", "action_expert_variant": "gemma_300m_lora"}
                         if spec.lora else {}))
    kwargs = {"freeze_filter": model.get_freeze_filter(), "ema_decay": None} if spec.lora else {}
    run = Path(spec.run_dir).resolve()
    return oc.TrainConfig(
        name=spec.name, exp_name="training", model=model,
        data=AirportDataConfig(repo_id=spec.dataset_repo_id,
                              base_config=oc.DataConfig(prompt_from_task=True)),
        weight_loader=weight_loaders.CheckpointWeightLoader(str(Path(spec.base_params).resolve())),
        lr_schedule=optimizer.CosineDecaySchedule(**resolved_lr_schedule(spec)),
        assets_base_dir=str(run / "assets"), checkpoint_base_dir=str(run / "checkpoints"),
        batch_size=spec.batch_size, num_train_steps=spec.num_train_steps, save_interval=spec.save_interval,
        num_workers=spec.num_workers, fsdp_devices=spec.fsdp_devices, seed=spec.seed,
        wandb_enabled=False, overwrite=False, resume=False,
        policy_metadata={"robot": "r1pro", "action_semantics": "absolute_mobile19", "fps": 20,
                         "prompt_mode": spec.prompt_mode,
                         "source": "simulation/program_generated", "method": "simulation_expert_dagger"
                         if spec.aggregation_manifest else ("bc_lora" if spec.lora else "bc")},
        **kwargs,
    )


def register_openpi_config(spec):
    config = build_openpi_config(spec)
    from openpi.training import config as oc
    # In-process extension registry; never rewrite the official checkout.
    if config.name in oc._CONFIGS_DICT:
        raise ValueError("Openpi configuration name already registered")
    oc._CONFIGS_DICT[config.name] = config
    return config


def _load_script(root, filename):
    path = (Path(root) / "scripts" / filename).resolve()
    if Path(filename).name != filename or path.suffix != ".py" or not path.is_file():
        raise ValueError("Official script must be an existing .py basename")
    # torch DataLoader spawn pickles RemoveStrings by its defining module.
    # A spec_from_file_location alias exists only in the parent process. Use
    # the script's real importable stem and inherit its directory in sys.path.
    directory = str(path.parent)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    importlib.invalidate_caches()
    module = importlib.import_module(path.stem)
    if Path(module.__file__).resolve() != path:
        raise ValueError("Script import resolved outside the pinned official source: " + path.stem)
    return module


def launch_training(spec: TrainingSpec, *, normalize_only=False):
    """Synchronous actual training, with truthful status on dependency/GPU failure."""
    import dataclasses
    spec.validate()
    run = Path(spec.run_dir).resolve()
    run.mkdir(parents=True, exist_ok=False)
    status_path = run / "training_status.json"
    status = {"status": "initializing", "spec": dataclasses.asdict(spec),
              "prompt_mode": spec.prompt_mode,
              "method": "simulation_expert_dagger" if spec.aggregation_manifest else "bc",
              "model": "pi05", "action_semantics": "absolute_mobile19", "fps": 20,
              "training_steps": 0, "checkpoint_verified": False, "source": "simulation/program_generated"}
    status["lr_schedule"] = resolved_lr_schedule(spec)
    cache_dir = project_jax_cache_dir(spec)
    status["jax_compilation_cache_dir"] = str(cache_dir)
    status["sampling_policy"] = ("weighted_random_skill_balanced_bc_preserve_dagger_mass"
                                 if spec.bc_skill_balance else "default_official_shuffle")
    def persist():
        status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    persist()
    loader_restore = None
    sampling_restore = None
    try:
        # HF_LEROBOT_HOME uses repo_id hierarchy; an actual train-only dataset is
        # already materialized there by the data exporter. Refuse mismatched roots.
        expected = Path(os.environ.get("HF_LEROBOT_HOME", "")).resolve() / spec.dataset_repo_id
        if expected.resolve() != Path(spec.dataset_root).resolve():
            raise ValueError("Set HF_LEROBOT_HOME so repo_id resolves to dataset_root")
        config = register_openpi_config(spec)
        stats_path = config.assets_dirs / spec.dataset_repo_id / "norm_stats.json"
        if spec.bc_warmstart_parent_status:
            audit = verified_bc_warmstart(spec)
            status["bc_warmstart"] = audit
            status["normalization_policy"] = audit["normalization_policy"]
            status["parent_checkpoint"] = audit["parent_checkpoint"]
            status["status"] = "verifying_bc_warmstart"; persist()
            copy_verified_warmstart_stats(audit, stats_path)
        elif spec.aggregation_manifest:
            import shutil
            from .dagger_dataset import install_mixed_loader
            parent = json.loads(Path(spec.parent_trained_status).read_text(encoding="utf-8"))
            stats_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(parent["normalization"], stats_path)
            status["normalization_policy"] = "preserve_parent_bc_train_stats"
            status["parent_checkpoint"] = parent["checkpoint"]
            status["status"] = "verifying_dagger_mixture"; persist()
            loader_restore = install_mixed_loader(spec)
        else:
            status["status"] = "normalizing_train_split"; persist()
            _load_script(spec.openpi_root, "compute_norm_stats.py").main(config.name)
        if not stats_path.is_file():
            raise RuntimeError("Official train-only normalization did not produce stats")
        status["normalization"] = str(stats_path)
        if normalize_only:
            status["status"] = "normalized_only"; persist(); return status
        status["status"] = "training"; persist()
        try:
            import jax
            cache_dir.mkdir(parents=True, exist_ok=True)
            if spec.bc_skill_balance:
                from .skill_sampling import install_skill_sampler
                sampling_restore, sampling_audit = install_skill_sampler(spec)
                status["sampling_audit"] = sampling_audit
                persist()
            with redirect_jax_compilation_cache(jax.config, cache_dir):
                train_script = _load_script(spec.openpi_root, "train.py")
                if jax.device_count() > 1:
                    from .training_preview import host_first_training_preview
                    with host_first_training_preview(train_script, Path(spec.openpi_root) / "scripts/train.py", bridge_inputs=True, on_verification=persist) as preview_audit:
                        status["training_preview_adapter"] = preview_audit
                        persist()
                        train_script.main(config)
                else:
                    train_script.main(config)
        finally:
            if sampling_restore is not None:
                sampling_restore()
                sampling_restore = None
            if loader_restore is not None:
                original, data_loader = loader_restore
                data_loader.create_torch_dataset = original
                loader_restore = None
        candidates = [p for p in config.checkpoint_dir.glob("*/params")
                      if p.is_dir() and any(q.is_file() for q in p.rglob("*"))]
        if not candidates:
            raise RuntimeError("Training returned without a saved parameter checkpoint")
        latest = max(candidates, key=lambda p: int(p.parent.name))
        status.update(status="checkpoint_saved", checkpoint=str(latest.parent), checkpoint_verified=True,
                      training_steps=spec.num_train_steps, checkpoint_step=int(latest.parent.name))
        persist(); return status
    except BaseException as exc:
        status.update(status="failed", error=repr(exc)); persist(); raise
    finally:
        if sampling_restore is not None:
            sampling_restore()
        if loader_restore is not None:
            original, data_loader = loader_restore
            data_loader.create_torch_dataset = original
