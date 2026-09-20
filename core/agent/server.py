import asyncio
import json
import os
from pathlib import Path
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from .contracts import envelope, validate
from .engine import Engine
from .memory import WorkingMemory, LongTermMemory
from .providers import GeminiModel, MockModel
from .transport import MAX_MESSAGE, RemotePlatform, authenticate

class CoreServer:
    def __init__(self,ui_token,platform_token,model_factory=MockModel,data_dir='.agent-data'):
        if len(ui_token)<32 or len(platform_token)<32 or ui_token==platform_token:
            raise ValueError('Use distinct random UI and platform tokens of at least 32 characters')
        self.ui_token,self.platform_token=ui_token,platform_token
        self.platform=RemotePlatform()
        self.memory=LongTermMemory(Path(data_dir)/'memory.sqlite3')
        self.engine=Engine(self.platform,WorkingMemory(float(os.getenv('AGENT_WORKING_TTL','1800'))),self.memory,model_factory)
        self.ui=None
        self.active=None
        self.task_id=None
        self.seen=set()
    async def handle(self,ws):
        path=ws.request.path
        if path=='/v1/platform':
            if await authenticate(ws,'platform',self.platform_token):
                try: await self.platform.attach(ws)
                except Exception: await ws.close(1008,'Invalid platform message')
            return
        if not await authenticate(ws,'ui',self.ui_token): return
        if self.ui is not None:
            await ws.close(1008,'UI already connected'); return
        self.ui=ws
        async def send_error(code,message,request_id=None):
            await ws.send(json.dumps(envelope('error',{'code':code,'message':message,'retryable':False},request_id=request_id)))
        try:
            async for raw in ws:
                try:
                    if not isinstance(raw,str): raise ValueError('Text frames required')
                    msg=validate(json.loads(raw))
                except Exception:
                    await send_error('invalid_message','Message does not match shared protocol v1.0.'); continue
                kind,task_id,payload=msg['type'],msg.get('task_id'),msg['payload']
                if kind=='user_request':
                    if self.active and not self.active.done():
                        await send_error('busy','A task is already running.',msg['request_id']); continue
                    if task_id in self.seen:
                        await send_error('duplicate_task','Use a fresh task ID.',msg['request_id']); continue
                    if len(self.seen)>=10000:
                        await send_error('session_limit','Restart Core to start a new session.'); continue
                    self.seen.add(task_id)
                    self.task_id=task_id
                    request_id=msg['request_id']
                    async def emit(status,*,_tid=task_id,_rid=request_id,**fields):
                        if ws.state.name=='OPEN':
                            await ws.send(json.dumps(envelope('agent_event',{'status':status,**fields},_tid,_rid)))
                    # Kept so a mid-task clarification can speak on this task.
                    self.emit_active=emit
                    self.active=asyncio.create_task(self.engine.run(task_id,payload,emit))
                elif kind in ('cancel','confirmation_response','user_reply'):
                    if task_id!=self.task_id or not self.active or self.active.done():
                        await send_error('inactive_task','No matching active task.',msg['request_id']); continue
                    if kind=='cancel':
                        self.active.cancel()
                    else:
                        # A spoken answer arrives as audio; Core transcribes it
                        # before the normal, unchanged handling runs.
                        try:
                            payload=await self.engine.resolve_spoken(payload)
                        except Exception:
                            await send_error('voice_unavailable','Could not transcribe the spoken answer.',msg['request_id']); continue
                        if payload is None:
                            # They asked a question instead of answering one.
                            # Explain and ask again rather than reading it as a no.
                            await self.engine.clarify(task_id,self.emit_active)
                            continue
                        accepted=(self.engine.confirmations.respond(task_id,payload) if kind=='confirmation_response' else self.engine.reply(task_id,payload))
                        if not accepted: await send_error('invalid_response','Response is stale or does not match the pending request.',msg['request_id'])
                else: await send_error('unexpected_message','UI cannot send this message type.',msg['request_id'])
        except ConnectionClosed: pass
        finally:
            if self.active and not self.active.done():
                self.active.cancel()
                await asyncio.gather(self.active,return_exceptions=True)
            self.ui=None
    async def start(self,port=8765):
        self.listener=await serve(self.handle,'127.0.0.1',port,max_size=MAX_MESSAGE,max_queue=8,compression=None,ping_timeout=20)
        return self.listener.sockets[0].getsockname()[1]
    async def close(self):
        if self.active and not self.active.done(): self.active.cancel()
        self.listener.close()
        await self.listener.wait_closed()
        self.memory.close()
