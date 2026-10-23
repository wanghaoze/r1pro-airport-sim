"""Separate host-side inference measurements; never imply GPU kernel timing."""
import json
import math
from pathlib import Path
import numpy as np

STAGES = ('model_adapter', 'http_roundtrip')


def stage_of(row):
    if 'stage' in row:
        return row['stage'] if row['stage'] in STAGES else 'unknown'
    # Legacy records from the two original writers have distinct evidence keys.
    if 'camera_sha256' in row and 'actions_sha256' in row and 'requestId' not in row:
        return 'model_adapter'
    if 'requestId' in row and 'camera_sha256' not in row:
        return 'http_roundtrip'
    return 'unknown'


def read_events(run):
    rows=[];malformed=0
    for name in ('inference_events.jsonl', 'inference_model_events.jsonl'):
        path=Path(run)/name
        if not path.exists():continue
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                row=json.loads(line)
                if not isinstance(row,dict):raise ValueError('non-object event')
                rows.append(row)
            except (ValueError,TypeError):malformed+=1
    return rows,malformed


def valid_latency(row):
    value=row.get('latency_seconds')
    return type(value) in (int,float) and math.isfinite(value) and value>=0


def successful_events(rows,stage):
    return [r for r in rows if stage_of(r)==stage and not r.get('error') and valid_latency(r)]


def summarize(rows,malformed=0):
    groups={}
    for stage in STAGES:
        selected=[r for r in rows if stage_of(r)==stage]
        values=[r['latency_seconds'] for r in successful_events(selected,stage)]
        groups[stage]=dict(records=len(selected),success_count=len(values),
            error_count=sum(bool(r.get('error')) for r in selected),
            invalid_latency_count=sum(not valid_latency(r) for r in selected),
            mean_seconds=float(np.mean(values)) if values else None,
            p50_seconds=float(np.quantile(values,.5)) if values else None,
            p95_seconds=float(np.quantile(values,.95)) if values else None)
    return dict(schema='inference_timing_summary/1',stages=groups,
        unknown_stage_count=sum(stage_of(r)=='unknown' for r in rows),malformed_line_count=malformed,
        gpu_kernel_timing=False,stages_additive=False,
        scope='available_log_snapshot_not_unique_request_count',
        semantics={'model_adapter':'Host elapsed including model transforms, execution and materialized output; excludes HTTP.',
                   'http_roundtrip':'Serialization, local HTTP queue/service and response decode; overlaps model_adapter; excludes earlier ROS/file waits.'})


def video_timing(run):
    rows,malformed=read_events(run)
    # One layer only: a model record and its HTTP record are not two replies.
    stage='model_adapter' if successful_events(rows,'model_adapter') else 'http_roundtrip'
    events=successful_events(rows,stage)
    events=[r for r in events if type(r.get('unix')) in (int,float) and math.isfinite(r['unix'])]
    return events,stage,summarize(rows,malformed)
