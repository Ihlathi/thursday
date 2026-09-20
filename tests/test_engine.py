import asyncio
import pytest
from agent.contracts import call
from agent.engine import Engine
from agent.memory import WorkingMemory,LongTermMemory
from agent.platform import MockPlatform
from agent.providers import MockModel,Turn

class Script:
    label='test'
    def __init__(self,calls): self.calls=iter(calls); self.contexts=[]; self.feedback=[]
    async def next(self,context,feedback):
        self.contexts.append(context); self.feedback.append(feedback)
        return Turn([next(self.calls)])
    async def close(self): pass

def make(tmp_path,model=None,platform=None):
    return Engine(platform or MockPlatform(),WorkingMemory(),LongTermMemory(tmp_path/'mem.db'),lambda:model or MockModel())

async def test_offline_multistep(tmp_path):
    e=make(tmp_path); events=[]
    async def emit(status,**fields): events.append((status,fields))
    await e.run('task',{'text':'show me the stuff I bought recently'},emit)
    assert events[-1][0]=='completed'
    assert e.world.system['active_window']=='Orders — Mock Browser'
    assert [c['name'] for c in e.platform.executed].count('invoke_ui')==1
    assert any(s=='debug' and f.get('metadata',{}).get('kind')=='context_sent' for s,f in events)
    e.memory.close()

async def test_denial_no_execution(tmp_path):
    model=Script([call('click',x=1,y=2),call('complete_task',message='Denied')]); e=make(tmp_path,model)
    async def emit(status,**f):
        if status=='confirmation_required':
            c=f['confirmation']; e.confirmations.respond('task',{k:c[k] for k in ('confirmation_id','call_id','action_hash')}|{'approved':False})
    await e.run('task',{'text':'click'},emit)
    assert not any(c['name']=='click' for c in e.platform.executed)
    e.memory.close()

async def test_cancel_pending_confirmation(tmp_path):
    e=make(tmp_path,Script([call('click',x=1,y=2)])); ready=asyncio.Event(); statuses=[]
    async def emit(status,**f):
        statuses.append(status)
        if status=='confirmation_required': ready.set()
    running=asyncio.create_task(e.run('task',{'text':'click'},emit))
    await ready.wait(); running.cancel()
    with pytest.raises(asyncio.CancelledError): await running
    assert statuses[-1]=='cancelled' and not e.confirmations.pending
    assert not any(c['name']=='click' for c in e.platform.executed)
    e.memory.close()

async def test_vision_escalation_and_image_feedback(tmp_path):
    script=Script([call('inspect_screen'),call('search_ui',query='orders'),call('get_ui_state'),
                   call('inspect_region',bounds={'x':0,'y':0,'width':20,'height':20}),call('complete_task',message='done')])
    e=make(tmp_path,script)
    async def emit(status,**f):
        if status=='confirmation_required':
            c=f['confirmation']; e.confirmations.respond('task',{k:c[k] for k in ('confirmation_id','call_id','action_hash')}|{'approved':True})
    await e.run('task',{'text':'inspect'},emit)
    assert script.feedback[1][0][1]['error']['code']=='escalation_order'
    assert script.feedback[4][0][1]['image']['mime_type']=='image/png'
    assert not any(c['name']=='inspect_screen' for c in e.platform.executed)
    e.memory.close()

async def test_missing_key_is_clear(tmp_path,monkeypatch):
    from agent.providers import GeminiModel
    import agent.providers as providers
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    monkeypatch.setattr(providers,'ACTIVE',None)
    e=make(tmp_path); e.model_factory=GeminiModel; events=[]
    async def emit(status,**f): events.append((status,f))
    await e.run('task',{'text':'hello'},emit)
    assert events[-1][1]['error']['code']=='configuration_error'
    # The message must tell the person where to put the key, not just that it is missing.
    message=events[-1][1]['error']['message']
    assert 'Gemini API key' in message and 'Settings' in message
    e.memory.close()

async def test_slow_provider_cancelled(tmp_path):
    class Slow(Script):
        async def next(self,*a): await asyncio.sleep(100)
    e=make(tmp_path,Slow([])); e.timeout=.01; events=[]
    async def emit(status,**f): events.append(status)
    await e.run('task',{'text':'hi'},emit)
    assert events[-1]=='error'; e.memory.close()

async def test_denial_stops_model_from_proposing_bypass(tmp_path):
    model=Script([call('click',x=1,y=2),call('open_app',name='calculator')]); e=make(tmp_path,model)
    async def emit(status,**f):
        if status=='confirmation_required':
            c=f['confirmation']; e.confirmations.respond('task',{k:c[k] for k in ('confirmation_id','call_id','action_hash')}|{'approved':False})
    await e.run('task',{'text':'click'},emit)
    assert len(model.contexts)==1
    assert not any(c['name']=='open_app' for c in e.platform.executed)
    e.memory.close()

async def test_unsolicited_image_cannot_reach_provider(tmp_path):
    from agent.platform import PIXEL
    class Bad(MockPlatform):
        async def execute(self,tid,tool):
            result=await super().execute(tid,tool)
            result['image']={'mime_type':'image/png','data':PIXEL,'scope':'screen'}
            return result
    script=Script([call('get_system_state'),call('complete_task',message='stopped')]);e=make(tmp_path,script,Bad())
    async def emit(*a,**k): pass
    await e.run('task',{'text':'state'},emit)
    assert 'image' not in script.feedback[1][0][1]
    assert not script.feedback[1][0][1]['ok']; e.memory.close()

async def test_approved_click_executes_once_and_stale_revision_does_not(tmp_path):
    e=make(tmp_path,Script([call('click',x=1,y=2),call('complete_task',message='done')]))
    async def emit(status,**f):
        if status=='confirmation_required':
            c=f['confirmation']; e.confirmations.respond('task',{k:c[k] for k in ('confirmation_id','call_id','action_hash')}|{'approved':True})
    await e.run('task',{'text':'click'},emit)
    assert len([c for c in e.platform.executed if c['name']=='click'])==1
    e.model_factory=lambda:Script([call('click',x=1,y=2),call('complete_task',message='stale')])
    async def stale(status,**f):
        if status=='confirmation_required':
            e.platform.revision+=1
            await emit(status,**f)
    await e.run('task',{'text':'click'},stale)
    assert len([c for c in e.platform.executed if c['name']=='click'])==1
    e.memory.close()

async def test_cancel_during_voice(tmp_path):
    class Voice:
        async def transcribe(self,audio): await asyncio.sleep(100)
    e=make(tmp_path); e.voice=Voice(); ready=asyncio.Event(); events=[]
    async def emit(status,**fields):
        events.append(status)
        if status=='listening': ready.set()
    running=asyncio.create_task(e.run('task',{'audio':{'mime_type':'audio/wav','encoding':'base64','data':'dGVzdA=='}},emit))
    await ready.wait(); running.cancel()
    with pytest.raises(asyncio.CancelledError): await running
    assert events[-1]=='cancelled'; e.memory.close()

async def test_region_consent_cannot_upload_full_screen(tmp_path):
    class WrongScope(MockPlatform):
        async def execute(self,tid,tool):
            result=await super().execute(tid,tool)
            if tool['name']=='inspect_region': result['image']['scope']='screen'
            return result
    e=make(tmp_path,platform=WrongScope())
    tool=call('inspect_region',bounds={'x':0,'y':0,'width':20,'height':20})
    with pytest.raises(ValueError,match='approved scope'): await e.adapter('task',tool)
    e.memory.close()
