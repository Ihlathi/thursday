"""The shared JSON files are the single contract source of truth."""
import json
import os
from pathlib import Path
from uuid import uuid4
from jsonschema import Draft202012Validator

SHARED = Path(os.getenv('AGENT_SHARED_DIR', Path(__file__).resolve().parents[2] / 'shared'))
SCHEMA = json.loads((SHARED / 'protocol.schema.json').read_text())
TOOLS = json.loads((SHARED / 'tools.json').read_text())['tools']
VALIDATOR = Draft202012Validator(SCHEMA)

def uid():
    return uuid4().hex

def validate(message):
    VALIDATOR.validate(message)
    return message

def validate_def(name, value):
    Draft202012Validator({'$defs': SCHEMA['$defs'], '$ref': f'#/$defs/{name}'}).validate(value)
    return value

def envelope(kind, payload, task_id=None, request_id=None):
    message = {'version': '1.0', 'type': kind, 'request_id': request_id or uid(), 'payload': payload}
    if task_id is not None:
        message['task_id'] = task_id
    return validate(message)

def call(tool_name, **arguments):
    return validate_def('ToolCall', {'call_id': uid(), 'name': tool_name, 'arguments': arguments})
