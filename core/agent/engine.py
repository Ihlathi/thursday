"""Bounded observe/act loop. All execution crosses independent policy."""
import asyncio
import base64
import os
import re
import time
from .contracts import TOOLS, call, validate_def, uid
from .policy import Policy, Confirmations
from .providers import ConfigurationError, ElevenLabsVoice
from .world import World

class Engine:
    def __init__(self,platform,working,memory,model_factory,*,max_steps=16,timeout=45,confirmation_timeout=60,voice=None):
        self.platform,self.working,self.memory=platform,working,memory
        self.model_factory=model_factory
        self.max_steps,self.timeout=max_steps,timeout
        self.policy=Policy()
        self.confirmations=Confirmations(confirmation_timeout)
        self.voice=voice or ElevenLabsVoice()
        self.world=World()
        self.replies={}
    def reply(self,task_id,payload):
        f=self.replies.get((task_id,payload['reply_to']))
        if f is None or f.done(): return False
        f.set_result(payload['text']); return True
    async def resolve_spoken(self,payload):
        """Turn a spoken answer into the field the protocol expects.

        A user who talks to this tool answers its questions the same way. Core
        already owns transcription, so the UI ships the recording and Core
        resolves it into `text` (a reply) or `approved` (a confirmation).
        """
        if 'audio' not in payload: return payload
        text=await asyncio.wait_for(self.voice.transcribe(payload['audio']),self.timeout)
        resolved={k:v for k,v in payload.items() if k!='audio'}
        if 'reply_to' in resolved:
            resolved['text']=(text or '').strip()[:4096] or 'no answer'
        else:
            resolved['approved']=self.approves(text)
        return resolved
    @staticmethod
    def approves(text):
        """Deterministic yes/no. Code decides consent, never the model, and
        anything unclear counts as no rather than as a silent yes."""
        words=set(re.findall(r"[a-z]+",(text or '').lower()))
        if words & {'no','nope','stop','cancel','dont','deny','negative','abort','nevermind','wait'}: return False
        return bool(words & {'yes','yeah','yep','yup','sure','ok','okay','okey','confirm','approve','approved','go','proceed','continue','affirmative','correct','please'})
    async def adapter(self,task_id,tool):
        result=await asyncio.wait_for(self.platform.execute(task_id,tool),self.timeout)
        validate_def('ToolResult',result)
        if result['call_id']!=tool['call_id']: raise ValueError('Mismatched call ID')
        if result.get('image') and tool['name'] not in ('inspect_region','inspect_screen'):
            raise ValueError('Unsolicited image from non-capture tool')
        if result.get('image') and not result['ok']:
            raise ValueError('Image on failed tool')
        if result['ok'] and tool['name'] in ('inspect_region','inspect_screen'):
            image=result.get('image')
            expected='region' if tool['name']=='inspect_region' else 'screen'
            if not image or image['scope']!=expected:
                raise ValueError('Capture did not match approved scope')
            if expected=='region' and image.get('bounds')!=tool['arguments']['bounds']:
                raise ValueError('Capture did not match approved bounds')
        if result.get('delta'):
            previous=self.world.system
            delta=result['delta']
            if previous and delta.get('system',{}).get('sleep_epoch',previous['sleep_epoch'])!=previous['sleep_epoch']:
                self.working.clear()
            self.world.update(delta)
        return result
    def model_result(self,result):
        """Bound context and remove sensitive UI content before cloud input."""
        result=dict(result)
        if 'delta' in result:
            delta=result.pop('delta')
            result['observed_revision']=delta['revision']
        return result
    async def run(self,task_id,request,emit):
        model=None
        self.world=World()  # never reuse stale desktop elements across tasks
        self.world.task=task_id
        feedback=[]
        escalations=set()
        sent_images=[]
        try:
            validate_def('UserRequest',request)
            # Spoken sessions get spoken prompts: a question the user cannot see
            # is the same as no question at all.
            self.speak=bool(request.get('speak'))
            if 'audio' in request:
                await emit('listening',message='Transcribing with ElevenLabs')
                text=await asyncio.wait_for(self.voice.transcribe(request['audio']),self.timeout)
            else: text=request['text']
            if not text.strip(): raise ValueError('Empty transcription')
            history=self.working.read()
            recalled=self.memory.retrieve(text)
            self.working.add('user',text)
            promoted=self.memory.consider(text)
            model=self.model_factory()  # no intent router before this boundary
            await emit('debug',metadata={'kind':'task_started','provider':model.label,'memory_hits':len(recalled),'promoted':promoted})
            for step in range(self.max_steps):
                await emit('thinking')
                context={'request':text,'conversation':history[-6:],'recalled_memory':recalled,'world':self.world.context(text)}
                images=[r['image'] for _,r in feedback if 'image' in r]
                sent_images.extend(images)
                await emit('debug',metadata={'kind':'context_sent','step':step,'element_ids':[e['id'] for e in context['world']['relevant_elements']],
                    'conversation_items':len(context['conversation']),'memory_items':len(recalled),'system_included':self.world.system is not None,
                    'images':[{'scope':im['scope'],'bytes':len(base64.b64decode(im['data'])),'mime_type':im['mime_type']} for im in sent_images],
                    'new_image_count':len(images),
                    'cloud':model.label=='gemini'})
                started=time.monotonic()
                turn=await asyncio.wait_for(model.next(context,feedback),self.timeout)
                feedback=[]
                await emit('debug',metadata={'kind':'model_decision','tools':[c['name'] for c in turn.calls],'latency_ms':round((time.monotonic()-started)*1000)})
                if not turn.calls:
                    if not turn.text: raise RuntimeError('Empty model response')
                    await self.finish(turn.text,request,emit)
                    return
                # Reply to every proposed call, but execute at most one. This preserves provider protocol.
                for i,tool in enumerate(turn.calls):
                    validate_def('ToolCall',tool)
                    if i>0:
                        result=self.failure(tool,'replan_required','Only one tool per turn; observe and replan.')
                    else:
                        result=await self.execute(task_id,tool,emit,escalations)
                    feedback.append((tool,self.model_result(result)))
                    self.world.observations.append({'tool':tool['name'],'ok':result['ok']})
                    if result.get('error',{}).get('code')=='confirmation_denied':
                        await emit('completed',message='Action denied or confirmation expired. Task stopped without executing it.')
                        return
                    if result.get('error',{}).get('code')=='execution_uncertain':
                        await emit('error',error=result['error'])
                        return
                    if tool['name']=='complete_task' and result['ok']:
                        await self.finish(tool['arguments']['message'],request,emit)
                        return
            raise RuntimeError('Task reached the configured step limit')
        except asyncio.CancelledError:
            self.confirmations.cancel(task_id)
            for (owner,_),future in list(self.replies.items()):
                if owner==task_id and not future.done(): future.cancel()
            try: await self.platform.cancel(task_id)
            except Exception: pass
            await emit('cancelled',message='Task cancelled. An action already dispatched may have completed.')
            raise
        except Exception as exc:
            provider_code=getattr(exc,'code',None)
            provider_status=getattr(exc,'status',None)
            provider_message=getattr(exc,'message',None)
            if provider_code is not None or provider_status is not None:
                await emit('debug',metadata={'kind':'provider_error','error_type':type(exc).__name__,
                    'status_code':provider_code,'provider_status':provider_status,
                    'provider_message':str(provider_message or '')[:500]})
            message=str(exc) if isinstance(exc,ConfigurationError) else 'Task failed: '+type(exc).__name__+'. Check provider configuration or bridge availability.'
            await emit('error',error={'code':'configuration_error' if isinstance(exc,ConfigurationError) else 'task_failed','message':message,'retryable':True})
        finally:
            if model:
                try: await model.close()
                except Exception: pass
    async def finish(self,message,request,emit):
        self.working.add('assistant',message)
        if request.get('speak'):
            try:
                audio=await asyncio.wait_for(self.voice.speak(message),self.timeout)
                await emit('speaking',audio=audio)
            except asyncio.CancelledError: raise
            except Exception as exc:
                # The HTTP status is the only way to tell a bad voice ID from a
                # key without TTS permission. No body, no headers, no key.
                detail={'kind':'voice_unavailable','error_type':type(exc).__name__}
                status=getattr(getattr(exc,'response',None),'status_code',None)
                if status: detail['status']=status
                await emit('debug',metadata=detail)
        await emit('completed',message=message[:4096])
    async def settle(self,task_id,name,emit):
        """Wait for the desktop to catch up, then observe.

        A menu animates, a window draws, a page loads. Observing the instant a
        click returns plans the next step against a screen that no longer
        exists, which is what makes a multi-step sequence fall apart halfway.
        So: poll until the world's revision moves, or until the budget runs out.
        Launching something gets a longer budget than clicking something.
        """
        launch=name in ('open_app','open_url','open_file','open_folder')
        step=float(os.getenv('AGENT_SETTLE_MS','500'))/1000*(2 if launch else 1)
        tries=int(os.getenv('AGENT_SETTLE_TRIES','6' if launch else '3'))
        before=self.world.revision
        observed=None
        for attempt in range(max(1,tries)):
            await asyncio.sleep(step)
            observed=await self.adapter(task_id,call('get_ui_state'))
            if not observed['ok'] or self.world.revision!=before: break
        if observed and observed['ok']:
            await emit('debug',metadata={'kind':'settled','tool':name,'waits':attempt+1,
                                         'changed':self.world.revision!=before})
        return observed or {'ok':False}
    async def say(self,text,emit):
        """Speak a prompt aloud mid-task. Best effort; a voice failure never blocks."""
        if not getattr(self,'speak',False): return
        try:
            audio=await asyncio.wait_for(self.voice.speak(text[:600]),self.timeout)
            await emit('speaking',audio=audio)
        except asyncio.CancelledError: raise
        except Exception: pass
    def pointer_target(self,name,args):
        """Screen point a platform action will drive the mouse to, when there is one."""
        if name in ('move_mouse','click'):
            x,y=args.get('x'),args.get('y')
            return {'x':x,'y':y} if isinstance(x,(int,float)) and isinstance(y,(int,float)) else None
        if name in ('invoke_ui','set_ui_value'):
            element=self.world.elements.get(args.get('id')) or {}
            bounds=element.get('bounds')
            if bounds:
                return {'x':bounds['x']+bounds['width']/2,'y':bounds['y']+bounds['height']/2}
        return None
    @staticmethod
    def failure(tool,code,message):
        return {'call_id':tool['call_id'],'ok':False,'error':{'code':code,'message':message,'retryable':False}}
    async def execute(self,task_id,tool,emit,escalations):
        name,args=tool['name'],tool['arguments']
        try:
            # Always resolve UI targets from a fresh adapter snapshot before policy evaluation.
            if name in ('invoke_ui','set_ui_value','click','type_text','press_key'):
                fresh=await self.adapter(task_id,call('get_ui_state'))
                if not fresh['ok']: return self.failure(tool,'observation_failed','Cannot verify target')
            if name=='invoke_ui':
                # Always operate controls the visible way: the bridge glides the
                # pointer to the element, re-resolves the same semantic target,
                # then activates it. The overlay animation and the real cursor
                # then describe the same action.
                args['mode']='visible'
            if name in ('invoke_ui','set_ui_value','click','type_text','press_key'):
                tool['expected_revision']=self.world.revision
            decision=self.policy.classify(tool,self.world)
            await emit('debug',metadata={'kind':'policy','tool':name,'risk':decision.risk,'confirmation':decision.confirm,'blocked':decision.blocked})
            if decision.blocked: return self.failure(tool,'policy_blocked',decision.reason)
            if name=='inspect_region' and not {'search_ui','get_ui_state'}<=escalations:
                return self.failure(tool,'escalation_order','Search UI and request broader UI state before image capture.')
            if name=='inspect_screen' and 'inspect_region' not in escalations:
                return self.failure(tool,'escalation_order','Inspect a relevant region before full-screen capture.')
            revision=self.world.revision
            if decision.confirm:
                # Ask out loud as well as on screen, in the words a person uses:
                # "Hey, I want to use Delete, but that would delete this, and I
                # don't think I can undo it. Is that okay?"
                await self.say(f"Hey, I want to {decision.action or 'do this'}, but {decision.reason}. Is that okay?",emit)
                if not await self.confirmations.request(task_id,tool,decision,emit):
                    return self.failure(tool,'confirmation_denied','Denied or expired; do not attempt an alternative action.')
                # Refresh after human delay; never reuse approval against a changed target.
                if name in ('invoke_ui','set_ui_value','click','type_text','press_key'):
                    verified=await self.adapter(task_id,call('get_ui_state'))
                    if not verified['ok'] or self.world.revision!=revision:
                        return self.failure(tool,'stale_confirmation','Desktop changed; replan and request new approval.')
            # Tell the UI where the pointer is about to go so the overlay can
            # animate the move before the bridge executes it.
            pointer=self.pointer_target(name,args)
            await emit('acting',metadata={'tool':name,'call_id':tool['call_id'],**({'pointer':pointer} if pointer else {})})
            if name=='search_ui':
                if not self.world.elements: await self.adapter(task_id,call('get_ui_state'))
                result={'call_id':tool['call_id'],'ok':True,'data':{'elements':self.world.search(args['query'])}}
            elif name=='inspect_ui':
                e=self.world.elements.get(args['id'])
                result={'call_id':tool['call_id'],'ok':True,'data':{'element':self.world.public(e)}} if e else self.failure(tool,'missing_element','Unknown UI element')
            elif name=='ask_user':
                rid=uid(); f=asyncio.get_running_loop().create_future(); self.replies[(task_id,rid)]=f
                try:
                    await self.say(args['message'],emit)
                    await emit('awaiting_input',message=args['message'],metadata={'reply_to':rid})
                    answer=await asyncio.wait_for(f,120)
                    result={'call_id':tool['call_id'],'ok':True,'data':{'answer':answer}}
                finally: self.replies.pop((task_id,rid),None)
            elif name=='propose_command':
                result={'call_id':tool['call_id'],'ok':True,'data':{'reviewed':True,'executed':False,'message':'Arbitrary shell is disabled; use a bounded approved action.'}}
            elif name in ('complete_task','request_confirmation'):
                result={'call_id':tool['call_id'],'ok':True,'data':{'acknowledged':True}}
            else:
                result=await self.adapter(task_id,tool)
                if name=='get_ui_state' and result['ok']:
                    result.setdefault('data',{})['elements']=[self.world.public(e) for e in list(self.world.elements.values())[:40]]
                if result.get('image'):
                    image=result['image']
                    decoded=base64.b64decode(image['data'],validate=True)
                    if len(decoded)>2_000_000: raise ValueError('Image exceeds limit')
                if result['ok'] and TOOLS[name]['risk']!='READ_ONLY' and name not in ('inspect_screen','inspect_region'):
                    self.world.actions.append({'tool':name,'call_id':tool['call_id'],'ok':True})
                    observed=await self.settle(task_id,name,emit)
                    if not observed['ok']:
                        return self.failure(tool,'execution_uncertain','Action dispatched but verification failed. Observe before retrying.')
            if result['ok']: escalations.add(name)
            await emit('debug',metadata={'kind':'tool_result','tool':name,'ok':result['ok'],'revision':self.world.revision})
            return validate_def('ToolResult',result)
        except asyncio.CancelledError: raise
        except Exception as exc:
            uncertain=TOOLS[name]['owner']=='platform' and TOOLS[name]['risk']!='READ_ONLY'
            return self.failure(tool,'execution_uncertain' if uncertain else 'tool_failed',
                'Execution outcome unknown; observe before retrying.' if uncertain else 'Tool failed: '+type(exc).__name__)
