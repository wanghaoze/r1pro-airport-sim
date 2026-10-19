"""Discover the legacy three-tray branch and stage new loaded-handover assets."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.real2sim.three_tray_migration import discover, build_scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--payload-template', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    inventory = discover(args.legacy_root)
    (args.output / 'legacy_inventory.json').write_text(json.dumps(inventory, indent=2))
    (args.output / 'parent_split_registry.json').write_text(json.dumps(inventory['parent_split_registry'], indent=2))
    if args.payload_template:
        for split in ('train', 'val', 'test'):
            row = next(row for row in inventory['sources'] if row['split'] == split)
            build_scene(row, args.payload_template, args.output / 'scenes' / split / row['parent_scene_id'])
    status = dict(stage='assets_staged_pending_native_validation', training_status='waiting_for_data',
        legacy_sources=len(inventory['sources']), qualified_new_native_sources=0,
        new_native_action_segments=0, model_training_started=False,
        legacy_data_relabelled=False, loaded_handover_controller_ported=False,
        native_whole_task_observer_ported=False)
    (args.output / 'pipeline_status.json').write_text(json.dumps(status, indent=2))
    print(json.dumps(status))


if __name__ == '__main__':
    main()
