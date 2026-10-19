"""Exclusive new skill-derived dataset, quality/coverage audit and train preflight.

This command does not start training. Run in a non-base Conda environment.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import sys
import traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.data import digest
from r1pro_teleop.vla.data_skill_merge import materialize_skill_dataset, audit_constituent_qualifications
from r1pro_teleop.vla.data_skill_coverage import audit_source_coverage


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source-dataset',required=True)
    p.add_argument('--parent-dataset',required=True)
    p.add_argument('--destination',required=True)
    p.add_argument('--repo-id',required=True)
    p.add_argument('--output-dir',required=True)
    p.add_argument('--training-spec',required=True)
    p.add_argument('--expected-scenes',type=int,default=32)
    p.add_argument('--expected-lifts',type=int,default=113)
    args=p.parse_args();output=Path(args.output_dir).resolve()
    output.mkdir(parents=True,exist_ok=False)
    manifest=output/'segments_native32_v4_skillmerged.jsonl'
    audit_path=output/'source_coverage_superset_audit.json'
    status=dict(stage='initializing',pid=os.getpid(),training_ready=False,training_started=False,
                source_dataset=str(Path(args.source_dataset).resolve()),dataset=str(Path(args.destination).resolve()),
                source_manifest=str(manifest),source_coverage_audit=str(audit_path),source='simulation/program_generated',
                max_camera_workers=3,ffmpeg_decode_threads_per_worker=1,gpu_used=False)
    def persist(stage,**values):
        status.update(values,stage=stage,updated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        temporary=output/'status.tmp';temporary.write_text(json.dumps(status,indent=2,allow_nan=False))
        temporary.replace(output/'status.json');print(json.dumps(status),flush=True)
    try:
        persist('materializing_skill_contiguous')
        result=materialize_skill_dataset(args.source_dataset,args.destination,args.repo_id,manifest)
        source_training=json.loads((Path(args.source_dataset)/'airport_training_manifest.json').read_text())
        quality=audit_constituent_qualifications(manifest,source_training['source_manifest'])
        if (quality['scene_count']!=args.expected_scenes or quality['initializations']!=args.expected_scenes
                or not quality['all_scenes_initialize'] or not quality['all_source_lifts_qualified']
                or quality['qualified_lift_operations']!=args.expected_lifts):
            raise ValueError('skill_constituent_quality_count_or_qualification_failed')
        (output/'quality_audit.json').write_text(json.dumps(quality,indent=2,allow_nan=False))
        persist('auditing_source_coverage',**result)
        audit=audit_source_coverage(args.parent_dataset,args.destination)
        audit_temporary=output/'source_coverage_superset_audit.tmp'
        with audit_temporary.open('x',encoding='utf-8') as stream:
            stream.write(json.dumps(audit,indent=2,allow_nan=False))
        audit_temporary.replace(audit_path)
        persist('training_spec_preflight',coverage_audit_sha256=digest(audit_path))
        from r1pro_teleop.vla.training import TrainingSpec
        spec=TrainingSpec(**json.loads(Path(args.training_spec).read_text(encoding='utf-8')))
        if (Path(spec.dataset_root).resolve()!=Path(args.destination).resolve()
                or spec.dataset_repo_id!=args.repo_id
                or Path(spec.bc_warmstart_source_audit).resolve()!=audit_path):
            raise ValueError('skill_preflight_dataset_or_coverage_path_mismatch')
        spec.validate()
        persist('complete',training_ready=True,official_loader_verified=True,
                source_frame_values_verified=True,source_scene_xml_verified=True,
                constituent_phase_coverage_verified=True,training_spec_preflight_verified=True,
                training_spec_sha256=digest(args.training_spec),source_manifest_sha256=digest(manifest),
                training_manifest_sha256=digest(Path(args.destination)/'airport_training_manifest.json'),
                initializations=quality['initializations'],qualified_lifts=quality['qualified_lift_operations'])
    except BaseException as exc:
        persist('failed',error=repr(exc),traceback=traceback.format_exc(),training_ready=False)
        raise


if __name__=='__main__':main()
