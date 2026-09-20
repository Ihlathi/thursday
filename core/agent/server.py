import asyncio
import json
import os
from pathlib import Path
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from .contracts import envelope, validate
from .engine import Engine
from .memory import WorkingMemory, LongTermMemory
from .providers import GeminiModel, MockModel, configure
from .settings import Settings
from .transport import MAX_MESSAGE, RemotePlatform, authenticate

class CoreServer:
    def __init__(self,ui_token,platform_token,model_factory=MockModel,data_dir='.agent-data',mode=None):
        if len(ui_token)<32 or len(platform_token)<32 or ui_token==platform_token:
            raise ValueError('Use distinct random UI and platform tokens of at least 32 characters')
        self.ui_token,self.platform_token=ui_token,platform_token
        self.platform=RemotePlatform()
        self.settings=Settings(Path(data_dir)/'settings.json',mode or 'gemini')
        configure(self.settings)
        self.memory=LongTermMemory(Path(data_dir)/'memory.sqlite3')
        # With no explicit factory the provider follows Settings, so a key added
        # from the tray takes effect on the next task without a restart.
        factory=model_factory if model_factory is not None else self.provider
        self.engine=Engine(self.platform,WorkingMemory(float(os.getenv('AGENT_WORKING_TTL','1800'))),self.memory,factory)
        self.ui=None
        self.active=None
        self.task_id=None
        self.seen=set()
    def provider(self):
        return GeminiModel() if self.settings.model_mode=='gemini' else MockModel()
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
                    self.active=asyncio.create_task(self.engine.run(task_id,payload,emit))
                elif kind in ('settings_get','settings_update'):
                    # Credentials arrive over the authenticated loopback socket and
                    # stay here; only presence flags are ever sent back.
                    saved=False
                    if kind=='settings_update':
                        try:
                            if payload.get('clear_all'): self.settings.clear()
                            else: self.settings.update({k:v for k,v in payload.items() if k!='clear_all'})
                            saved=True
                        except (ValueError,OSError) as exc:
                            await send_error('settings_rejected',str(exc),msg['request_id']); continue
                    state=self.settings.state()|{'saved':saved}
                    await ws.send(json.dumps(envelope('settings_state',state,request_id=msg['request_id'])))
                elif kind in ('cancel','confirmation_response','user_reply'):
                    if task_id!=self.task_id or not self.active or self.active.done():
                        await send_error('inactive_task','No matching active task.',msg['request_id']); continue
                    if kind=='cancel':
                        self.active.cancel()
                    else:
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
