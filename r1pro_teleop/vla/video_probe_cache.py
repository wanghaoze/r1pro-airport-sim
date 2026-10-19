"""Candidate hash-bound reuse of prior decoded video probes; not installed by default."""
from __future__ import annotations
import hashlib,json,math,subprocess
from pathlib import Path
from .data import digest, probe_video


def probe_header(path):
    """Cheap codec/shape/FPS check; never substitute tags for decoded counts."""
    data=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-show_entries','stream=codec_name,pix_fmt,width,height,avg_frame_rate','-of','json',str(path)],text=True))['streams'][0]
    numerator,denominator=map(int,data['avg_frame_rate'].split('/'))
    return dict(codec=data['codec_name'],pixel_format=data['pix_fmt'],width=int(data['width']),
                height=int(data['height']),fps=numerator/denominator)


def _measured(value):
    if (not isinstance(value,dict) or any(type(value.get(k))is not int or value[k]<=0 for k in ('width','height','frames'))
            or isinstance(value.get('fps'),bool) or not isinstance(value.get('fps'),(int,float))
            or not math.isfinite(value['fps']) or value['fps']<=0):
        raise ValueError('verified_probe_invalid_decoded_metadata')
    return {key:value[key] for key in ('width','height','fps','frames')}


class VerifiedVideoProbeCache:
    """Explicit opt-in callable compatible with prepare_manifest(video_probe=...).

    expected_sha256 must come from a trusted, completed source manifest binding.
    Merely naming a file does not establish a verified audit. Each reused video
    retains the source document SHA, complete original JSON record identity,
    current file SHA, and fresh header probe. Unverified/missing entries use a
    full decoded frame probe. Existing sources changing bytes are rejected.
    """
    def __init__(self,source_manifest,expected_sha256,*,header_probe=probe_header,decoded_probe=probe_video):
        self.source=Path(source_manifest).resolve();raw=self.source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected_sha256:
            raise ValueError('verified_probe_source_manifest_hash_changed')
        self.source_sha256=expected_sha256;self.header_probe=header_probe;self.decoded_probe=decoded_probe
        self.entries={};self.audit=[]
        for line in raw.decode('utf-8').splitlines():
            row=json.loads(line)
            if row.get('schema')!='airport_vla_segments/1':raise ValueError('verified_probe_source_schema_unknown')
            for camera,record in row.get('videos',{}).items():
                if record.get('verified')is not True:continue
                sha=record.get('sha256')
                if not isinstance(sha,str)or len(sha)!=64 or any(c not in '0123456789abcdef'for c in sha):
                    raise ValueError('verified_probe_video_sha_missing')
                measured=_measured(record.get('measured'));key=str(Path(record['path']).resolve())
                original=json.dumps(record,sort_keys=True,separators=(',',':'),allow_nan=False)
                entry=dict(video_sha256=sha,measured=measured,original_record=record,
                    original_record_sha256=hashlib.sha256(original.encode()).hexdigest(),camera=camera,
                    original_segment_id=row['segment_id'])
                if key in self.entries and (self.entries[key]['video_sha256']!=sha or self.entries[key]['measured']!=measured):
                    raise ValueError('verified_probe_conflicting_previous_metadata')
                self.entries.setdefault(key,entry)

    def __call__(self,path):
        key=str(Path(path).resolve());before=digest(key);entry=self.entries.get(key)
        if entry is None:
            measured=_measured(self.decoded_probe(key));method='full_decoded_ffprobe';header=None
        else:
            if before!=entry['video_sha256']:raise ValueError('verified_probe_video_hash_changed')
            header=self.header_probe(key)
            if (not header.get('codec')or not header.get('pixel_format')
                    or header.get('width')!=entry['measured']['width'] or header.get('height')!=entry['measured']['height']
                    or header.get('fps')!=entry['measured']['fps']):
                raise ValueError('verified_probe_current_header_mismatch')
            measured=entry['measured'].copy();method='hash_bound_previous_decoded_probe'
        after=digest(key)
        if before!=after:raise ValueError('verified_probe_file_changed_during_probe')
        audit=dict(path=key,method=method,decoded_frame_probe_executed=entry is None,
            current_file_sha256=after,measured=measured,header=header)
        if entry is not None:
            audit.update(original_audit_document=str(self.source),original_audit_document_sha256=self.source_sha256,
                original_record_sha256=entry['original_record_sha256'],original_record=entry['original_record'],
                original_segment_id=entry['original_segment_id'],camera=entry['camera'])
        self.audit.append(audit)
        return measured.copy()

    def audit_report(self):
        report=dict(schema='airport_verified_video_probe_cache/1',source_manifest=str(self.source),
            source_manifest_sha256=self.source_sha256,records=self.audit.copy(),
            reused_count=sum(not row['decoded_frame_probe_executed'] for row in self.audit),
            decoded_count=sum(row['decoded_frame_probe_executed'] for row in self.audit),
            native_video_modified=False,default_pipeline_installed=False)
        return json.loads(json.dumps(report,allow_nan=False))
