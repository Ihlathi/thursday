"""Repo-local launcher, independent of editable-install path handling."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent/'core'))
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='desktop':
        sys.argv.pop(1)
        from agent.desktop import main as desktop_main
        desktop_main()
    elif len(sys.argv)>1 and sys.argv[1]=='windows-platform':
        sys.argv.pop(1)
        runpy.run_path(str(Path(__file__).resolve().parent/'platform'/'windows'/'bridge.py'),run_name='__main__')
    elif len(sys.argv)>1 and sys.argv[1] in ('stack','mock-platform','mock-ui'):
        module={'stack':'mocks.stack','mock-platform':'mocks.platform','mock-ui':'mocks.ui'}[sys.argv.pop(1)]
        runpy.run_module(module,run_name='__main__')
    else:
        from agent.cli import main
        main()
