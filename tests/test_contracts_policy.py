import asyncio
import copy
import pytest
from jsonschema import ValidationError, Draft202012Validator
from agent.contracts import SCHEMA, TOOLS, call, envelope, validate, validate_def
from agent.platform import element
from agent.policy import Policy, Confirmations
from agent.world import World

def test_shared_contracts_are_valid_and_strict():
    Draft202012Validator.check_schema(SCHEMA)
    for tool in TOOLS.values(): Draft202012Validator.check_schema(tool['parameters'])
    validate(envelope('user_request',{'text':'hello'},'task'))
    with pytest.raises(ValidationError): envelope('user_request',{'text':'x','audio':{}},'task')
    with pytest.raises(ValidationError): call('run_approved_action',action='shell',args={'value':1})
    with pytest.raises(ValidationError): call('run_approved_action',action='set_volume',args={'value':101})
    with pytest.raises(ValidationError): call('click',x=1,y=2,risk='READ_ONLY')
    with pytest.raises(ValidationError): validate_def('ToolResult',{'call_id':'x','ok':False})

def world(kind='navigation'):
    w=World(); w.update({'revision':1,'elements':[element(kind=kind)],'full':True}); return w

def test_policy_uses_authoritative_action_context():
    p=Policy()
    assert not p.classify(call('invoke_ui',id='orders',mode='direct'),world()).confirm
    assert p.classify(call('invoke_ui',id='orders',mode='direct'),world('submit')).confirm
    assert p.classify(call('invoke_ui',id='orders',mode='visible'),world('delete')).risk=='DESTRUCTIVE'
    assert p.classify(call('click',x=0,y=0),world()).confirm
    assert p.classify(call('type_text',text='hello'),world()).confirm
    assert p.classify(call('press_key',key='ENTER'),world()).confirm
    assert p.classify(call('set_setting',setting='firewall',value=False),world()).confirm
    assert not p.classify(call('set_setting',setting='volume',value=20),world()).confirm
    assert p.classify(call('invoke_ui',id='unknown',mode='direct'),world()).blocked

async def test_confirmation_bound_one_use_denial_and_cancel():
    c=Confirmations(timeout=1); captured=asyncio.Queue()
    async def emit(status,**fields): await captured.put(fields['confirmation'])
    tool=call('click',x=1,y=2); decision=Policy().classify(tool,world())
    task=asyncio.create_task(c.request('task1',tool,decision,emit)); request=await captured.get()
    response={k:request[k] for k in ('confirmation_id','call_id','action_hash')}|{'approved':False}
    assert not c.respond('wrong-task',response)
    assert not c.respond('task1',response|{'action_hash':'wrong'})
    assert c.respond('task1',response)
    assert not await task
    assert not c.respond('task1',response)
    task=asyncio.create_task(c.request('task2',tool,decision,emit)); await captured.get()
    c.cancel('task2')
    with pytest.raises(asyncio.CancelledError): await task
    assert not c.pending

def test_all_committed_wire_examples_validate():
    import json
    from pathlib import Path
    for path in ('shared/examples.json','mocks/agent-events.json'):
        for message in json.loads(Path(path).read_text()): validate(message)

def test_catalog_and_call_validation_do_not_drift():
    branches=SCHEMA['$defs']['ToolCall']['allOf']
    for name,tool in TOOLS.items():
        branch=next(b for b in branches if b['if']['properties']['name']['const']==name)
        assert branch['then']['properties']['arguments']==tool['parameters']

async def test_confirmation_timeout_fails_closed():
    c=Confirmations(timeout=.01)
    async def emit(*args,**kwargs): pass
    tool=call('click',x=1,y=2)
    assert not await c.request('task',tool,Policy().classify(tool,world()),emit)
    assert not c.pending


def test_every_tool_is_described_for_the_model():
    """Tool descriptions are the model's only documentation; placeholders cost accuracy."""
    from agent.contracts import TOOLS

    for name, tool in TOOLS.items():
        description = tool['description']
        assert len(description) > 40, f'{name} has a placeholder description'
        assert description != name.replace('_', ' '), f'{name} only restates its own name'
        assert description[0].isupper() and description.rstrip().endswith('.'), name
