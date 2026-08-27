#!/usr/bin/env node
// Quality Playbook Factory — workspace scaffolder (Tier 3).
//
// Creates a self-contained, tool-agnostic customer quality workspace from the tool's
// templates and house standards. Invoked by the /qpf-init command.
//
// Usage:
//   node scaffold.mjs --customer "Acme Corp" [--language en|fi] [--dir <path>]
//
//   --customer   (required) customer/org display name
//   --language   en | fi  (default: en) — set ONCE; all deliverables render in it
//   --dir        target directory (default: ./<slug>-quality)
//   --force      allow writing into an existing non-empty directory

import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync, cpSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

// --- locate the tool root (scripts/ lives directly under it) --------------------
const TOOL_ROOT = process.env.CLAUDE_PLUGIN_ROOT
  ? resolve(process.env.CLAUDE_PLUGIN_ROOT)
  : resolve(dirname(fileURLToPath(import.meta.url)), '..');

// --- tiny arg parser ------------------------------------------------------------
function parseArgs(argv) {
  const out = { language: 'en' };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--customer') out.customer = argv[++i];
    else if (a === '--language') out.language = argv[++i];
    else if (a === '--dir') out.dir = argv[++i];
    else if (a === '--force') out.force = true;
    else die(`Unknown argument: ${a}`);
  }
  return out;
}

function die(msg) {
  console.error(`✗ ${msg}`);
  process.exit(1);
}

function slugify(s) {
  return s.toLowerCase().trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

// ISO 8601 with an explicit UTC offset, as OKF v0.2 §5 requires of every timestamp.
function nowIso() { return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'); }

// Best-effort local identity for `generated.by`. Falls back to a placeholder the
// authoring agent (or a human) is expected to replace.
function gitUser() {
  try {
    const name = execFileSync('git', ['config', 'user.name'], { encoding: 'utf8' }).trim();
    return name ? slugify(name) : '<your-id>';
  } catch { return '<your-id>'; }
}

function today() {
  // Local YYYY-MM-DD.
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function render(text, vars) {
  return text.replace(/\{\{(\w+)\}\}/g, (m, k) => (k in vars ? vars[k] : m));
}

function writeRendered(srcRel, destAbs, vars) {
  const src = join(TOOL_ROOT, srcRel);
  writeFileSync(destAbs, render(readFileSync(src, 'utf8'), vars));
}

// --- main -----------------------------------------------------------------------
const args = parseArgs(process.argv.slice(2));
if (!args.customer) die('Missing --customer "<name>"');
if (!['en', 'fi'].includes(args.language)) die('--language must be "en" or "fi"');

const version = readFileSync(join(TOOL_ROOT, 'VERSION'), 'utf8').trim();
const slug = slugify(args.customer);
const dest = resolve(args.dir || `${slug}-quality`);
// TIMESTAMP/AUTHOR feed the OKF v0.2 trust fields in the wiki templates: every OKF
// timestamp is an ISO 8601 datetime with an explicit UTC offset (a bare date is not
// conformant), and actors use the `human:<id>` prefix that trust tiers key off.
const vars = {
  CUSTOMER: args.customer, LANGUAGE: args.language, VERSION: version,
  DATE: today(), TIMESTAMP: nowIso(), AUTHOR: gitUser(),
};

if (existsSync(dest) && readdirSync(dest).length > 0 && !args.force) {
  die(`Target ${dest} exists and is not empty (use --force to write into it).`);
}

// directory skeleton
const dirs = [
  'raw/workshops', 'raw/interviews', 'raw/assessments', 'raw/product', 'raw/assets',
  'wiki/log', 'wiki/summaries', 'wiki/entities', 'wiki/concepts',
  'guidelines', 'playbooks',
];
for (const d of dirs) mkdirSync(join(dest, d), { recursive: true });

// seeded top-level files (rendered)
writeRendered('templates/workspace/AGENTS.md', join(dest, 'AGENTS.md'), vars);
writeRendered('templates/workspace/CLAUDE.md', join(dest, 'CLAUDE.md'), vars);
writeRendered('templates/workspace/README.md', join(dest, 'README.md'), vars);
writeRendered('templates/workspace/qpf.config.yml', join(dest, 'qpf.config.yml'), vars);
writeRendered('templates/workspace/gitignore', join(dest, '.gitignore'), vars);

// derived wiki starters
writeRendered('templates/wiki/index.md', join(dest, 'wiki/index.md'), vars);
writeRendered('templates/wiki/overview.md', join(dest, 'wiki/overview.md'), vars);
writeFileSync(join(dest, 'wiki/log/.gitkeep'), '');

// Guidelines: seed the tailorable source of truth from the house default.
cpSync(join(TOOL_ROOT, 'standards/quality-guidelines.default.yml'),
       join(dest, 'guidelines/guidelines.yml'));
writeFileSync(join(dest, 'guidelines/guidelines.md'),
  '<!-- DERIVED — run `rebuild-index` to render from guidelines.yml. -->\n');

// keep empty dirs in git
for (const d of ['raw/workshops', 'raw/interviews', 'raw/assessments', 'raw/product',
                 'raw/assets', 'wiki/summaries', 'wiki/entities', 'wiki/concepts',
                 'playbooks']) {
  writeFileSync(join(dest, d, '.gitkeep'), '');
}

// init git in the workspace
try {
  execFileSync('git', ['init', '-q'], { cwd: dest });
} catch {
  console.warn('! git not available — skipped `git init` (initialize the repo manually).');
}

console.log(`✓ Scaffolded workspace for "${args.customer}" (${args.language}) at:\n  ${dest}\n`);
console.log('Next steps:');
console.log(`  1. cd ${dest} && git add -A && git commit -m "Scaffold quality workspace"`);
console.log('  2. Drop engagement inputs into raw/ and run /qpf-ingest.');
console.log('  3. /qpf-guidelines to tailor, then /qpf-playbook <team> per team.');
