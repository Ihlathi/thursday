"""Independent, fail-closed policy. Model-supplied risk labels are never accepted."""
import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from .contracts import TOOLS, uid, validate_def

@dataclass(frozen=True)
class Decision:
    risk: str
    confirm: bool
    reason: str
    blocked: bool = False

class Policy:
    def classify(self, tool, world):
        validate_def('ToolCall',tool)
        name,args=tool['name'],tool['arguments']
        risk=TOOLS[name]['risk']
        if world.system and world.system['locked'] and risk!='READ_ONLY':
            return Decision('SECURITY_SENSITIVE',False,'Computer is locked.',True)
        if name=='open_app' and args['name'].lower() not in ('calculator','notepad','settings','browser'):
            risk='CONSEQUENTIAL'
        if name == 'propose_command':
            return Decision('SECURITY_SENSITIVE',True,'Review only: arbitrary shell execution is disabled.')
        if name in ('invoke_ui','set_ui_value'):
            e=world.elements.get(args['id'])
            if not e or not e['enabled'] or not e['visible']:
                return Decision('CONSEQUENTIAL',False,'Target is missing, hidden, or disabled.',True)
            if e['sensitive'] or e['action_kind']=='security':
                risk='SECURITY_SENSITIVE'
            elif e['action_kind']=='delete':
                risk='DESTRUCTIVE'
            elif name=='invoke_ui' and e['action_kind']=='navigation' and e['source'] in ('api','accessibility','mock'):
                risk='REVERSIBLE'
            else:
                risk='CONSEQUENTIAL'
        # Only explicit bounded settings may bypass confirmation.
        if name == 'set_setting' and args['setting'] in ('volume','brightness'):
            v=args['value']
            if type(v) in (int,float) and 0<=v<=100:
                risk='REVERSIBLE'
        return Decision(risk,risk not in ('READ_ONLY','REVERSIBLE'),
                        'Screen content will be sent to the model.' if name.startswith('inspect_') and name in ('inspect_region','inspect_screen') else f'{risk.lower().replace("_"," ")} action')

class Confirmations:
    def __init__(self, timeout=60):
        self.timeout=timeout
        self.pending={}
    async def request(self, task_id, tool, decision, emit):
        digest=hashlib.sha256(json.dumps(tool,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        cid=uid()
        payload={'confirmation_id':cid,'call_id':tool['call_id'],'action_hash':digest,
                 'action':tool['name']+': '+json.dumps(tool['arguments'],ensure_ascii=False),
                 'consequence':decision.reason,'risk':decision.risk,'expires_at':time.time()+self.timeout}
        future=asyncio.get_running_loop().create_future()
        self.pending[cid]=(task_id,payload,future)
        try:
            await emit('confirmation_required',confirmation=payload)
            return await asyncio.wait_for(future,self.timeout)
        except TimeoutError:
            return False
        finally:
            self.pending.pop(cid,None)
    def respond(self, task_id, response):
        validate_def('ConfirmationResponse',response)
        entry=self.pending.get(response['confirmation_id'])
        if not entry: return False
        owner,payload,future=entry
        if owner!=task_id or future.done() or time.time()>payload['expires_at']:
            return False
        if any(response[k]!=payload[k] for k in ('call_id','action_hash')):
            return False
        future.set_result(response['approved'])
        return True
    def cancel(self, task_id):
        for owner,_,future in list(self.pending.values()):
            if owner==task_id and not future.done(): future.cancel()
