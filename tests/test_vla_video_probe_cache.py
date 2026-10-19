import json
import pytest
from r1pro_teleop.vla.video_probe_cache import VerifiedVideoProbeCache
from r1pro_teleop.vla.data import digest


def source(tmp_path,*,verified=True):
    video=tmp_path/'native.mp4';video.write_bytes(b'immutable native bytes')
    metadata=dict(width=1920,height=1536,fps=20.,frames=123)
    record=dict(path=str(video),verified=verified,sha256=digest(video),measured=metadata,start_frame=40,end_frame=78)
    manifest=tmp_path/'source.jsonl';manifest.write_text(json.dumps(dict(schema='airport_vla_segments/1',segment_id='original',videos={'head_left':record})))
    return video,manifest,metadata


def header(path):return dict(width=1920,height=1536,fps=20.,codec='h264',pixel_format='yuv420p')


def test_verified_identical_bytes_reuse_actual_decoded_metadata_with_full_audit(tmp_path):
    video,manifest,metadata=source(tmp_path)
    def forbid_decode(path):raise AssertionError('must not decode verified identical content again')
    cache=VerifiedVideoProbeCache(manifest,digest(manifest),header_probe=header,decoded_probe=forbid_decode)
    assert cache(video)==metadata
    report=cache.audit_report();row=report['records'][0]
    assert report['reused_count']==1 and report['decoded_count']==0
    assert row['current_file_sha256']==digest(video) and row['original_audit_document_sha256']==digest(manifest)
    assert len(row['original_record_sha256'])==64 and row['original_record']['verified']is True
    assert row['header']['codec']=='h264' and row['measured']['frames']==123


def test_unverified_source_still_decodes_and_never_claims_cached_audit(tmp_path):
    video,manifest,metadata=source(tmp_path,verified=False);calls=[]
    cache=VerifiedVideoProbeCache(manifest,digest(manifest),header_probe=lambda _:pytest.fail('unknown file must decode'),decoded_probe=lambda p:calls.append(p)or metadata)
    assert cache(video)==metadata and calls==[str(video)]
    row=cache.audit_report()['records'][0]
    assert row['decoded_frame_probe_executed']and 'original_audit_document_sha256'not in row


def test_changed_manifest_is_rejected(tmp_path):
    _,manifest,_=source(tmp_path);expected=digest(manifest);manifest.write_text('{}')
    with pytest.raises(ValueError,match='source_manifest_hash_changed'):VerifiedVideoProbeCache(manifest,expected)


def test_changed_video_cannot_reuse_prior_probe(tmp_path):
    video,manifest,_=source(tmp_path);cache=VerifiedVideoProbeCache(manifest,digest(manifest),header_probe=header)
    video.write_bytes(b'reencoded different bytes')
    with pytest.raises(ValueError,match='video_hash_changed'):cache(video)
    assert not cache.audit_report()['records']


def test_file_changing_during_header_probe_is_rejected(tmp_path):
    video,manifest,_=source(tmp_path)
    def mutation(path):video.write_bytes(b'changed during probe');return header(path)
    cache=VerifiedVideoProbeCache(manifest,digest(manifest),header_probe=mutation)
    with pytest.raises(ValueError,match='file_changed_during_probe'):cache(video)


def test_header_disagrees_with_verified_shape_is_rejected(tmp_path):
    video,manifest,_=source(tmp_path)
    cache=VerifiedVideoProbeCache(manifest,digest(manifest),header_probe=lambda p:dict(header(p),width=320))
    with pytest.raises(ValueError,match='header_mismatch'):cache(video)


def test_conflicting_verified_metadata_for_same_bytes_is_rejected(tmp_path):
    _,manifest,_=source(tmp_path);row=json.loads(manifest.read_text());other=json.loads(json.dumps(row));other['videos']['head_left']['measured']['frames']+=1
    manifest.write_text(json.dumps(row)+'\n'+json.dumps(other))
    with pytest.raises(ValueError,match='conflicting_previous_metadata'):VerifiedVideoProbeCache(manifest,digest(manifest))
