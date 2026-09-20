import argparse
import asyncio
import json
import os
import tempfile
from .contracts import uid
from .engine import Engine
from .memory import WorkingMemory, LongTermMemory
from .platform import MockPlatform
from .providers import GeminiModel, MockModel
from .server import CoreServer

def model_factory(mode): return MockModel if mode=='mock' else GeminiModel

async def demo(args):
    with tempfile.TemporaryDirectory() as directory:
        memory=LongTermMemory(directory+'/memory.sqlite3')
        engine=Engine(MockPlatform(),WorkingMemory(),memory,model_factory(args.mode))
        task_id=uid()
        async def emit(status,**fields):
            print(json.dumps({'status':status,**fields}),flush=True)
            if status=='confirmation_required':
                # Demo is deliberately non-interactive and denies confirmations.
                p=fields['confirmation']
                engine.confirmations.respond(task_id,{k:p[k] for k in ('confirmation_id','call_id','action_hash')}|{'approved':False})
        try: await engine.run(task_id,{'text':args.text},emit)
        finally: memory.close()

async def server(args):
    # No --mode: the provider follows Settings, so a key saved from the tray
    # takes effect without a restart. An explicit --mode pins it for the run.
    forced=model_factory(args.mode) if args.mode else None
    # AGENT_MODEL_MODE only seeds the default; Settings can still switch at runtime.
    app=CoreServer(os.getenv('AGENT_UI_TOKEN',''),os.getenv('AGENT_PLATFORM_TOKEN',''),forced,
                   os.getenv('AGENT_DATA_DIR','.agent-data'),
                   mode=args.mode or os.getenv('AGENT_MODEL_MODE') or 'gemini')
    port=await app.start(args.port)
    print(f'Core ready at ws://127.0.0.1:{port}/v1/ui; provider={args.mode or app.settings.model_mode+" (from settings)"}',flush=True)
    try: await asyncio.Future()
    finally: await app.close()

def main():
    parser=argparse.ArgumentParser(description='Adaptive Accessibility Agent Core')
    commands=parser.add_subparsers(dest='command',required=True)
    d=commands.add_parser('demo',help='Mock desktop; explicit mock or live Gemini mode')
    d.add_argument('--text',default='show me the stuff I bought recently')
    d.add_argument('--mode',choices=['mock','gemini'],default=os.getenv('AGENT_MODEL_MODE','mock'))
    s=commands.add_parser('serve')
    s.add_argument('--port',type=int,default=8765)
    s.add_argument('--mode',choices=['mock','gemini'],default=None,
                   help='Pin the provider for this run; omit to follow saved settings')
    args=parser.parse_args()
    try: asyncio.run(demo(args) if args.command=='demo' else server(args))
    except KeyboardInterrupt: pass
    except ValueError as exc: parser.error(str(exc))

if __name__=='__main__': main()
