import base64
from types import SimpleNamespace
from google.genai import types
import httpx
from agent.providers import GeminiModel,ElevenLabsVoice
from agent.contracts import call
from agent.platform import PIXEL

async def test_gemini_multimodal_and_native_signature_preserved():
    seen=[]
    native=types.Content(role='model',parts=[types.Part(function_call=types.FunctionCall(id='provider-call',name='complete_task',args={'message':'done'}),thought_signature=b'signature')])
    class Models:
        async def generate_content(self,**kwargs):
            seen.append(kwargs)
            return types.GenerateContentResponse(candidates=[types.Candidate(content=native)])
    client=SimpleNamespace(aio=SimpleNamespace(models=Models()))
    model=GeminiModel(client=client)
    tool=call('inspect_screen')
    turn=await model.next({'request':'inspect'},[(tool,{'call_id':tool['call_id'],'ok':True,'image':{'data':PIXEL,'mime_type':'image/png','scope':'screen'}})])
    parts=seen[0]['contents'][0].parts
    assert any(p.inline_data and p.inline_data.data==base64.b64decode(PIXEL) for p in parts)
    assert model.history[-1].parts[0].thought_signature==b'signature'
    assert model.config.automatic_function_calling.disable is True
    await model.next({'request':'continue'},[(turn.calls[0],{'call_id':turn.calls[0]['call_id'],'ok':True})])
    assert model.history[-2].parts[1].function_response.id=='provider-call'

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
