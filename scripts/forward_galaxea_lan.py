"""Private wired TCP relay; preserves existing model and robot safety protocol."""
import asyncio,fcntl,json,os,time
from pathlib import Path

RUN=Path(__file__).resolve().parent


async def pipe(reader,writer):
    while data:=await reader.read(262144):
        writer.write(data);await writer.drain()


async def connection(reader,writer,port):
    target=None
    try:
        remote,target=await asyncio.open_connection('100.104.0.108',port)
        tasks=[asyncio.create_task(pipe(reader,target)),asyncio.create_task(pipe(remote,writer))]
        _,pending=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        for task in pending:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
    except Exception as error:print('Relay connection error',repr(error),flush=True)
    finally:
        writer.close()
        if target:target.close()


async def main():
    servers=[]
    for port in [8095,8096]:
        servers.append(await asyncio.start_server(lambda r,w,p=port:connection(r,w,p),'10.42.0.191',port))
    (RUN/'status.json').write_text(json.dumps(dict(stage='ready',pid=os.getpid(),unix=time.time(),host='10.42.0.191',ports=[8095,8096],target='100.104.0.108',changes_model_or_filter=False),indent=2))
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__=='__main__':
    lock=(RUN/'relay.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    asyncio.run(main())
