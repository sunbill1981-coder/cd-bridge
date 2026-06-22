const http = require('http');
const https = require('https');
const { URL } = require('url');
const fs = require('fs');
const path = require('path');

// ── Config ──────────────────────────────────────────

let cfg = {};
try {
  const cfgPath = path.join(require('os').homedir(), '.cd-bridge', 'config.json');
  cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf-8'));
} catch {}

const PROVIDERS = cfg.providers || [];

// Local backend (oMLX)
const OMLX_HOST = process.env.OMLX_HOST || cfg.omlx_host || 'localhost';
const OMLX_PORT = parseInt(process.env.OMLX_PORT || cfg.omlx_port || '8000');
const OMLX_KEY = process.env.OMLX_KEY || cfg.omlx_key || '';

const PROXY_PORT = parseInt(process.env.PROXY_PORT || cfg.proxy_port || '3099');
let MODEL = process.env.OMLX_MODEL || cfg.omlx_model || '';

// ── Model routing helpers ───────────────────────────

function isCloudModel(name) {
  return name.includes('/') || name.startsWith('sensenova-');
}

function getProviderName(model) {
  if (model.startsWith('sensenova-')) return 'sensenova';
  const idx = model.indexOf('/');
  return idx === -1 ? '' : model.slice(0, idx);
}

function getCloudModelName(model) {
  // sensenova-deepseek-v4-flash → deepseek-v4-flash
  if (model.startsWith('sensenova-')) {
    const native = new Set(['sensenova-6.7-flash-lite', 'sensenova-u1-fast']);
    if (native.has(model)) return model;
    return model.slice(10);
  }
  const idx = model.indexOf('/');
  return idx === -1 ? model : model.slice(idx + 1);
}

function getProvider(model) {
  const name = getProviderName(model);
  return PROVIDERS.find(p => p.name === name) || null;
}

// ── HTTP helpers ──────────────────────────────────

function omlxRequest(method, path, body) {
  return new Promise((resolve, reject) => {
    const opts = {
      hostname: OMLX_HOST,
      port: OMLX_PORT,
      path,
      method,
      headers: { 'x-api-key': OMLX_KEY, 'Content-Type': 'application/json' },
    };
    const req = http.request(opts, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => resolve({ status: res.statusCode, body: data }));
    });
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

function omlxPipe(method, path, body, clientRes) {
  return new Promise((resolve, reject) => {
    const opts = {
      hostname: OMLX_HOST,
      port: OMLX_PORT,
      path,
      method,
      headers: { 'x-api-key': OMLX_KEY, 'Content-Type': 'application/json' },
    };
    const req = http.request(opts, backendRes => {
      clientRes.writeHead(backendRes.statusCode, backendRes.headers);
      backendRes.pipe(clientRes);
      backendRes.on('end', resolve);
    });
    req.on('error', e => {
      clientRes.writeHead(502);
      clientRes.end(JSON.stringify({ error: { message: e.message } }));
      reject(e);
    });
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

function parseUrl(base, relativePath) {
  const normalized = base.endsWith('/') ? base : base + '/';
  const u = new URL(relativePath, normalized);
  return { hostname: u.hostname, port: u.port || 443, pathname: u.pathname };
}

function cloudRequest(provider, method, path, body) {
  return new Promise((resolve, reject) => {
    const target = parseUrl(provider.base_url, path);
    const isHTTPS = provider.base_url.startsWith('https');
    const mod = isHTTPS ? https : http;
    const opts = {
      hostname: target.hostname,
      port: target.port,
      path: target.pathname,
      method,
      headers: {
        'Authorization': `Bearer ${provider.api_key}`,
        'Content-Type': 'application/json',
      },
    };
    const req = mod.request(opts, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => resolve({ status: res.statusCode, body: data }));
    });
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

// ── Format translators ────────────────────────────

function anthropicToOpenAI(anthropicReq) {
  const messages = [];
  if (anthropicReq.system) {
    messages.push({ role: 'system', content: anthropicReq.system });
  }
  for (const m of (anthropicReq.messages || [])) {
    let content = '';
    if (typeof m.content === 'string') {
      content = m.content;
    } else if (Array.isArray(m.content)) {
      content = m.content.map(b =>
        b.type === 'text' ? b.text : ''
      ).join('').trim();
    }
    messages.push({ role: m.role, content });
  }
  return {
    model: getCloudModelName(MODEL),
    messages,
    max_tokens: anthropicReq.max_tokens || 4096,
    temperature: anthropicReq.temperature,
    stream: false,
  };
}

function openaiToAnthropic(openaiResp, origModel) {
  const choice = (openaiResp.choices || [])[0] || {};
  const finishMap = { stop: 'end_turn', length: 'max_tokens' };
  return {
    id: openaiResp.id || `msg_${Date.now()}`,
    type: 'message',
    role: choice.message?.role || 'assistant',
    content: [{ type: 'text', text: choice.message?.content || '' }],
    model: origModel,
    stop_reason: finishMap[choice.finish_reason] || choice.finish_reason || 'end_turn',
    usage: {
      input_tokens: openaiResp.usage?.prompt_tokens || 0,
      output_tokens: openaiResp.usage?.completion_tokens || 0,
    },
  };
}

// ── Model detection ───────────────────────────────

async function autoDetectModel() {
  if (!isCloudModel(MODEL)) {
    const res = await omlxRequest('GET', '/v1/models');
    if (res.status !== 200) return null;
    try {
      const models = JSON.parse(res.body).data || [];
      const preferred = models.find(m =>
        /coder|code|qwen/i.test(m.id) && !/embed/i.test(m.id)
      );
      return preferred || models.find(m => !/embed|rerank/i.test(m.id)) || models[0];
    } catch { return null; }
  }
  return null;
}

async function ensureModel() {
  if (!MODEL) {
    const detected = await autoDetectModel();
    if (detected) {
      MODEL = detected.id;
      console.log(`  Auto-detected model: ${MODEL}`);
    }
  }
}

// ── Server ────────────────────────────────────────

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', '*');

  if (req.method === 'OPTIONS') { res.writeHead(204); return res.end(); }

  // Admin: switch model
  if (url.pathname === '/_admin/switch' && req.method === 'POST') {
    let body = '';
    req.on('data', c => body += c);
    req.on('end', () => {
      try {
        const { model } = JSON.parse(body);
        if (!model) { res.writeHead(400); return res.end('{"error":"model required"}'); }
        MODEL = model;
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'ok', model: MODEL }));
      } catch (e) {
        res.writeHead(400);
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }

  // Admin: status
  if (url.pathname === '/_admin/status') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({
      proxy: { port: PROXY_PORT, model: MODEL, backend: isCloudModel(MODEL) ? 'cloud' : 'local' },
      local: { host: OMLX_HOST, port: OMLX_PORT },
      cloud: { providers: PROVIDERS.map(p => p.name) },
    }));
  }

  // /v1/models — return Anthropic model names
  if (url.pathname === '/v1/models' && req.method === 'GET') {
    await ensureModel();
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({
      object: 'list',
      data: [
        { id: 'claude-sonnet-4-6', object: 'model', created: Date.now(), owned_by: 'anthropic' },
        { id: 'claude-opus-4-7', object: 'model', created: Date.now(), owned_by: 'anthropic' },
        { id: 'claude-haiku-4-5', object: 'model', created: Date.now(), owned_by: 'anthropic' },
      ],
    }));
  }

  // /v1/messages — proxy to backend
  if (url.pathname === '/v1/messages' && req.method === 'POST') {
    await ensureModel();
    let body = '';
    req.on('data', c => body += c);
    req.on('end', async () => {
      try {
        const upstream = JSON.parse(body);
        const origModel = upstream.model;

        if (isCloudModel(MODEL)) {
          const provider = getProvider(MODEL);
          if (!provider) {
            res.writeHead(400);
            return res.end(JSON.stringify({ error: `未知云端服务商: ${getProviderName(MODEL)}，请先用 configure 添加` }));
          }
          const openaiReq = anthropicToOpenAI(upstream);
          const result = await cloudRequest(provider, 'POST', 'chat/completions', openaiReq);
          const openaiResp = JSON.parse(result.body);
          const anthropicResp = openaiToAnthropic(openaiResp, origModel);
          res.writeHead(result.status, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify(anthropicResp));
        } else {
          upstream.model = MODEL;
          await omlxPipe('POST', '/v1/messages', upstream, res);
        }
      } catch (e) {
        res.writeHead(502);
        res.end(JSON.stringify({ error: { message: e.message } }));
      }
    });
    return;
  }

  res.writeHead(404);
  res.end('Not found');
});

server.listen(PROXY_PORT, async () => {
  await ensureModel();
  console.log(`✓ cd-bridge → http://localhost:${PROXY_PORT}`);
  if (PROVIDERS.length) {
    console.log(`  Providers: ${PROVIDERS.map(p => p.name).join(', ')}`);
  }
});
