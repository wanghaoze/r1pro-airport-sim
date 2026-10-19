"""Lossless metadata routing; publication formatting never drops verified source fields."""
from copy import deepcopy
import math

def verify_native_replay_errors(manifest, tolerance):
    if type(tolerance) not in (int,float) or not math.isfinite(tolerance) or tolerance<=0:
        raise ValueError('invalid_source_replay_tolerance')
    limits={'qpos':tolerance,'qvel':10*tolerance,'time':1e-8}
    for section in ('prefix_errors','terminal_errors'):
        errors=manifest.get(section,{})
        if set(errors)!=set(limits):raise ValueError('missing_replay_error_channels')
        for key,limit in limits.items():
            value=errors[key]
            if type(value) not in (int,float) or not math.isfinite(value) or value<0 or value>limit:
                raise ValueError('source_replay_error_limit:'+section+':'+key)
    return True

def merge_verified_reference_fields(incoming, retained):
    prior={(row['trace_sha256'],row['camera']):row for row in retained}
    if len(prior)!=len(retained):raise ValueError('duplicate_retained_native_reference')
    result=[];seen=set()
    for row in incoming:
        key=(row['trace_sha256'],row['camera'])
        if key in seen:raise ValueError('duplicate_incoming_native_reference')
        seen.add(key);item=deepcopy(row)
        if key in prior:
            old=prior[key]
            for name in ('path','sha256','source_manifest','source_manifest_sha256','frames'):
                if name in row and name in old and row[name]!=old[name]:
                    raise ValueError('retained_native_reference_identity_changed:'+name)
            item.update(deepcopy(old))
        result.append(item)
    if set(prior)-seen:raise ValueError('closed_native_reference_removed_from_live_inventory')
    return result

def decode_linux_wait_status(raw_exit_code):
    """/proc/PID/stat field52 exposes the real wait status while parent retains Z."""
    if type(raw_exit_code) is not int or raw_exit_code<0:raise ValueError('invalid_linux_exit_status')
    return -(raw_exit_code&127) if raw_exit_code&127 else (raw_exit_code>>8)&255
