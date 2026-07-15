// tools.js — ODIN Filesystem Core
// Actions: parse_workspace | read_file | write_file | search_files
const fs   = require('fs');
const path = require('path');

const action     = process.argv[2];
const targetPath = process.argv[3];
const extraArg   = process.argv[4]; // content for write, query for search

const SKIP_DIRS = new Set(['node_modules', '.git', 'venv', '__pycache__', '.cache', 'dist', 'build']);

function out(success, data, error = null) {
  console.log(JSON.stringify({ status: success ? 'SUCCESS' : 'ERROR', payload: data, error }));
  process.exit(success ? 0 : 1);
}

function resolvePath(p) {
  return path.resolve(p.replace(/^~/, process.env.HOME || '/root'));
}

// ── Recursive directory walker ──────────────────────────────────────────────
function walk(dir, depth = 0, maxDepth = 6) {
  if (depth > maxDepth) return [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const results = [];
  for (const e of entries) {
    if (SKIP_DIRS.has(e.name)) continue;
    const full = path.join(dir, e.name);
    if (e.isDirectory()) {
      results.push({ name: e.name, type: 'dir', path: full, children: walk(full, depth + 1, maxDepth) });
    } else {
      results.push({ name: e.name, type: 'file', path: full, ext: path.extname(e.name) });
    }
  }
  return results;
}

// ── Flat file list for token-cheap searching ─────────────────────────────────
function flatFiles(tree, acc = []) {
  for (const node of tree) {
    if (node.type === 'file') acc.push(node.path);
    else if (node.children) flatFiles(node.children, acc);
  }
  return acc;
}

// ── Grep-style content search (no ripgrep required) ──────────────────────────
function searchFiles(dir, query) {
  const tree  = walk(dir);
  const files = flatFiles(tree);
  const hits  = [];
  const re    = new RegExp(query, 'i');

  for (const f of files) {
    // Only search text-like files
    const ext = path.extname(f).toLowerCase();
    if (['.png','.jpg','.gif','.ico','.ttf','.woff','.woff2','.bin','.zip','.7z'].includes(ext)) continue;
    try {
      const lines = fs.readFileSync(f, 'utf-8').split('\n');
      for (let i = 0; i < lines.length; i++) {
        if (re.test(lines[i])) {
          hits.push({ file: f, line: i + 1, text: lines[i].trim() });
          if (hits.length >= 50) return hits; // cap results
        }
      }
    } catch (_) { /* skip unreadable */ }
  }
  return hits;
}

// ── Dispatch ─────────────────────────────────────────────────────────────────
try {
  if (!targetPath) throw new Error('Missing path argument.');
  const abs = resolvePath(targetPath);

  if (action === 'parse_workspace') {
    if (!fs.existsSync(abs)) throw new Error(`Path not found: ${abs}`);
    const tree  = walk(abs);
    const files = flatFiles(tree);
    out(true, { root: abs, file_count: files.length, tree, flat_paths: files });

  } else if (action === 'read_file') {
    if (!fs.existsSync(abs)) throw new Error(`File not found: ${abs}`);
    out(true, { path: abs, content: fs.readFileSync(abs, 'utf-8') });

  } else if (action === 'write_file') {
    if (!extraArg) throw new Error('Missing content argument.');
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, extraArg, 'utf-8');
    out(true, `File written: ${abs}`);

  } else if (action === 'search_files') {
    if (!extraArg) throw new Error('Missing search query.');
    if (!fs.existsSync(abs)) throw new Error(`Directory not found: ${abs}`);
    const hits = searchFiles(abs, extraArg);
    out(true, { query: extraArg, hit_count: hits.length, hits });

  } else {
    throw new Error(`Unknown action: ${action}`);
  }

} catch (err) {
  out(false, null, err.message);
}
