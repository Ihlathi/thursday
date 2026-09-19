"""Loopback-only WebSockets with separate UI/bridge credentials and strict envelopes."""
import asyncio
import hmac
import json
from websockets.asyncio.client import connect
from .contracts import envelope, validate, validate_def

MAX_MESSAGE=3_000_000

async def receive(ws):
    raw=await ws.recv()
    if not isinstance(raw,str): raise ValueError('JSON text frames required')
    return validate(json.loads(raw))

async def authenticate(ws, role, token):
    if ws.request.path != '/v1/'+role or ws.request.headers.get('Origin') not in (None,'tauri://localhost','http://tauri.localhost'):
        await ws.close(1008,'Path or origin rejected')
        return False
    try:
        message=await asyncio.wait_for(receive(ws),5)
        p=message['payload']
        valid=message['type']=='hello' and p['role']==role and hmac.compare_digest(p['token'],token)
    except (ValueError,KeyError,TimeoutError): valid=False
    except Exception: valid=False
    if not valid:
        await ws.close(1008,'Authentication required')
        return False
    await ws.send(json.dumps(envelope('hello_ack',{'role':role},request_id=message['request_id'])))
    return True

async def client_connect(url,role,token):
    ws=await connect(url,max_size=MAX_MESSAGE,compression=None,open_timeout=5)
    try:
        await ws.send(json.dumps(envelope('hello',{'role':role,'token':token})))
        ack=await asyncio.wait_for(receive(ws),5)
        if ack['type']!='hello_ack' or ack['payload']['role']!=role: raise ValueError('Invalid handshake')
        return ws
    except BaseException:
        await ws.close()
        raise

class RemotePlatform:
    def __init__(self):
        self.ws=None
        self.pending={}
    async def attach(self,ws):
        if self.ws is not None:
            await ws.close(1008,'Bridge already connected'); return
        self.ws=ws
        try:
            async for raw in ws:
                msg=validate(json.loads(raw))
                if msg['type']!='tool_result': raise ValueError('Unexpected bridge message')
                key=(msg['task_id'],msg['payload']['call_id'],msg['request_id'])
                future=self.pending.get(key)
                if future and not future.done(): future.set_result(msg['payload'])
        finally:
            self.ws=None
            for f in self.pending.values():
                if not f.done(): f.set_exception(ConnectionError('Platform disconnected'))
    async def execute(self,task_id,tool):
        if self.ws is None: raise ConnectionError('No platform bridge connected')
        message=envelope('tool_call',tool,task_id)
        key=(task_id,tool['call_id'],message['request_id'])
        f=asyncio.get_running_loop().create_future()
        self.pending[key]=f
        try:
            await self.ws.send(json.dumps(message))
            return await asyncio.wait_for(f,15)
        finally: self.pending.pop(key,None)
    async def cancel(self,task_id):
        if self.ws is not None:
            await self.ws.send(json.dumps(envelope('cancel',{'reason':'Task cancelled'},task_id)))
