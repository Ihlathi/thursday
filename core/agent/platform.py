"""Platform-independent adapter boundary and deterministic fake desktop."""
import base64
from copy import deepcopy
from .contracts import validate_def

PIXEL='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='

def element(eid='orders',name='Returns & Orders',kind='navigation'):
    return {'id':eid,'role':'button','name':name,'description':'View recent purchases and order history',
            'bounds':{'x':20,'y':20,'width':180,'height':40},'enabled':True,'visible':True,
            'parent':None,'children':[],'source':'mock','confidence':1.0,'sensitive':False,'action_kind':kind}

class MockPlatform:
    def __init__(self):
        self.revision=0
        self.elements=[element()]
        self.system={'active_app':'Mock Browser','active_window':'Shop','locked':False,'sleep_epoch':0,'revision':0}
        self.executed=[]
    async def execute(self,task_id,tool):
        validate_def('ToolCall',tool)
        name,args=tool['name'],tool['arguments']
        if 'expected_revision' in tool and tool['expected_revision']!=self.revision:
            return {'call_id':tool['call_id'],'ok':False,'error':{'code':'stale_target','message':'Desktop revision changed','retryable':False}}
        self.executed.append(tool)
        data={'mock':True}
        result={'call_id':tool['call_id'],'ok':True,'data':data}
        if name in ('get_system_state','get_ui_state'):
            pass
        elif name in ('inspect_screen','inspect_region'):
            result['image']={'mime_type':'image/png','data':PIXEL,'scope':'region' if name=='inspect_region' else 'screen'}
            if 'bounds' in args: result['image']['bounds']=args['bounds']
        elif name=='invoke_ui':
            self.system['active_window']='Orders — Mock Browser'
            data['invoked']=args['id']
            self.revision+=1
        elif name in ('open_app','open_url','set_setting','set_ui_value','scroll','move_mouse','click','type_text','press_key','open_file','open_folder','run_approved_action'):
            self.revision+=1
            data['simulated']=name
        else:
            return {'call_id':tool['call_id'],'ok':False,'error':{'code':'unsupported_tool','message':'Unsupported mock platform tool','retryable':False}}
        self.system['revision']=self.revision
        result['delta']={'revision':self.revision,'system':deepcopy(self.system)}
        if name=='get_ui_state': result['delta'].update(elements=deepcopy(self.elements),full=True)
        return validate_def('ToolResult',result)
    async def cancel(self,task_id): pass
