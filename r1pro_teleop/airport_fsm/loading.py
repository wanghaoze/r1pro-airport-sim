"""Load all shards of ONE scene split with official MultiLeRobotDataset.

Symlinks only: no copied/re-encoded videos and no train/validation/test merging.
The caller must build normalization from train.stats, not validation/test stats.
"""
from __future__ import annotations
from pathlib import Path
import json
import re
from .contracts import Fault


def load_split(root, split='train', *, action_horizon=1, image_transforms=None):
    from lerobot.datasets.lerobot_dataset import MultiLeRobotDataset
    if split not in ('train','val','test'):raise ValueError('Unknown split')
    if action_horizon<1:raise ValueError('action_horizon must be positive')
    root=Path(root).resolve()
    catalog=json.loads((root/'datasets/catalog.json').read_text())
    shards=[s for s in catalog['shards'] if s['split']==split]
    if not shards:raise Fault('no_exported_shards_for_split',split)
    links=root/'datasets/multi_root';links.mkdir(exist_ok=True)
    expected=json.loads((root/'splits/scenes.json').read_text())
    seen=set()
    for shard in shards:
        if any(expected.get(sid)!=split for sid in shard['scene_ids']):raise Fault('scene_split_leak')
        repo=shard['repo_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+',repo) or repo in seen:raise Fault('invalid_or_duplicate_shard_repo_id',repo)
        seen.add(repo)
        destination=(root/shard['path']).resolve()
        if not destination.is_relative_to(root/'datasets') or not destination.is_dir():raise Fault('missing_shard_directory')
        link=links/repo;link.parent.mkdir(exist_ok=True)
        if link.is_symlink():
            if link.resolve()!=destination:raise Fault('dataset_symlink_target_changed',str(link))
        elif link.exists():raise Fault('refuse_overwrite_dataset_link',str(link))
        else:link.symlink_to(destination,target_is_directory=True)
    times={'action':[i/20 for i in range(action_horizon)]} if action_horizon>1 else None
    return MultiLeRobotDataset(repo_ids=[s['repo_id'] for s in shards],root=links,
                               delta_timestamps=times,image_transforms=image_transforms,
                               video_backend='pyav',download_videos=False)
