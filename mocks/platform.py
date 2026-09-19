"""Run without Windows; replace execute() with the real bridge implementation."""
import argparse
import asyncio
import json
import os
from agent.contracts import envelope, validate
from agent.platform import MockPlatform
from agent.transport import client_connect

async def run(url,token,ready=None):
    ws=await client_connect(url,'platform',token)
    platform=MockPlatform()
    pending={}
    if ready: ready.set()
    print('Mock platform connected (no real computer actions).',flush=True)
    async def execute(message):
        result=await platform.execute(message['task_id'],message['payload'])
        await ws.send(json.dumps(envelope('tool_result',result,message['task_id'],message['request_id'])))
    try:
        async for raw in ws:
            msg=validate(json.loads(raw))
            if msg['type']=='tool_call':
                task=asyncio.create_task(execute(msg))
                pending.setdefault(msg['task_id'],set()).add(task)
                def finished(t,tid=msg['task_id']):
                    pending[tid].discard(t)
                    if not t.cancelled(): t.exception()
                task.add_done_callback(finished)
            elif msg['type']=='cancel':
                for task in pending.get(msg['task_id'],set()): task.cancel()
                await platform.cancel(msg['task_id'])
            else: raise ValueError('Unexpected Core message')
    finally:
        tasks=[t for group in pending.values() for t in group]
        for t in tasks: t.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await ws.close()

def main():
    p=argparse.ArgumentParser(); p.add_argument('--url',default='ws://127.0.0.1:8765/v1/platform')
    args=p.parse_args()
    try: asyncio.run(run(args.url,os.environ['AGENT_PLATFORM_TOKEN']))
    except KeyboardInterrupt: pass
if __name__=='__main__': main()
