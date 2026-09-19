import asyncio
import json
import secrets
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from agent.contracts import envelope,uid
from agent.server import CoreServer
from agent.transport import client_connect,receive
from mocks.platform import run

async def test_actual_websocket_roundtrip_auth_and_replay(tmp_path):
    ui,bridge=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
    server=CoreServer(ui,bridge,data_dir=tmp_path)
    port=await server.start(0); url=f'ws://127.0.0.1:{port}'
    worker=None
    try:
        with pytest.raises(ConnectionClosed): await client_connect(url+'/v1/ui','ui',bridge)
        async with connect(url+'/v1/ui',origin='https://evil.example') as bad:
            with pytest.raises(ConnectionClosed): await bad.recv()
        ready=asyncio.Event(); worker=asyncio.create_task(run(url+'/v1/platform',bridge,ready))
        await asyncio.wait_for(ready.wait(),3)
        ws=await client_connect(url+'/v1/ui','ui',ui)
        tid=uid(); req=envelope('user_request',{'text':'stuff I bought recently'},tid)
        await ws.send(json.dumps(req)); events=[]
        while True:
            m=await asyncio.wait_for(receive(ws),3); events.append(m)
            assert m.get('task_id')==tid
            if m['payload']['status'] in ('completed','error'): break
        assert events[-1]['payload']['status']=='completed'
        assert 'Returns & Orders' in events[-1]['payload']['message']
        await ws.send(json.dumps(req))
        assert (await receive(ws))['payload']['code']=='duplicate_task'
        await ws.close()
    finally:
        if worker: worker.cancel(); await asyncio.gather(worker,return_exceptions=True)
        await server.close()

async def test_socket_cancellation_while_waiting_for_confirmation(tmp_path):
    from agent.providers import Turn
    from agent.contracts import call
    class Model:
        label='test'
        async def next(self,*args): return Turn([call('click',x=1,y=2)])
        async def close(self): pass
    ui,bridge=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
    server=CoreServer(ui,bridge,Model,tmp_path); port=await server.start(0)
    ready=asyncio.Event(); worker=asyncio.create_task(run(f'ws://127.0.0.1:{port}/v1/platform',bridge,ready))
    try:
        await asyncio.wait_for(ready.wait(),3)
        ws=await client_connect(f'ws://127.0.0.1:{port}/v1/ui','ui',ui)
        await ws.send(json.dumps(envelope('user_request',{'text':'click'},'canceltest')))
        while (await asyncio.wait_for(receive(ws),3))['payload']['status']!='confirmation_required': pass
        await ws.send(json.dumps(envelope('cancel',{},'canceltest')))
        assert (await asyncio.wait_for(receive(ws),3))['payload']['status']=='cancelled'
        assert not server.engine.confirmations.pending
        await ws.close()
    finally:
        worker.cancel(); await asyncio.gather(worker,return_exceptions=True); await server.close()
