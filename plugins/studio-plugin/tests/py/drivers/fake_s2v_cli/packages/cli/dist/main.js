#!/usr/bin/env node
// A fake script2video CLI for Studio's tests (m1-plan §4.3, D-M1-8). No dependencies, no servers, no models.
// machine.json points at tests/py/drivers/fake_s2v_cli (this file is its packages/cli/dist/main.js).
//
// It keeps s2v's contract as Studio reads it: stdout is JSON only, every line for people (`→ …`, `busy (…)`,
// `ok:` / `CHECK FAILED:`, lint diagnostics) goes to stderr; an unknown flag or output exits 2 with no JSON; every
// JSON answer carries one key Studio does not know (`fake_unknown`). The scenario comes from the file named by
// STUDIO_TEST_FAKE_S2V_SCENARIO (JSON, see SCENARIO below); each call is appended to `calls.log` beside it.
// What inspect hashes for each kind of edit follows fake_inspect_table.json (written by hand in M1b; M1j makes it
// from real s2v, m1-plan §12.3).
'use strict';
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const FAKE_ROOT = path.resolve(__dirname, '..', '..', '..');
const TABLE = JSON.parse(fs.readFileSync(path.join(FAKE_ROOT, 'fake_inspect_table.json'), 'utf8'));
const SCENARIO_FILE = process.env.STUDIO_TEST_FAKE_S2V_SCENARIO || '';
const SCENARIO = (() => {
  if (!SCENARIO_FILE) return {};
  try {
    return JSON.parse(fs.readFileSync(SCENARIO_FILE, 'utf8'));
  } catch {
    return {};
  }
})();
const UNKNOWN = { fake_unknown: { note: 'a key Studio must ignore' } };

// ---------- small helpers ----------
function canon(v) {
  if (Array.isArray(v)) return v.map(canon);
  if (v && typeof v === 'object') {
    const o = {};
    for (const k of Object.keys(v).sort()) o[k] = canon(v[k]);
    return o;
  }
  return v;
}
const sha256 = (data) => crypto.createHash('sha256').update(data).digest('hex');
const hashOf = (v) => sha256(JSON.stringify(canon(v)));
const out = (v) => process.stdout.write(`${JSON.stringify({ ...v, ...UNKNOWN }, null, 2)}\n`);
const err = (m) => process.stderr.write(`${m}\n`);
const fileSha = (p) => {
  try {
    return fs.statSync(p).isFile() ? sha256(fs.readFileSync(p)) : null;
  } catch {
    return null;
  }
};

function logCall(argv) {
  if (!SCENARIO_FILE) return;
  const log = SCENARIO.log || path.join(path.dirname(SCENARIO_FILE), 'calls.log');
  fs.appendFileSync(
    log,
    `${JSON.stringify({
      argv,
      heavy_token: !!process.env.S2V_HEAVY_LOCK_TOKEN,
      no_open: process.env.S2V_NO_OPEN ?? null,
      cwd: process.cwd(),
    })}\n`,
  );
}

class UsageError extends Error {}

// ---------- flags (each command takes only its own, as s2v does) ----------
const FLAGS = {
  lint: {},
  check: {},
  doctor: {},
  sentences: { json: 'bool' },
  inspect: { json: 'bool', 'hash-version': 'value' },
  tts: { retry: 'multi', 'no-asr': 'bool', recheck: 'bool' },
  snapshot: { output: 'value', 'frozen-audio': 'bool', frames: 'bool', 'out-dir': 'value', draft: 'bool', fps: 'value' },
  render: {
    output: 'value',
    'frozen-audio': 'bool',
    'out-dir': 'value',
    watermark: 'value',
    draft: 'bool',
    fps: 'value',
    'no-cache': 'bool',
    workers: 'value',
  },
  'services status': { json: 'bool' },
};

function parseFlags(key, args) {
  const spec = FLAGS[key];
  const values = {};
  const positionals = [];
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a.startsWith('--')) {
      const [name, inline] = a.slice(2).split(/=(.*)/s);
      const kind = spec[name];
      if (!kind) throw new UsageError(`s2v ${key}: unknown flag --${name}`);
      if (kind === 'bool') {
        if (inline !== undefined) throw new UsageError(`--${name} takes no value`);
        values[name] = true;
      } else {
        const v = inline !== undefined ? inline : args[++i];
        if (v === undefined) throw new UsageError(`--${name} needs a value`);
        if (kind === 'multi') (values[name] = values[name] || []).push(v);
        else values[name] = v;
      }
    } else positionals.push(a);
  }
  return { values, positionals };
}

// ---------- the script ----------
function splitInline(text) {
  // "{ voice: "qwen:Sohee", style: "a, b" }" -> {voice, style}
  const t = text.trim().replace(/^\{/, '').replace(/\}$/, '');
  const o = {};
  let depth = 0;
  let quote = null;
  let cur = '';
  const parts = [];
  for (const ch of t) {
    if (quote) {
      cur += ch;
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    if (ch === '{' || ch === '[') depth++;
    if (ch === '}' || ch === ']') depth--;
    if (ch === ',' && depth === 0) {
      parts.push(cur);
      cur = '';
    } else cur += ch;
  }
  if (cur.trim()) parts.push(cur);
  for (const p of parts) {
    const m = /^\s*([\w-]+)\s*:\s*(.*)$/s.exec(p);
    if (m) o[m[1]] = scalar(m[2]);
  }
  return o;
}

function scalar(v) {
  const t = v.trim();
  if (/^".*"$/s.test(t) || /^'.*'$/s.test(t)) return t.slice(1, -1);
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  if (t === 'true' || t === 'false') return t === 'true';
  if (t.startsWith('{')) return splitInline(t);
  return t;
}

function parseScript(file) {
  const text = fs.readFileSync(file, 'utf8');
  const lines = text.split(/\r?\n/);
  const fm = {};
  const fmLine = {};
  let i = 0;
  if (lines[0] === '---') {
    let key = null;
    for (i = 1; i < lines.length && lines[i] !== '---'; i++) {
      const line = lines[i];
      const top = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line);
      if (top) {
        key = top[1];
        fmLine[key] = i + 1;
        fm[key] = top[2].trim() ? scalar(top[2]) : {};
        continue;
      }
      const child = /^\s+([^\s:][^:]*?):\s*(.*)$/.exec(line);
      if (key && child && typeof fm[key] === 'object') fm[key][child[1].trim()] = scalar(child[2]);
    }
    i++;
  }
  const scenes = [];
  let scene = null;
  const ensure = () => {
    if (!scene) {
      scene = { id: `scene-${scenes.length + 1}`, title: '', line: i + 1, blocks: [] };
      scenes.push(scene);
    }
  };
  const casts = Object.keys(typeof fm.cast === 'object' ? fm.cast : {});
  let para = null;
  const images = [];
  const flush = () => {
    if (para) {
      scene.blocks.push(para);
      para = null;
    }
  };
  for (; i < lines.length; i++) {
    const line = lines[i];
    const h = /^# (.*?)(?:\s*\{#([\w-]+)\})?\s*$/.exec(line);
    if (h) {
      flush();
      scene = { id: h[2] || `scene-${scenes.length + 1}`, title: h[1].trim(), line: i + 1, blocks: [] };
      scenes.push(scene);
      continue;
    }
    const open = /^:::(\w+)(\{.*\})?\s*$/.exec(line);
    if (open) {
      flush();
      ensure();
      const body = [];
      const start = i + 1;
      for (i++; i < lines.length && !/^:::\s*$/.test(lines[i]); i++) body.push(lines[i]);
      scene.blocks.push({ kind: 'screen', type: open[1], text: body.join('\n').trim(), line: start });
      continue;
    }
    const leaf = /^::(\w+)(\{.*\})?\s*$/.exec(line);
    if (leaf) {
      flush();
      ensure();
      const src = /src="([^"]+)"/.exec(leaf[2] || '');
      // s2v's file kinds (inspect.ts): a video block, the thumbnail, else a picture
      const kind = leaf[1] === 'video' ? 'video' : leaf[1] === 'thumbnail' ? 'thumbnail' : 'image';
      if (src) images.push({ src: src[1], line: i + 1, kind });
      scene.blocks.push({ kind: 'leaf', type: leaf[1], attrs: leaf[2] || '', line: i + 1 });
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    for (const m of line.matchAll(/!\[[^\]]*\]\(([^)\s]+)/g)) images.push({ src: m[1], line: i + 1 });
    if (/^\s*!\[[^\]]*\]\([^)]*\)\s*$/.test(line)) {
      flush();
      ensure();
      scene.blocks.push({ kind: 'image', line: i + 1 });
      continue;
    }
    ensure();
    const sp = /^([a-z][\w-]*)(\{[^}]*\})?:\s+(.*)$/.exec(line);
    if (sp) {
      flush();
      para = { kind: 'paragraph', cast: sp[1], text: sp[3], line: i + 1, recorded: false };
    } else if (para) para.text += ` ${line.trim()}`;
    else para = { kind: 'paragraph', cast: casts[0] || 'narrator', text: line.trim(), line: i + 1, recorded: false };
    if (/:audio\{[^}]*src=/.test(line)) para.recorded = true;
  }
  flush();
  return { file, text, fm, fmLine, scenes, images, casts };
}

const plain = (t) =>
  t
    .replace(/:\w+\{[^}]*\}/g, '')
    .replace(/\s+/g, ' ')
    .trim();

function sentencesOf(script) {
  const out = [];
  for (const s of script.scenes)
    s.blocks.forEach((b, bi) => {
      if (b.kind !== 'paragraph') return;
      plain(b.text)
        .split(/(?<=[.!?。？！])\s+/)
        .filter((x) => x)
        .forEach((t, si) => out.push({ id: `${s.id}:${bi}:${si}`, cast: b.cast, text: t, recorded: b.recorded, line: b.line }));
    });
  return out;
}

const castSpec = (script, c) => (script.fm.cast && typeof script.fm.cast === 'object' ? script.fm.cast[c] : null) || {};

function applyPronounce(script, text) {
  let t = text;
  const p = script.fm.pronounce && typeof script.fm.pronounce === 'object' ? script.fm.pronounce : {};
  for (const k of Object.keys(p).sort((a, b) => b.length - a.length)) t = t.split(k).join(String(p[k]));
  return t;
}

function lockKey(script, s) {
  const c = castSpec(script, s.cast);
  return hashOf({
    voice: c.voice || null,
    style: c.style || null,
    lang: script.fm.lang,
    text: applyPronounce(script, s.text),
    pacing: script.fm.pacing || null,
  }).slice(0, 16);
}

const lockDirOf = (script) => path.join(path.dirname(script.file), 'audio', String(script.fm.lang));
function readManifest(script) {
  try {
    return JSON.parse(fs.readFileSync(path.join(lockDirOf(script), 'manifest.json'), 'utf8'));
  } catch {
    return { version: 1, entries: {} };
  }
}

function lockOf(script, s, manifest) {
  const e = manifest.entries[lockKey(script, s)];
  if (!e) return null;
  const wav = path.join(lockDirOf(script), e.src);
  return fs.existsSync(wav) ? { e, wav } : null;
}

// ---------- lint ----------
function outputsOf(script) {
  return typeof script.fm.outputs === 'object' && script.fm.outputs ? script.fm.outputs : {};
}

function estimate(script, manifest) {
  const cps = Number(SCENARIO.chars_per_sec || 7);
  let total = 0;
  for (const s of sentencesOf(script)) {
    const l = lockOf(script, s, manifest);
    total += l ? Number(l.e.duration) : plain(s.text).length / cps;
  }
  return total;
}

const fmt = (sec) => {
  const s = Math.round(sec);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

function diagnostics(script) {
  const d = [];
  const dir = path.dirname(script.file);
  if (!script.fm.lang) d.push({ severity: 'error', code: 'lang', message: 'frontmatter has no lang' });
  if (Object.keys(outputsOf(script)).length === 0)
    d.push({ severity: 'error', code: 'outputs', message: 'frontmatter has no outputs' });
  for (const im of script.images)
    if (!fs.existsSync(path.resolve(dir, im.src)))
      d.push({ severity: 'error', code: 'asset-missing', message: `${im.src} does not exist`, line: im.line });
  for (const s of script.scenes)
    for (const b of s.blocks)
      if (b.kind === 'paragraph' && script.casts.length > 0 && !script.casts.includes(b.cast))
        d.push({ severity: 'error', code: 'cast', message: `unknown cast "${b.cast}"`, line: b.line });
  const secs = estimate(script, readManifest(script));
  for (const [name, o] of Object.entries(outputsOf(script))) {
    const max = typeof o === 'object' ? o.maxDuration : undefined;
    if (typeof max === 'number' && secs > max)
      d.push({ severity: 'warning', code: 'max-duration', message: `"${name}" is ${fmt(secs)} (estimated), over its maxDuration ${fmt(max)}` });
  }
  const target = script.fm.targetDuration;
  if (typeof target === 'number' && Object.keys(outputsOf(script)).length > 0) {
    const diff = (secs - target) / target;
    if (Math.abs(diff) > 0.15)
      d.push({
        severity: 'warning',
        code: 'target-duration',
        message: `"${Object.keys(outputsOf(script))[0]}" is ${fmt(secs)} (estimated), ${diff > 0 ? '+' : ''}${Math.round(diff * 100)}% from targetDuration ${fmt(target)} (tolerance ±15%)`,
      });
  }
  for (const x of (SCENARIO.lint && SCENARIO.lint.errors) || []) d.push({ severity: 'error', ...x });
  for (const x of (SCENARIO.lint && SCENARIO.lint.warnings) || []) d.push({ severity: 'warning', ...x });
  return d;
}

function load(file, keepGoing) {
  if (!fs.existsSync(file) || !fs.statSync(file).isFile()) {
    err(`${file}: no such file`);
    process.exit(1);
  }
  const script = parseScript(file);
  const d = diagnostics(script);
  for (const x of d) err(`${file}${x.line ? `:${x.line}` : ''} ${x.severity} [${x.code}] ${x.message}`);
  if (!keepGoing && d.some((x) => x.severity === 'error')) process.exit(1);
  return { script, diags: d };
}

// ---------- version ----------
function versionInfo() {
  const base = { version: '0.12.2', code: 'fakec0de0001', commit: 'f'.repeat(40), dirty: false, stale_build: false, stale_packages: [] };
  const v = { ...base, ...(SCENARIO.version || {}) };
  if (!('id' in (SCENARIO.version || {}))) v.id = `${v.version}+${v.code}`;
  return v;
}

// ---------- inspect ----------
function inspect(script, shownPath) {
  const dir = path.dirname(script.file);
  const files = new Map();
  const ref = (p, kind) => {
    const abs = path.resolve(dir, p);
    const rel = path.relative(dir, abs).split(path.sep).join('/');
    const sha = fileSha(abs);
    const f = files.get(rel);
    if (f) {
      if (!f.kind.split(',').includes(kind)) f.kind = [...f.kind.split(','), kind].sort().join(',');
    } else files.set(rel, { path: rel, sha256: sha, kind });
    return sha ? `${rel}@${sha}` : `missing:${rel}`;
  };
  const groups = { content: [], voice: [], presentation: [] };
  const put = (kinds, value) => {
    for (const k of kinds) if (groups[k]) groups[k].push(value);
  };
  const fmTable = TABLE.frontmatter;
  for (const [k, v] of Object.entries(script.fm)) {
    const kinds = fmTable[k];
    if (!kinds) continue; // a key the table does not know: no hash (s2v reports unknown keys in lint)
    let value = v;
    if (k === 'outputs' && typeof v === 'object') {
      value = {};
      for (const [n, o] of Object.entries(v)) {
        const copy = typeof o === 'object' ? { ...o } : o;
        for (const ig of TABLE.output_attrs_ignored) if (copy && typeof copy === 'object') delete copy[ig];
        value[n] = copy;
      }
    }
    if (k === 'logo' && typeof v === 'object' && v.src) value = { ...v, src: ref(v.src, 'logo') };
    if (k === 'subtitleStyle' && typeof v === 'object' && v.font) value = { ...v, font: ref(v.font, 'font') };
    if (k === 'bgm' && typeof v === 'object' && v.src) value = { ...v, src: ref(v.src, 'bgm') };
    put(kinds, { [k]: value });
  }
  const screen = [];
  for (const s of script.scenes) {
    put(TABLE.body.scene_title, { scene: s.id, title: s.title });
    s.blocks.forEach((b, bi) => {
      if (b.kind === 'paragraph') put(TABLE.body.paragraph, { scene: s.id, block: bi, cast: b.cast, text: b.text });
      if (b.kind === 'screen') {
        put(TABLE.body.screen, { scene: s.id, block: bi, type: b.type, text: b.text });
        screen.push({ scene: s.id, kind: b.type, text: b.text });
      }
    });
  }
  for (const im of script.images) put(TABLE.body.image, { image: ref(im.src, im.kind || 'image') });
  const reasons = {};
  const sents = sentencesOf(script);
  const used = [...new Set(sents.map((s) => s.cast))].sort();
  const voiceValue = used.map((c) => ({ cast: c, voice: castSpec(script, c).voice || null, style: castSpec(script, c).style || null }));
  let voice = hashOf({ casts: voiceValue, rest: groups.voice });
  if (used.some((c) => !castSpec(script, c).voice)) {
    voice = null;
    reasons.voice = [`cast without a voice: ${used.filter((c) => !castSpec(script, c).voice).join(', ')}`];
  }
  let audio = null;
  const manifest = readManifest(script);
  const missing = [];
  const pairs = [];
  for (const s of sents) {
    if (s.recorded) continue;
    const l = lockOf(script, s, manifest);
    if (!l) missing.push(s.id);
    else pairs.push([lockKey(script, s), sha256(fs.readFileSync(l.wav)), l.e.duration]);
  }
  if (missing.length) reasons.audio = [`${missing.length} sentence(s) not synthesized: ${missing.slice(0, 5).join(', ')}`];
  else if (voice !== null) audio = hashOf(pairs.sort());
  if (voice === null) reasons.audio = reasons.voice;
  const presentation = {};
  const outputs = [];
  for (const [name, o] of Object.entries(outputsOf(script))) {
    const attrs = typeof o === 'object' ? o : {};
    const gone = [...files.values()].filter((f) => f.sha256 === null).map((f) => f.path);
    presentation[name] = gone.length ? null : hashOf({ output: name, groups: groups.presentation });
    if (gone.length) reasons[`presentation.${name}`] = [`missing file(s): ${gone.join(', ')}`];
    outputs.push({
      name,
      aspect: attrs.aspect || '16:9',
      layout: attrs.layout || 'single',
      thumbnail: (attrs.aspect || '16:9') === '16:9',
      chapters: script.scenes.length > 1,
      scenes: script.scenes.map((s) => s.id),
      framing: {},
    });
  }
  const engine = {
    tts: 'fake-tts-1',
    templates: 'fake-templates-1',
    defaults_voice: 'fake-defaults-voice-1',
    composer: 'fake-composer-1',
    renderer: 'fake-renderer-1',
    ffmpeg: 'fake-ffmpeg-1',
    defaults_presentation: 'fake-defaults-presentation-1',
    ...(SCENARIO.engine || {}),
  };
  const v = versionInfo();
  return {
    s2v_version: v.id,
    stale_build: v.stale_build,
    hash_version: 1,
    script: shownPath,
    lang: script.fm.lang,
    hashes: {
      content: hashOf(groups.content),
      voice,
      audio,
      presentation_by_output: presentation,
      engine: Object.fromEntries(Object.entries(engine).map(([k, x]) => [k, hashOf({ v: x })])),
    },
    reasons,
    engine,
    outputs,
    scenes: script.scenes.map((s) => ({ id: s.id, title: s.title })),
    screen_text: screen,
    voices: used.map((c) => ({ cast: c, voice: castSpec(script, c).voice || null, engine: 'qwen', lang: script.fm.lang })),
    characters: [],
    faces: [],
    files: [...files.values()].sort((a, b) => (a.path < b.path ? -1 : 1)),
  };
}

// ---------- sentences ----------
function report(script) {
  const manifest = readManifest(script);
  return sentencesOf(script).map((s) => {
    const key = s.recorded ? null : lockKey(script, s);
    const l = s.recorded ? null : lockOf(script, s, manifest);
    return {
      ...UNKNOWN,
      id: s.id,
      cast: s.cast,
      text: s.text,
      recorded: s.recorded,
      lockKey: key,
      pickKey: key ? `${key}:pick` : null,
      acting: null,
      pick: null,
      lock: l
        ? {
            attempt: l.e.attempt,
            wavSha256: sha256(fs.readFileSync(l.wav)),
            asr: l.e.asr,
            cer: l.e.asr ? l.e.cer : null,
            heard: l.e.asr ? l.e.heard : '',
            checks: l.e.checks || [],
          }
        : null,
      error: null,
    };
  });
}

// ---------- tts ----------
function wavBytes(seed, seconds) {
  const rate = 8000;
  const n = Math.max(8, Math.round(rate * Math.min(seconds, 0.05)));
  const data = Buffer.alloc(n * 2);
  const h = crypto.createHash('sha256').update(seed).digest();
  for (let i = 0; i < n; i++) data.writeInt16LE(h[i % h.length] * 8 - 1024, i * 2);
  const head = Buffer.alloc(44);
  head.write('RIFF', 0);
  head.writeUInt32LE(36 + data.length, 4);
  head.write('WAVE', 8);
  head.write('fmt ', 12);
  head.writeUInt32LE(16, 16);
  head.writeUInt16LE(1, 20);
  head.writeUInt16LE(1, 22);
  head.writeUInt32LE(rate, 24);
  head.writeUInt32LE(rate * 2, 28);
  head.writeUInt16LE(2, 32);
  head.writeUInt16LE(16, 34);
  head.write('data', 36);
  head.writeUInt32LE(data.length, 40);
  return Buffer.concat([head, data]);
}

function repoRootOf(dir) {
  let d = dir;
  for (;;) {
    if (fs.existsSync(path.join(d, '.git'))) return d;
    const up = path.dirname(d);
    if (up === d) return dir;
    d = up;
  }
}

function baseVoices(script) {
  // the outermost existing voices/ between the script and the repository root (else <root>/voices, as s2v does)
  const dir = path.dirname(script.file);
  const root = repoRootOf(dir);
  let found = null;
  let d = dir;
  for (;;) {
    const v = path.join(d, 'voices');
    if (fs.existsSync(v) && fs.statSync(v).isDirectory()) found = v;
    if (d === root) break;
    const up = path.dirname(d);
    if (up === d) break;
    d = up;
  }
  const where = found || path.join(root, 'voices');
  for (const c of [...new Set(sentencesOf(script).map((s) => s.cast))]) {
    const voice = String(castSpec(script, c).voice || '');
    if (!voice.startsWith('qwen:')) continue;
    const name = voice.slice('qwen:'.length);
    const base = path.join(where, '_qwen', name, `${script.fm.lang}-${hashOf({ voice, lang: script.fm.lang }).slice(0, 8)}`);
    if (fs.existsSync(`${base}.json`)) continue;
    fs.mkdirSync(path.dirname(base), { recursive: true });
    fs.writeFileSync(`${base}.wav`, wavBytes(`${voice}:${script.fm.lang}`, 0.05));
    fs.writeFileSync(`${base}.json`, `${JSON.stringify({ voice, lang: script.fm.lang, sentences: 4, seeds: 5 }, null, 2)}\n`);
  }
}

function retried(id, specs) {
  return (specs || []).some((r) => id === r || id.startsWith(`${r}:`));
}

function tts(script, values) {
  const t = SCENARIO.tts || {};
  err(`tts: ${sentencesOf(script).length} sentence(s) to check`);
  if (t.busy) {
    err('tts: loading the plan');
    err(`busy (${t.busy}): the machine lock is held by another s2v (pid 4242, tts)`);
    err('  see: s2v services status');
    process.exit(73);
  }
  baseVoices(script);
  const dir = lockDirOf(script);
  fs.mkdirSync(dir, { recursive: true });
  const manifest = readManifest(script);
  let synthesized = 0;
  let reused = 0;
  const cps = Number(SCENARIO.chars_per_sec || 7);
  const per = SCENARIO.sentences || {};
  let n = 0;
  for (const s of sentencesOf(script)) {
    if (s.recorded) continue;
    const key = lockKey(script, s);
    const have = lockOf(script, s, manifest);
    if (have && !retried(s.id, values.retry)) {
      reused++;
      continue;
    }
    if (t.signal && n >= (t.signal_after || 0)) {
      fs.writeFileSync(path.join(dir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
      err(`tts: stopped by signal ${t.signal}`);
      process.exit(128 + Number(t.signal));
    }
    const attempt = have ? have.e.attempt + 1 : 1;
    const conf = per[s.id] || {};
    const pick = (arr, dflt) => (Array.isArray(arr) ? arr[Math.min(attempt - 1, arr.length - 1)] : dflt);
    const asr = values['no-asr'] ? false : pick(conf.asr, true);
    const src = `${key}.${attempt}.wav`;
    const duration = Math.round((plain(s.text).length / cps) * 1000) / 1000;
    fs.writeFileSync(path.join(dir, src), wavBytes(`${key}:${attempt}`, duration));
    manifest.entries[key] = {
      src,
      attempt,
      duration,
      words: [],
      asr,
      cer: asr ? pick(conf.cer, 0) : null,
      heard: asr ? pick(conf.heard, s.text) : '',
      checks: pick(conf.checks, []),
    };
    synthesized++;
    n++;
  }
  const tmp = path.join(dir, `manifest.json.tmp.${process.pid}`);
  fs.writeFileSync(tmp, `${JSON.stringify(manifest, null, 2)}\n`);
  fs.renameSync(tmp, path.join(dir, 'manifest.json'));
  err(`synthesized ${synthesized}, reused ${reused} in 0.0s → ${path.join(dir, 'manifest.json')}`);
}

// ---------- snapshot / render ----------
function outputOf(script, name) {
  const outs = outputsOf(script);
  const n = name || Object.keys(outs)[0];
  if (!n || !(n in outs)) throw new UsageError(`unknown output "${name}" (the script has: ${Object.keys(outs).join(', ')})`);
  const o = typeof outs[n] === 'object' ? outs[n] : {};
  return { name: n, aspect: o.aspect || '16:9' };
}

function frozenProblem(script) {
  const manifest = readManifest(script);
  const missing = sentencesOf(script).filter((s) => !s.recorded && !lockOf(script, s, manifest));
  return missing.length ? `--frozen-audio: ${missing.length} sentence(s) are not in the audio lock (run tts first)` : null;
}

const outDirOf = (script, flag) => (flag !== undefined ? path.resolve(flag) : path.join(FAKE_ROOT, 'out', path.basename(path.dirname(script.file))));

function snapshot(script, values) {
  if (values['out-dir'] === undefined) throw new UsageError('the fake s2v writes only with --out-dir (never into its own folder)');
  const o = outputOf(script, values.output);
  const outDir = outDirOf(script, values['out-dir']);
  const lang = script.fm.lang;
  const sheet = path.join(outDir, `${o.name}.${lang}.snapshot.png`);
  const frames = path.join(outDir, `${o.name}.${lang}.frames`);
  fs.rmSync(sheet, { force: true });
  fs.rmSync(frames, { recursive: true, force: true });
  if (!values['frozen-audio']) {
    err('fake s2v: a snapshot without --frozen-audio would synthesize (not faked)');
    process.exit(1);
  }
  const fp = frozenProblem(script);
  if (fp) {
    err(fp);
    process.exit(1);
  }
  fs.mkdirSync(outDir, { recursive: true });
  if (values.frames) {
    const tmp = path.join(outDir, `${o.name}.${lang}.frames.tmp`);
    fs.rmSync(tmp, { recursive: true, force: true });
    fs.mkdirSync(tmp, { recursive: true });
    if (SCENARIO.snapshot && SCENARIO.snapshot.interrupt) {
      fs.writeFileSync(path.join(tmp, '000-partial.png'), Buffer.from('partial'));
      err('snapshot: stopped by signal 2');
      process.exit(130);
    }
    let start = 0;
    const scenes = script.scenes.map((s, k) => {
      const file = `${String(k).padStart(3, '0')}-${s.id}-20.png`;
      fs.writeFileSync(path.join(tmp, file), pngBytes(`${script.text}:${o.name}:${s.id}`));
      const r = { id: s.id, title: s.title, startFrame: start, frames: [{ file, frame: 20, seconds: Math.round(((start + 20) / 30) * 1000) / 1000, reasons: ['scene start'] }] };
      start += 90;
      return r;
    });
    const index = {
      output: o.name,
      lang,
      draft: false,
      fps: 30,
      s2v_version: versionInfo().id,
      script_sha256: sha256(fs.readFileSync(script.file)),
      scale: 1,
      scenes,
      ...UNKNOWN,
    };
    fs.writeFileSync(path.join(tmp, 'index.json'), `${JSON.stringify(index, null, 2)}\n`);
    fs.renameSync(tmp, frames);
  }
  fs.writeFileSync(sheet, pngBytes(`${script.text}:${o.name}:sheet`));
  err(`→ ${sheet}`);
}

function pngBytes(seed) {
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from(sha256(seed))]);
}

function render(script, values) {
  if (values['out-dir'] === undefined) throw new UsageError('the fake s2v writes only with --out-dir (never into its own folder)');
  if (values.watermark !== undefined && values.watermark !== 'proxy')
    throw new UsageError(`--watermark takes only proxy, not "${values.watermark}"`);
  const o = outputOf(script, values.output);
  const proxy = values.watermark === 'proxy';
  const r = SCENARIO.render || {};
  if (!values['frozen-audio']) {
    err('fake s2v: a render without --frozen-audio would synthesize (not faked)');
    process.exit(1);
  }
  const fp = frozenProblem(script);
  if (fp) {
    err(fp);
    process.exit(1);
  }
  const lang = script.fm.lang;
  const outDir = outDirOf(script, values['out-dir']);
  fs.mkdirSync(outDir, { recursive: true });
  const base = path.join(outDir, `${o.name}.${lang}${proxy ? '.proxy' : ''}`);
  err(`tts: synthesized 0, reused ${sentencesOf(script).length}`);
  const manifest = readManifest(script);
  const seed = `${sha256(fs.readFileSync(script.file))}:${o.name}:${proxy}:${hashOf(manifest)}`;
  const tmp = `${base}.tmp.${process.pid}.mp4`;
  fs.writeFileSync(tmp, Buffer.concat([Buffer.from('FAKEMP4'), Buffer.from(sha256(seed))]));
  if (r.tmp_leftover) fs.copyFileSync(tmp, `${base}.tmp.1.mp4`);
  fs.renameSync(tmp, `${base}.mp4`);
  const frames = Math.max(1, script.scenes.length) * 90;
  if (r.check_failed) err(`CHECK FAILED: ${frames - 3}/${frames} frames, video ${(frames / 30).toFixed(3)}s, audio ${(frames / 30 + 0.2).toFixed(3)}s`);
  else if (!r.no_ok_line) err(`ok: ${frames}/${frames} frames, video ${(frames / 30).toFixed(3)}s, audio ${(frames / 30).toFixed(3)}s`);
  err(`→ ${base}.mp4 (0.1s)`);
  for (const [ext, body] of [
    ['srt', `1\n00:00:00,000 --> 00:00:01,000\n${script.fm.title || ''}\n`],
    ['vtt', 'WEBVTT\n'],
    ['description.md', `${script.fm.title || ''}\n`],
  ]) {
    fs.writeFileSync(`${base}.${ext}`, body);
    err(`→ ${base}.${ext}`);
  }
  const chapters = `${base}.chapters.txt`;
  if (o.aspect === '16:9' && script.scenes.length > 1) {
    fs.writeFileSync(chapters, script.scenes.map((s, k) => `${fmt(k * 3)} ${s.title}`).join('\n') + '\n');
    err(`→ ${chapters}`);
  } else fs.rmSync(chapters, { force: true }); // not last run's (S2)
  const thumb = `${base}.thumbnail.png`;
  if (o.aspect === '16:9') {
    fs.writeFileSync(thumb, pngBytes(`${seed}:thumb`));
    err(`→ ${thumb}`);
  } else fs.rmSync(thumb, { force: true });
  if (r.check_failed) process.exit(1);
  if (r.exit_after_write) process.exit(Number(r.exit_after_write));
}

// ---------- main ----------
function main() {
  const argv = process.argv.slice(2);
  logCall(argv);
  const [command, ...rest] = argv;
  if (command === '--version') {
    if (rest.some((a) => a !== '--json')) throw new UsageError('s2v --version: takes only --json');
    const v = versionInfo();
    if (rest.includes('--json')) out(v);
    else process.stdout.write(`s2v ${v.id}\n`);
    return;
  }
  if (command === 'services') {
    if (rest[0] !== 'status') throw new UsageError('s2v services status [--json]');
    const { values } = parseFlags('services status', rest.slice(1));
    const sv = SCENARIO.services || {};
    const stateDir = sv.state_dir || process.env.S2V_STATE_DIR || path.join(process.env.HOME || '', '.s2v');
    const busy = sv.busy_tts ? { reason: sv.busy_tts } : null;
    const status = { version: 1, state_dir: stateDir, busy: { tts: busy, gen: busy }, lock: null, breaking: false, resident: null, servers: [], orphans: 0, cleaned: [], warnings: [] };
    if (values.json) out(status);
    else process.stdout.write(`machine lock: ${busy ? 'busy' : 'free'}\n`);
    return;
  }
  if (command === 'doctor') {
    parseFlags('doctor', rest);
    const fail = SCENARIO.doctor && SCENARIO.doctor.fail;
    process.stdout.write(`ok    node\n${fail ? 'FAIL' : 'ok  '}  fake tools\n${fail ? '\n1 required check(s) failed\n' : '\nready\n'}`);
    if (fail) process.exit(1);
    return;
  }
  if (!(command in FLAGS)) throw new UsageError(`unknown command: ${command ?? '(none)'}`);
  const { values, positionals } = parseFlags(command, rest);
  const file = positionals[0];
  if (!file || positionals.length !== 1) throw new UsageError(`s2v ${command} <script.md>`);
  const abs = path.resolve(file);
  switch (command) {
    case 'lint': {
      load(abs);
      err(`${file}: ok`);
      break;
    }
    case 'check': {
      const { script } = load(abs);
      if (SCENARIO.check && SCENARIO.check.overflow) {
        err(`${abs}:${script.scenes[0] ? script.scenes[0].line : 1} error [subtitle-overflow] a subtitle does not fit its box`);
        process.exit(1);
      }
      err(`${file}: ${sentencesOf(script).length} subtitles fit (text)`);
      break;
    }
    case 'inspect': {
      if (!values.json) throw new UsageError('s2v inspect <script.md> --json');
      if (values['hash-version'] !== undefined && values['hash-version'] !== '1') {
        err(`--hash-version ${values['hash-version']}: supported: 1`);
        process.exit(2);
      }
      if (!fs.existsSync(abs)) {
        err(`${file}: no such file`);
        process.exit(2);
      }
      const script = parseScript(abs);
      // a missing file is no error here: its hash is null with the reason (s2v inspect's null reasons)
      const errors = diagnostics(script).filter((d) => d.severity === 'error' && d.code !== 'asset-missing');
      if (errors.length) {
        for (const e of errors) err(`${abs}${e.line ? `:${e.line}` : ''} error ${e.message}`);
        process.exit(1);
      }
      out(inspect(script, file));
      break;
    }
    case 'sentences': {
      const { script, diags } = load(abs, values.json);
      if (values.json) {
        process.stdout.write(`${JSON.stringify(report(script), null, 2)}\n`);
        if (diags.some((d) => d.severity === 'error')) process.exitCode = 1;
      } else for (const s of sentencesOf(script)) process.stdout.write(`${s.id}\t${s.cast}\t${s.text}\n`);
      break;
    }
    case 'tts': {
      const { script } = load(abs);
      tts(script, values);
      break;
    }
    case 'snapshot': {
      const { script } = load(abs);
      snapshot(script, values);
      break;
    }
    case 'render': {
      const { script } = load(abs);
      render(script, values);
      break;
    }
    default:
      throw new UsageError(`unknown command: ${command}`);
  }
}

try {
  main();
} catch (e) {
  if (e instanceof UsageError) {
    err(`usage: ${e.message}`);
    process.exit(2);
  }
  err(`error: ${e && e.stack ? e.stack : e}`);
  process.exit(1);
}
