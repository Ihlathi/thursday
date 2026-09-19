"""Terminal UI harness. Confirms only after explicit interactive approval."""
import argparse
import asyncio
import json
import os
from agent.contracts import envelope, uid
from agent.transport import client_connect, receive

async def request(url,token,text,interactive=False):
    ws=await client_connect(url,'ui',token)
    tid=uid()
    try:
        await ws.send(json.dumps(envelope('user_request',{'text':text},tid)))
        while True:
            msg=await receive(ws)
            print(json.dumps(msg),flush=True)
            if msg['type']=='error': return msg
            p=msg['payload']; status=p['status']
            if status=='confirmation_required':
                c=p['confirmation']
                approve=interactive and (await asyncio.to_thread(input,'Approve exactly this action? Type yes: ')).strip()=='yes'
                response={k:c[k] for k in ('confirmation_id','call_id','action_hash')}|{'approved':approve}
                await ws.send(json.dumps(envelope('confirmation_response',response,tid)))
            if status=='awaiting_input':
                answer=await asyncio.to_thread(input,'Reply: ') if interactive else 'Please stop; non-interactive demo.'
                await ws.send(json.dumps(envelope('user_reply',{'reply_to':p['metadata']['reply_to'],'text':answer},tid)))
            if status in ('completed','cancelled','error'): return msg
    finally: await ws.close()

def main():
    p=argparse.ArgumentParser(); p.add_argument('text',nargs='?',default='show me the stuff I bought recently')
    p.add_argument('--url',default='ws://127.0.0.1:8765/v1/ui'); p.add_argument('--interactive',action='store_true')
    args=p.parse_args()
    try: asyncio.run(request(args.url,os.environ['AGENT_UI_TOKEN'],args.text,args.interactive))
    except KeyboardInterrupt: pass
if __name__=='__main__': main()
