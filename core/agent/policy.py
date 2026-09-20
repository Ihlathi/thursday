"""Independent policy. Model-supplied risk labels are never accepted.

Two postures, selected by AGENT_POLICY_MODE:

* `assistive` (default) -- this is an accessibility tool, so operating a named,
  visible control that a trusted accessibility adapter described is ordinary
  work. Confirmation is reserved for what a person cannot easily undo:
  deletion, credentials, security surfaces, and keys that close or lock the
  session. Confirmations are also spoken aloud, because a user who needs this
  tool may not be reading the screen.
* `strict` -- the original fail-closed posture, confirming every mutation that
  is not provably reversible.

Unknown-target, locked-machine and shell-execution rules are identical in both.
"""
import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass
from .contracts import TOOLS, uid, validate_def

@dataclass(frozen=True)
class Decision:
    risk: str
    confirm: bool
    reason: str
    blocked: bool = False

REVERSIBLE_APPS=('calculator','notepad','settings','browser','explorer','files')
TRUSTED_SOURCES=('api','accessibility','mock')
# Combinations that close, lock, or hand off the session. Ordinary typing is not
# in this set.
GUARDED_KEYS={'alt+f4','ctrl+alt+delete','ctrl+alt+del','win+l','win+r'}

def assistive_posture():
    """`strict` restores the original fail-closed behaviour."""
    return os.getenv('AGENT_POLICY_MODE','assistive').strip().lower()!='strict'

def normalise_key(key):
    return '+'.join(p.strip().lower() for p in str(key).replace('-','+').split('+') if p.strip())

class Policy:
    def classify(self, tool, world):
        validate_def('ToolCall',tool)
        name,args=tool['name'],tool['arguments']
        risk=TOOLS[name]['risk']
        relaxed=assistive_posture()
        reason=None
        # A locked machine is never operated, in either posture.
        if world.system and world.system['locked'] and risk!='READ_ONLY':
            return Decision('SECURITY_SENSITIVE',False,'The computer is locked.',True)
        if name == 'propose_command':
            return Decision('SECURITY_SENSITIVE',True,'Review only: arbitrary shell execution is disabled.')
        if name=='open_app':
            known=args['name'].lower() in REVERSIBLE_APPS
            risk='REVERSIBLE' if known or relaxed else 'CONSEQUENTIAL'
        if name in ('invoke_ui','set_ui_value'):
            e=world.elements.get(args['id'])
            if not e or not e['enabled'] or not e['visible']:
                return Decision('CONSEQUENTIAL',False,'That control is missing, hidden, or disabled.',True)
            trusted=e['source'] in TRUSTED_SOURCES
            if e['sensitive'] or e['action_kind']=='security':
                risk,reason='SECURITY_SENSITIVE','This is a password or security control.'
            elif e['action_kind']=='delete':
                risk,reason='DESTRUCTIVE',f"This deletes {e['name'] or 'the selected item'}."
            elif name=='invoke_ui' and e['action_kind']=='navigation' and trusted:
                risk='REVERSIBLE'
            elif relaxed and trusted:
                # A named control the accessibility adapter reports as visible
                # and enabled: operating it is the request, not an escalation.
                risk='REVERSIBLE'
            else:
                risk='CONSEQUENTIAL'
        if name=='press_key':
            if normalise_key(args['key']) in GUARDED_KEYS:
                risk,reason='CONSEQUENTIAL',f"{args['key']} closes or locks what you are working in."
            elif relaxed:
                risk='REVERSIBLE'
        if relaxed and name in ('click','move_mouse','scroll','type_text','open_url','open_file','open_folder'):
            # Pointer movement, typing and opening things are the assistant's
            # ordinary vocabulary; confirming each one makes it unusable for the
            # person who needs it most, and a prompt shown constantly is a prompt
            # nobody reads.
            risk='REVERSIBLE'
        # Only explicit bounded settings may bypass confirmation.
        if name == 'set_setting' and args['setting'] in ('volume','brightness'):
            v=args['value']
            if type(v) in (int,float) and 0<=v<=100:
                risk='REVERSIBLE'
        if reason is None:
            reason=('Screen content will be sent to the model.' if name in ('inspect_region','inspect_screen')
                    else f'{risk.lower().replace("_"," ")} action')
        return Decision(risk,risk not in ('READ_ONLY','REVERSIBLE'),reason)

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
