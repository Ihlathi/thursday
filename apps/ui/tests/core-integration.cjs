const fs = require('fs');
const vm = require('vm');
const assert = require('node:assert/strict');
const ts = require(process.cwd() + '/node_modules/typescript');
const listeners = new Map(), sent = [], nodes = new Map();
class Element {
  constructor() { this.children = []; this.value = ''; this.checked = false; this.textContent = ''; }
  append(p) { this.children.push(p); }
  replaceChildren() { this.children = []; }
  scrollIntoView() {}
  querySelector() { return element('form'); }
}
function element(id) { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); }
const source = fs.readFileSync('src/assistant-window.ts', 'utf8').replace(/^import .*;\r?\n/gm, '');
const js = ts.transpile(source, { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None });
let next = 0;
const context = { document: { querySelector: () => element('app'), getElementById: element, createElement: () => new Element() },
  invoke: async (command, args) => { if (command === 'core_send') sent.push(JSON.parse(args.json)); },
  listen: async (name, fn) => listeners.set(name, fn), emitTo: async () => {},
  crypto: { randomUUID: () => `test_${++next}` }, window: { setTimeout: () => 1 }, clearTimeout() {},
  Date, Set, console, Audio: class { play() { return Promise.resolve(); } pause() {} } };
(async () => {
  await vm.runInNewContext(`(async () => { ${js} })()`, context);
  listeners.get('core-connection')({ payload: 'connected' });
  element('request').value = 'Help me open my orders';
  await element('form').onsubmit({ preventDefault() {} });
  const request = sent[0]; assert.equal(request.type, 'user_request');
  const event = (status, extra = {}, tid = request.task_id) => listeners.get('core-message')({ payload: { version:'1.0',type:'agent_event',task_id:tid,request_id:request.request_id,payload:{status,...extra} } });
  const c = {confirmation_id:'c1',call_id:'call1',action_hash:'exact_hash',action:'Open orders',consequence:'Opens a page',risk:'CONSEQUENTIAL',expires_at: Date.now()/1000+60};
  event('confirmation_required',{confirmation:c},'stale'); assert.equal(element('consent').children.length,0);
  event('confirmation_required',{confirmation:c}); assert.equal(sent.length,1,'never auto approve');
  event('debug'); assert.equal(element('consent').children.length,6,'debug must preserve pending approval');
  await element('consent').children[5].onclick();
  assert.equal(sent[1].type,'confirmation_response'); assert.deepEqual(sent[1].payload,{confirmation_id:'c1',call_id:'call1',action_hash:'exact_hash',approved:true});
  event('awaiting_input',{metadata:{reply_to:'question1'}}); element('request').value='The most recent order';
  await element('form').onsubmit({preventDefault(){}}); assert.equal(sent[2].type,'user_reply'); assert.equal(sent[2].payload.reply_to,'question1');
  await element('cancel').onclick(); assert.equal(sent[3].type,'cancel'); assert.equal(element('send').disabled,true);
  event('cancelled'); assert.equal(element('send').disabled,false);
  event('confirmation_required',{confirmation:c}); assert.equal(element('consent').children.length,0,'terminal task ignores late messages');
  const schema = JSON.parse(fs.readFileSync('../../shared/protocol.schema.json', 'utf8'));
  function check(value, shape) {
    if (shape.$ref) return check(value, schema.$defs[shape.$ref.split('/').pop()]);
    if (shape.type) assert.equal(typeof value, shape.type);
    if (shape.const !== undefined) assert.equal(value, shape.const);
    if (shape.enum) assert.ok(shape.enum.includes(value));
    if (shape.pattern) assert.match(value, new RegExp(shape.pattern));
    if (shape.minLength) assert.ok(value.length >= shape.minLength);
    if (shape.maxLength) assert.ok(value.length <= shape.maxLength);
    if (shape.required) for (const key of shape.required) assert.ok(key in value);
    if (shape.properties) for (const key of Object.keys(value)) {
      if (shape.additionalProperties === false) assert.ok(key in shape.properties);
      if (shape.properties[key]) check(value[key], shape.properties[key]);
    }
  }
  const names = {user_request:'UserRequest',confirmation_response:'ConfirmationResponse',user_reply:'UserReply',cancel:'Cancel'};
  for (const frame of sent) { check(frame, schema); check(frame.payload, schema.$defs[names[frame.type]]); assert.ok(frame.task_id); }
  if (process.argv[2]) fs.writeFileSync(process.argv[2], JSON.stringify(sent));
  console.log('PASS: request, stale events, explicit confirmation, debug, follow-up, cancel, terminal cleanup');
})().catch(e=>{ console.error(e);process.exit(1); });
