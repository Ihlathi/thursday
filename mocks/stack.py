"""One-command verification of the actual WebSocket vertical slice."""
import asyncio
import secrets
import tempfile
from agent.server import CoreServer
from agent.providers import MockModel
from .platform import run
from .ui import request

async def main():
    with tempfile.TemporaryDirectory() as data:
        ui_token,platform_token=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        server=CoreServer(ui_token,platform_token,MockModel,data)
        port=await server.start(0)
        ready=asyncio.Event()
        platform=asyncio.create_task(run(f'ws://127.0.0.1:{port}/v1/platform',platform_token,ready))
        try:
            await asyncio.wait_for(ready.wait(),5)
            result=await request(f'ws://127.0.0.1:{port}/v1/ui',ui_token,'show me the stuff I bought recently')
            if result['payload'].get('status')!='completed': raise RuntimeError('Demo failed')
        finally:
            platform.cancel(); await asyncio.gather(platform,return_exceptions=True)
            await server.close()
if __name__=='__main__': asyncio.run(main())
