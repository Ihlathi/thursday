import base64
from types import SimpleNamespace
from google.genai import types
import httpx
from agent.providers import GeminiModel,ElevenLabsVoice
from agent.contracts import call
from agent.platform import PIXEL

async def test_gemini_multimodal_and_native_signature_preserved():
    seen=[]
    native=types.Content(role='model',parts=[types.Part(function_call=types.FunctionCall(id='provider-call',name='inspect_screen',args={}),thought_signature=b'signature')])
    class Models:
        async def generate_content(self,**kwargs):
            seen.append(kwargs)
            return types.GenerateContentResponse(candidates=[types.Candidate(content=native)])
    client=SimpleNamespace(aio=SimpleNamespace(models=Models()))
    model=GeminiModel(client=client)
    turn=await model.next({'request':'inspect'},[])
    assert model.history[-1].parts[0].thought_signature==b'signature'
    assert model.config.automatic_function_calling.disable is True
    tool=turn.calls[0]
    await model.next({'request':'continue'},[(tool,{'call_id':tool['call_id'],'ok':True,'image':{'data':PIXEL,'mime_type':'image/png','scope':'screen'}})])
    contents=seen[1]['contents']
    assert [content.role for content in contents[:3]]==['user','model','user']
    assert contents[2].parts[0].function_response.id=='provider-call'
    assert contents[2].parts[0].function_response.response['context']['request']=='continue'
    assert any(p.inline_data and p.inline_data.data==base64.b64decode(PIXEL) for p in contents[2].parts)

async def test_voice_http_contracts(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_API_KEY','test-key'); monkeypatch.setenv('ELEVENLABS_VOICE_ID','test-voice')
    requests=[]
    def handler(request):
        requests.append(request)
        assert request.headers['xi-api-key']=='test-key'
        if request.url.path.endswith('speech-to-text'): return httpx.Response(200,json={'text':'hello'})
        return httpx.Response(200,content=b'audio',headers={'Content-Type':'audio/mpeg'})
    voice=ElevenLabsVoice(httpx.MockTransport(handler))
    assert await voice.transcribe({'mime_type':'audio/wav','encoding':'base64','data':base64.b64encode(b'test').decode()})=='hello'
    assert base64.b64decode((await voice.speak('hello'))['data'])==b'audio'
    assert len(requests)==2
