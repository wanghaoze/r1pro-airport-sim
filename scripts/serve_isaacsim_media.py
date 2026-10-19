"""Read-only, single-instance byte-range media service on the existing tailnet."""
import argparse
import fcntl
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import time


class RangeHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Accept-Ranges','bytes');super().end_headers()

    def send_head(self):
        self.byte_range=None;request=self.headers.get('Range')
        path=Path(self.translate_path(self.path))
        if not request or not path.is_file():return super().send_head()
        size=path.stat().st_size;match=re.fullmatch(r'bytes=(\d*)-(\d*)',request.strip())
        start=end=None
        if match and size:
            lo,hi=match.groups()
            if lo:start=int(lo);end=min(int(hi),size-1) if hi else size-1
            elif hi and int(hi)>0:start=max(0,size-int(hi));end=size-1
        if start is None or end is None or not 0<=start<=end<size:
            self.send_response(416);self.send_header('Content-Range',f'bytes */{size}')
            self.send_header('Content-Length','0');self.end_headers();return None
        stream=path.open('rb');self.byte_range=(start,end)
        self.send_response(206);self.send_header('Content-Type',self.guess_type(str(path)))
        self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length',str(end-start+1));self.end_headers();return stream

    def copyfile(self,source,output):
        try:
            if self.byte_range is None:return super().copyfile(source,output)
            start,end=self.byte_range;source.seek(start);remaining=end-start+1
            while remaining:
                block=source.read(min(64*1024,remaining))
                if not block:break
                output.write(block);remaining-=len(block)
        except (BrokenPipeError,ConnectionResetError):pass  # Normal cancelled seeks.


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    p.add_argument('--state-dir',type=Path,required=True);p.add_argument('--bind',default='100.104.0.108')
    p.add_argument('--port',type=int,default=8776);a=p.parse_args()
    root=a.root.resolve(strict=True);state=a.state_dir.resolve();state.mkdir(parents=True,exist_ok=True)
    lock=(state/'server.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    server=ThreadingHTTPServer((a.bind,a.port),functools.partial(RangeHandler,directory=str(root)))
    identity=dict(pid=os.getpid(),start_ticks=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19],
        argv=Path('/proc/self/cmdline').read_text().split('\0')[:-1],cwd=str(Path.cwd()))
    result=dict(stage='serving_read_only_media',identity=identity,bind=a.bind,port=a.port,root=str(root),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),unix=time.time())
    tmp=state/'status.tmp';tmp.write_text(json.dumps(result,indent=2));tmp.replace(state/'status.json')
    print(json.dumps(result),flush=True);server.serve_forever()


if __name__=='__main__':main()
