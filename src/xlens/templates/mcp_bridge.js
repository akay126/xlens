// MCP Apps bridge for the inline Xlens map: JSON-RPC 2.0 over window.parent.postMessage.
//
// Spec: https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx
// Types: https://github.com/modelcontextprotocol/ext-apps/blob/main/src/spec.types.ts
// Shapes used here, quoted from the spec (View = this page, Host = the chat client):
//
//   View -> Host request  "ui/initialize"
//     params: { appInfo: Implementation, appCapabilities: McpUiAppCapabilities, protocolVersion: string }
//     result (McpUiInitializeResult): { protocolVersion, hostInfo, hostCapabilities, hostContext, ... }
//   View -> Host notification "ui/notifications/initialized"   params?: {}
//     ("The Host MUST NOT send any request or notification to the View before it receives an
//      initialized notification.")
//   Host -> View notification "ui/notifications/tool-input"     params: { arguments?: Record<string, unknown> }
//   Host -> View notification "ui/notifications/tool-result"    params: CallToolResult
//     i.e. { content: ContentBlock[], structuredContent?: {...}, _meta?: {...}, isError?: boolean }
//     "structuredContent: Structured data optimized for UI rendering (not added to model context)"
//     "_meta: Additional metadata ... not intended for model context"
//   View -> Host request  "ui/message"
//     spec.types.ts: params: { role: "user", content: ContentBlock[] }
//     (apps.mdx's example shows `content: { type: "text", text }` as a single object; the generated
//      schema in spec.types.ts is an array, which is what host validators use, so we send an array.)
//   View -> Host request  "tools/call"  params: { name, arguments }  -> result: CallToolResult
//   View -> Host notification "ui/notifications/size-changed"  params: { width: number, height: number }
//   Host -> View request  "ping" -> {} ;  "ui/resource-teardown" params: { reason } -> {}
//
// Payload delivery (design choice): the full map payload never goes into model-visible text.
// analyze_model returns overview + viewer_url as `content` text and `structuredContent`, and the map
// payload in the result's `_meta["xlens/payload"]`. Per the spec, tool-result params are the whole
// CallToolResult, so `_meta` reaches this View. If a host strips `_meta`, the bridge falls back once to
// `tools/call analyze_model` with the path from tool-input and reads `_meta` from that response; if that
// fails too, the page shows "Map data unavailable" instead of staying blank.
(function () {
  'use strict';
  if (!window.parent || window.parent === window) return;  // opened top-level: no host, no bridge
  var PROTOCOL = '2026-01-26', PAYLOAD_KEY = 'xlens/payload';
  var nextId = 1, pending = {}, resultCbs = [], toolArgs = null, refetched = false;

  function send(msg) { window.parent.postMessage(msg, '*'); }
  function notify(method, params) { send({ jsonrpc: '2.0', method: method, params: params || {} }); }
  function request(method, params) {
    var id = nextId++;
    send({ jsonrpc: '2.0', id: id, method: method, params: params || {} });
    return new Promise(function (res, rej) { pending[id] = { res: res, rej: rej }; });
  }
  function reply(id, result) { send({ jsonrpc: '2.0', id: id, result: result || {} }); }

  function parseText(content) {
    if (!content || !content.length || content[0].type !== 'text') return null;
    try { return JSON.parse(content[0].text); } catch (x) { return null; }
  }
  var UNAVAILABLE = 'Map data unavailable \u2014 run analyze_model again.';
  function emit(out) {
    resultCbs.forEach(function (cb) { try { cb(out); } catch (x) { /* a bad callback must not stop others */ } });
  }
  function unavailable() { emit({ result: null, payload: null, error: UNAVAILABLE }); }
  function handleResult(p) {
    if (!p || p.isError) return;
    var result = p.structuredContent || parseText(p.content);
    var payload = p._meta && p._meta[PAYLOAD_KEY];
    if (!payload && result && result.mode === 'overview') {  // a map result without its map data
      if (toolArgs && toolArgs.path && !refetched) {
        refetched = true;  // host dropped _meta: ask once for the same result through the host
        request('tools/call', { name: 'analyze_model', arguments: { path: toolArgs.path } })
          .then(function (r) {
            if (r && !r.isError && r._meta && r._meta[PAYLOAD_KEY]) handleResult(r); else unavailable();
          }, unavailable);
      } else {
        unavailable();  // shown only if no map is on screen yet
      }
    }
    emit({ result: result, payload: payload || null });
  }

  window.addEventListener('message', function (e) {
    if (e.source !== window.parent) return;
    var m = e.data;
    if (!m || typeof m !== 'object' || m.jsonrpc !== '2.0') return;
    if (!m.method && m.id != null) {  // a response to one of our requests
      var w = pending[m.id];
      if (w) { delete pending[m.id]; if (m.error) w.rej(m.error); else w.res(m.result); }
      return;
    }
    switch (m.method) {
      case 'ui/notifications/tool-input': toolArgs = (m.params && m.params.arguments) || null; break;
      case 'ui/notifications/tool-result': handleResult(m.params); break;
      case 'ping': case 'ui/resource-teardown': if (m.id != null) reply(m.id, {}); break;
      default: if (m.id != null) send({ jsonrpc: '2.0', id: m.id, error: { code: -32601, message: 'Method not found' } });
    }
  });

  function reportSize() {  // body, not documentElement: the root is never smaller than the frame, so it could not shrink
    var r = document.body.getBoundingClientRect();
    notify('ui/notifications/size-changed', { width: Math.ceil(r.width), height: Math.ceil(r.height) });
  }

  request('ui/initialize', {
    appInfo: { name: 'xlens-map', version: '1' },
    appCapabilities: { availableDisplayModes: ['inline'] },
    protocolVersion: PROTOCOL
  }).then(function () {
    notify('ui/notifications/initialized', {});
    if (window.ResizeObserver) new ResizeObserver(reportSize).observe(document.body);
    else reportSize();
  }, function () {});

  window.XlensBridge = {
    onResult: function (cb) { resultCbs.push(cb); },
    ask: function (text) {
      return request('ui/message', { role: 'user', content: [{ type: 'text', text: String(text) }] })
        .catch(function () { return null; });  // a host may deny or not support ui/message
    }
  };
})();
