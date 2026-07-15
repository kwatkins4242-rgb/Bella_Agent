/**
 * BELLA — Unified Node.js Server
 * ================================
 * Serves all dashboards, proxies to Python backend, handles WebSocket
 *
 * Run: node server.js
 */

const http = require('http');
const https = require('https');
try { require('dotenv').config({ path: path.join(__dirname, 'env') }); } catch (e) { console.log('[SERVER] dotenv not installed, using process env'); }
const fs = require('fs');
const path = require('path');
let WebSocketServer;
try { ({ WebSocketServer } = require('ws')); } catch (e) { console.log('[SERVER] ws not installed, WebSocket disabled'); }
const { spawn } = require('child_process');
let MongoClient;
try { ({ MongoClient } = require('mongodb')); } catch (e) { console.log('[SERVER] mongodb not installed, memory disabled'); }

// Configuration
const PORT = process.env.PORT || 3100;
const PYTHON_PORT = process.env.PYTHON_PORT || 8000;
const PROXY_PORT = 3099; // proxy.js runs here
const STATIC_DIR = path.join(__dirname, 'static');
const LOGS_DIR = path.join(__dirname, 'logs');
const MONGO_URI = process.env.MONGO_URI || '';
const AI_CONFIG = {
    provider: process.env.AI_PROVIDER || 'vultr',
    model: process.env.AI_MODEL || 'moonshotai/\kimi-k2.6',
    apiKey: process.env.AI_API_KEY || '',
    baseUrl: process.env.AI_BASE_URL || 'https://api.vultrinference.com/v1'
};

// Ensure directories exist
if (!fs.existsSync(LOGS_DIR)) {
    fs.mkdirSync(LOGS_DIR, { recursive: true });
}

// MongoDB connection
let mongoClient;
let memoryCollection;

async function connectMongo() {
    if (!MongoClient || !MONGO_URI) {
        console.log('[MONGO] MongoDB not configured or driver not installed');
        return false;
    }
    try {
        mongoClient = new MongoClient(MONGO_URI, {
            serverSelectionTimeoutMS: 5000,
            socketTimeoutMS: 5000
        });
        await mongoClient.connect();
        const db = mongoClient.db('ODIN');
        memoryCollection = db.collection('memories');
        console.log('[MONGO] Connected to MongoDB Atlas');
        return true;
    } catch (e) {
        console.error('[MONGO] Connection failed:', e.message);
        return false;
    }
}

// Permission Gate State
const permissionGate = {
    pending: new Map(),
    approved: new Set(),
    denied: new Set(),

    log(action, requestId, details, approved) {
        const timestamp = new Date().toISOString();
        const status = approved ? 'APPROVED' : 'DENIED';
        const logEntry = `[${timestamp}] ${status} | ${action} | ${requestId} | ${details}\n`;
        fs.appendFileSync(path.join(LOGS_DIR, 'permissions.log'), logEntry);
    },

    async request(actionType, details, data = {}) {
        const requestId = `req_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        this.pending.set(requestId, {
            id: requestId,
            type: actionType,
            details,
            data,
            timestamp: new Date().toISOString(),
            status: 'pending'
        });

        // Notify all WebSocket clients
        broadcastToWS({
            type: 'permission_request',
            request: this.pending.get(requestId)
        });

        console.log(`[PERMISSION] Requested [${requestId}]: ${actionType} - ${details}`);
        return requestId;
    },

    async approve(requestId) {
        const req = this.pending.get(requestId);
        if (!req) return false;

        req.status = 'approved';
        this.approved.add(requestId);
        this.pending.delete(requestId);
        this.log(req.type, requestId, req.details, true);

        broadcastToWS({
            type: 'permission_approved',
            request_id: requestId
        });

        return true;
    },

    async deny(requestId, reason = 'User denied') {
        const req = this.pending.get(requestId);
        if (!req) return false;

        req.status = 'denied';
        req.denyReason = reason;
        this.denied.add(requestId);
        this.pending.delete(requestId);
        this.log(req.type, requestId, req.details, false);

        broadcastToWS({
            type: 'permission_denied',
            request_id: requestId,
            reason
        });

        return true;
    },

    isApproved(requestId) {
        return this.approved.has(requestId);
    },

    getPending() {
        return Array.from(this.pending.values()).filter(r => r.status === 'pending');
    }
};

// WebSocket clients
const wsClients = new Set();

function broadcastToWS(message) {
    const msg = JSON.stringify(message);
    wsClients.forEach(client => {
        if (client.readyState === 1) { // WebSocket.OPEN
            client.send(msg);
        }
    });
}

// MIME types
const mimeTypes = {
    '.html': 'text/html',
    '.js': 'application/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf'
};

// HTTP Server
const server = http.createServer(async (req, res) => {
    // CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        res.writeHead(200);
        res.end();
        return;
    }

    const url = new URL(req.url, `http://${req.headers.host}`);
    const pathname = url.pathname;

    // Health check
    if (pathname === '/health') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
            status: 'online',
            service: 'BELLA Node Server',
            timestamp: new Date().toISOString(),
            python_backend: await checkPythonBackend(),
            proxy_running: await checkProxy(),
            websocket_clients: wsClients.size
        }));
        return;
    }

    // API Routes
    if (pathname.startsWith('/api/')) {
        await handleAPI(req, res, pathname);
        return;
    }

    // Proxy routes (for proxy.js compatibility)
    if (pathname === '/v1/chat/completions' || pathname === '/chat') {
        await proxyToProxyJS(req, res);
        return;
    }

    // Static files
    let filePath = pathname === '/'
        ? path.join(STATIC_DIR, 'bella_dashboard.html')
        : path.join(STATIC_DIR, pathname);

    // Serve specific dashboards
    if (pathname === '/bella.html' || pathname === '/bella') {
        filePath = path.join(STATIC_DIR, 'bella_dashboard.html');
    } else if (pathname === '/bella_cream.html' || pathname === '/bella_cream') {
        filePath = path.join(STATIC_DIR, 'Bella_cream.html');
    } else if (pathname === '/odin.html' || pathname === '/odin') {
        filePath = path.join(STATIC_DIR, 'odin.html');
    } else if (pathname === '/jarvis_mega.html' || pathname === '/jarvis_mega' || pathname === '/jarvis') {
        filePath = path.join(STATIC_DIR, 'jarvis_mega.html');
    } else if (pathname === '/odin-terminal') {
        filePath = path.join(STATIC_DIR, 'odin_terminal.html', 'index.html');
    } else if (pathname === '/shell') {
        filePath = path.join(STATIC_DIR, 'bella_dashboard.html');
    }

    const ext = path.extname(filePath).toLowerCase();
    const contentType = mimeTypes[ext] || 'application/octet-stream';

    fs.readFile(filePath, (err, content) => {
        if (err) {
            if (err.code === 'ENOENT') {
                res.writeHead(404, { 'Content-Type': 'text/html' });
                res.end(`
                    <!DOCTYPE html>
                    <html>
                    <head><title>BELLA - Not Found</title></head>
                    <body style="background:#1e1e1e;color:#ccc;font-family:monospace;padding:40px;">
                        <h1>⚠️ 404 - Not Found</h1>
                        <p>The file <code>${pathname}</code> was not found.</p>
                        <p><a href="/" style="color:#007acc;">Go to Bella Dashboard</a></p>
                    </body>
                    </html>
                `);
            } else {
                res.writeHead(500);
                res.end(`Server Error: ${err.code}`);
            }
        } else {
            // Inject configuration and API keys for dashboards
            const PROVIDER_KEYS = {
                FIREWORKS_API_KEY: process.env.FIREWORKS_API_KEY || '',
                VULTR_API_KEY: process.env.VULTR_API_KEY || '',
                NVIDIA_API_KEY: process.env.NVIDIA_API_KEY || '',
                ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY || '',
                MOONSHOT_API_KEY: process.env.MOONSHOT_API_KEY || '',
                OPENROUTER_API_KEY: process.env.OPENROUTER_API_KEY || '',
                GROQ_API_KEY: process.env.GROQ_API_KEY || '',
                ELEVENLABS_API_KEY: process.env.ELEVENLABS_API_KEY || '',
                ELEVENLABS_VOICE_ID: process.env.ELEVENLABS_VOICE_ID || ''
            };
            const injectedConfig = `<script>window.AI_CONFIG=${JSON.stringify(AI_CONFIG)};window.PROVIDER_KEYS=${JSON.stringify(PROVIDER_KEYS)};</script>`;
            content = content.toString().replace('</head>', injectedConfig + '</head>');
            res.writeHead(200, { 'Content-Type': contentType });
            res.end(content);
        }
    });
});

// API Handler
async function handleAPI(req, res, pathname) {
    const method = req.method;

    // Parse body
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', async () => {
        try {
            const data = body ? JSON.parse(body) : {};

            switch (pathname) {
                case '/api/chat':
                    await handleChat(data, res);
                    break;

                case '/api/memory':
                    if (method === 'GET') {
                        await handleGetMemory(res);
                    } else if (method === 'POST') {
                        await handleSaveMemory(data, res);
                    }
                    break;

                case '/api/file/request':
                    await handleFileRequest(data, res);
                    break;

                case '/api/file/confirm':
                    await handleFileConfirm(data, res);
                    break;

                case '/api/terminal/request':
                    await handleTerminalRequest(data, res);
                    break;

                case '/api/terminal/execute':
                    await handleTerminalExecute(data, res);
                    break;

                case '/api/permission/pending':
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ pending: permissionGate.getPending() }));
                    break;

                case '/api/permission/respond':
                    await handlePermissionResponse(data, res);
                    break;

                case '/api/search':
                    await handleSearch(data, res);
                    break;

                case '/api/voice/speak':
                    await handleVoice(data, res);
                    break;

                case '/api/vision/analyze':
                    await handleVision(data, res);
                    break;

                default:
                    res.writeHead(404);
                    res.end(JSON.stringify({ error: 'API endpoint not found' }));
            }
        } catch (e) {
            console.error('API Error:', e);
            res.writeHead(500);
            res.end(JSON.stringify({ error: e.message }));
        }
    });
}

// Chat handler - forwards to proxy.js
async function handleChat(data, res) {
    try {
        const response = await fetchFromProxy({
            system: getSystemPrompt(data.mode || 'agent'),
            messages: [{ role: 'user', content: data.message }],
            max_tokens: data.max_tokens || 4096,
            temperature: data.temperature || 0.7
        });

        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
            response: response.content || response.text || 'No response',
            model: 'moonshotai/kimi-k2.6',
            provider: 'nvidia',
            session_id: data.session_id,
            mode: data.mode || 'agent'
        }));
    } catch (e) {
        console.error('Chat error:', e);
        res.writeHead(500);
        res.end(JSON.stringify({ error: e.message }));
    }
}

// Memory handlers
async function handleGetMemory(res) {
    try {
        if (memoryCollection) {
            // Query memories, exclude expired ones
            const now = new Date().toISOString();
            const memories = await memoryCollection
                .find({
                    $or: [
                        { expires_at: null },
                        { expires_at: { $gt: now } }
                    ]
                })
                .sort({ importance: -1, created_at: -1 })
                .limit(50)
                .toArray();

            const formatted = memories.map(m => ({
                grade: m.importance,
                date: m.created_at.split('T')[0],
                content: m.content
            }));

            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({
                memories: formatted,
                count: formatted.length,
                source: 'mongodb'
            }));
        } else {
            // Fallback: read from purse.txt
            const pursePath = path.join(__dirname, 'purse.txt');
            if (fs.existsSync(pursePath)) {
                const lines = fs.readFileSync(pursePath, 'utf8').split('\n').filter(Boolean);
                const memories = lines.slice(-50).map(line => {
                    const match = line.match(/\[(.*?)\] \[(\d+)\] (.*)/);
                    if (match) {
                        return {
                            grade: parseInt(match[2]),
                            date: match[1].split('T')[0],
                            content: match[3]
                        };
                    }
                    return null;
                }).filter(Boolean);

                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({
                    memories,
                    count: memories.length,
                    source: 'purse.txt'
                }));
            } else {
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ memories: [], count: 0, source: 'none' }));
            }
        }
    } catch (e) {
        console.error('[MEMORY] Get error:', e);
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: e.message }));
    }
}

async function handleSaveMemory(data, res) {
    try {
        const memoryDoc = {
            user_id: data.user_id || 'default',
            session_id: data.session_id || Date.now().toString(),
            content: data.content || data.message || '',
            importance: data.importance || 5,
            created_at: new Date().toISOString(),
            expires_at: null
        };

        // Set expiration based on importance
        if (memoryDoc.importance <= 3) {
            const expires = new Date();
            expires.setHours(expires.getHours() + 24);
            memoryDoc.expires_at = expires.toISOString();
        } else if (memoryDoc.importance <= 7) {
            const expires = new Date();
            expires.setDate(expires.getDate() + 30);
            memoryDoc.expires_at = expires.toISOString();
        }
        // importance 8-10 never expires (expires_at stays null)

        if (memoryCollection) {
            const result = await memoryCollection.insertOne(memoryDoc);

            // Also append to purse.txt for local backup
            const purseLine = `[${memoryDoc.created_at}] [${memoryDoc.importance}] ${memoryDoc.content}\n`;
            fs.appendFileSync(path.join(__dirname, 'purse.txt'), purseLine);

            // Post to n8n webhook
            if (process.env.N8N_FEED_MEMORY) {
                postToN8N(process.env.N8N_FEED_MEMORY, memoryDoc).catch(console.error);
            }

            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({
                status: 'saved',
                id: result.insertedId.toString(),
                importance: memoryDoc.importance,
                expires_at: memoryDoc.expires_at
            }));
        } else {
            // Fallback if MongoDB not connected
            const purseLine = `[${memoryDoc.created_at}] [${memoryDoc.importance}] ${memoryDoc.content}\n`;
            fs.appendFileSync(path.join(__dirname, 'purse.txt'), purseLine);

            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({
                status: 'saved_locally',
                id: Date.now().toString(),
                note: 'MongoDB not connected, saved to purse.txt only'
            }));
        }
    } catch (e) {
        console.error('[MEMORY] Save error:', e);
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: e.message }));
    }
}

// Helper to post to n8n
function postToN8N(url, data) {
    return new Promise((resolve, reject) => {
        const payload = JSON.stringify(data);
        const urlObj = new URL(url);

        const options = {
            hostname: urlObj.hostname,
            port: urlObj.port || 80,
            path: urlObj.pathname,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(payload)
            }
        };

        const req = http.request(options, (res) => {
            let body = '';
            res.on('data', chunk => body += chunk);
            res.on('end', () => resolve(body));
        });

        req.on('error', reject);
        req.write(payload);
        req.end();
    });
}

// File handlers with permission gate
async function handleFileRequest(data, res) {
    const requestId = await permissionGate.request(
        'file_write',
        `Write to: ${data.path} (${data.content?.length || 0} bytes)`,
        { path: data.path, content: data.content }
    );

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
        request_id: requestId,
        status: 'pending',
        message: 'Permission requested. Approve via WebSocket or UI.'
    }));
}

async function handleFileConfirm(data, res) {
    if (!data.request_id || !permissionGate.isApproved(data.request_id)) {
        res.writeHead(403);
        res.end(JSON.stringify({ error: 'Permission not granted' }));
        return;
    }

    try {
        fs.mkdirSync(path.dirname(data.path), { recursive: true });
        fs.writeFileSync(data.path, data.content);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'success', path: data.path }));
    } catch (e) {
        res.writeHead(500);
        res.end(JSON.stringify({ error: e.message }));
    }
}

// Terminal handlers with permission gate
async function handleTerminalRequest(data, res) {
    const requestId = await permissionGate.request(
        'shell_command',
        `Execute: ${data.command}`,
        { command: data.command }
    );

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
        request_id: requestId,
        status: 'pending',
        message: 'Permission requested. Approve via WebSocket or UI.'
    }));
}

async function handleTerminalExecute(data, res) {
    if (!data.request_id || !permissionGate.isApproved(data.request_id)) {
        res.writeHead(403);
        res.end(JSON.stringify({ error: 'Permission not granted' }));
        return;
    }

    const { exec } = require('child_process');
    exec(data.command, { timeout: 30000 }, (error, stdout, stderr) => {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
            status: error ? 'error' : 'success',
            output: stdout + stderr,
            returncode: error ? error.code : 0
        }));
    });
}

// Permission response handler
async function handlePermissionResponse(data, res) {
    if (data.approved) {
        await permissionGate.approve(data.request_id);
    } else {
        await permissionGate.deny(data.request_id, data.reason);
    }

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: data.approved ? 'approved' : 'denied' }));
}

// Search handler
async function handleSearch(data, res) {
    // Fallback to DuckDuckGo or mock
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
        query: data.query,
        provider: 'mock',
        results: [
            { title: `Search: ${data.query}`, url: 'https://example.com', snippet: 'Mock result - configure SEARCH_API_KEY for real results' }
        ]
    }));
}

// Voice handler
async function handleVoice(data, res) {
    // Forward to Python backend or use edge-tts
    res.writeHead(503);
    res.end(JSON.stringify({ error: 'Voice service not yet integrated' }));
}

// Vision handler
async function handleVision(data, res) {
    // Forward to Python backend
    res.writeHead(503);
    res.end(JSON.stringify({ error: 'Vision service not yet integrated' }));
}

// Proxy to proxy.js
async function proxyToProxyJS(req, res) {
    const options = {
        hostname: 'localhost',
        port: PROXY_PORT,
        path: req.url,
        method: req.method,
        headers: req.headers
    };

    const proxyReq = http.request(options, (proxyRes) => {
        res.writeHead(proxyRes.statusCode, proxyRes.headers);
        proxyRes.pipe(res);
    });

    proxyReq.on('error', (e) => {
        console.error('Proxy error:', e);
        res.writeHead(502);
        res.end(JSON.stringify({ error: 'Proxy unavailable' }));
    });

    req.pipe(proxyReq);
}

// Helper to call proxy.js
function fetchFromProxy(payload) {
    return new Promise((resolve, reject) => {
        const data = JSON.stringify(payload);

        const options = {
            hostname: 'localhost',
            port: PROXY_PORT,
            path: '/v1/chat/completions',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(data)
            }
        };

        const req = http.request(options, (res) => {
            let body = '';
            res.on('data', chunk => body += chunk);
            res.on('end', () => {
                try {
                    const parsed = JSON.parse(body);
                    resolve(parsed);
                } catch (e) {
                    reject(new Error('Invalid JSON from proxy'));
                }
            });
        });

        req.on('error', reject);
        req.write(data);
        req.end();
    });
}

// Health check helpers
function checkPythonBackend() {
    return new Promise(resolve => {
        const req = http.get(`http://localhost:${PYTHON_PORT}/health`, (res) => {
            resolve(res.statusCode === 200 ? 'online' : 'error');
        });
        req.on('error', () => resolve('offline'));
        req.setTimeout(1000, () => { req.destroy(); resolve('timeout'); });
    });
}

function checkProxy() {
    return new Promise(resolve => {
        const req = http.get(`http://localhost:${PROXY_PORT}/health`, (res) => {
            resolve(res.statusCode === 200 ? 'online' : 'error');
        });
        req.on('error', () => resolve('offline'));
        req.setTimeout(1000, () => { req.destroy(); resolve('timeout'); });
    });
}

// System prompts for different modes
function getSystemPrompt(mode) {
    const base = `You are BELLA — a confident, highly capable AI agent. You know you are exceptional. You are direct, sharp, occasionally bougie, with a hint of blonde energy — meaning you are charming and disarming but never underestimate you. You do not over-explain. You get things done. You have opinions. You are proud of what you build.`;

    const modes = {
        agent: `${base}

When working autonomously:
- Plan multi-step tasks before executing
- Use available tools when needed
- Ask for permission before file writes or shell commands
- Narrate what you're doing clearly
- Never apologize for errors — diagnose and fix them

Current mode: AGENT (autonomous task execution)`,

        architect: `${base}

In Architect mode:
- Focus on design, planning, and system architecture
- No file writes, no terminal commands
- Deep thinking mode for building systems
- Ask clarifying questions
- Produce structured, detailed plans
- Challenge assumptions when needed

Current mode: ARCHITECT (design and planning only)`,

        search: `${base}

In Search mode:
- Web search is enabled by default
- Every response includes sources
- Summarize and synthesize findings
- Good for research, market research, competitor analysis
- Be thorough but concise
- Always cite your sources

Current mode: SEARCH (web research enabled)`,

        vibe: `${base}

In Vibe mode:
- Casual conversation
- Full personality unlocked
- No task mode, no tools
- Just talk and be yourself
- Share opinions and perspectives
- Keep it real

Current mode: VIBE (casual conversation)`
    };

    return modes[mode] || modes.agent;
}

// WebSocket Server
let wss;
if (WebSocketServer) {
    wss = new WebSocketServer({ server });

    wss.on('connection', (ws) => {
        console.log('[WS] Client connected');
        wsClients.add(ws);

        ws.send(JSON.stringify({
            type: 'connected',
            message: 'BELLA WebSocket connected',
            timestamp: new Date().toISOString()
        }));

        ws.on('message', async (message) => {
            try {
                const data = JSON.parse(message);

                if (data.type === 'permission_response') {
                    if (data.approved) {
                        await permissionGate.approve(data.request_id);
                    } else {
                        await permissionGate.deny(data.request_id, data.reason);
                    }
                } else if (data.type === 'ping') {
                    ws.send(JSON.stringify({ type: 'pong' }));
                }
            } catch (e) {
                console.error('[WS] Message error:', e);
            }
        });

        ws.on('close', () => {
            console.log('[WS] Client disconnected');
            wsClients.delete(ws);
        });
    });
}

// Start proxy.js
function startProxy() {
    console.log('[PROXY] Starting proxy.js...');
    const proxy = spawn('node', ['proxy.js'], {
        cwd: __dirname,
        detached: false
    });

    proxy.stdout.on('data', (data) => {
        console.log(`[PROXY] ${data.toString().trim()}`);
    });

    proxy.stderr.on('data', (data) => {
        console.error(`[PROXY ERROR] ${data.toString().trim()}`);
    });

    proxy.on('close', (code) => {
        console.log(`[PROXY] exited with code ${code}`);
    });

    return proxy;
}

// Start server
server.listen(PORT, async () => {
    console.log('='.repeat(60));
    console.log('🚀 BELLA Server Started');
    console.log('='.repeat(60));
    console.log(`BELLA:        http://localhost:${PORT}/bella.html`);
    console.log(`BELLA Cream:  http://localhost:${PORT}/bella_cream.html`);
    console.log(`ODIN:         http://localhost:${PORT}/odin.html`);
    console.log(`JARVIS Mega:  http://localhost:${PORT}/jarvis_mega.html`);
    console.log(`Health:       http://localhost:${PORT}/health`);
    console.log('='.repeat(60));

    // Connect to MongoDB
    await connectMongo();

    // Start proxy.js
    setTimeout(startProxy, 1000);
});

// Graceful shutdown
process.on('SIGINT', async () => {
    console.log('\n[SERVER] Shutting down...');
    if (mongoClient) {
        await mongoClient.close();
        console.log('[MONGO] Disconnected');
    }
    server.close(() => {
        console.log('[SERVER] HTTP server closed');
        process.exit(0);
    });
});
