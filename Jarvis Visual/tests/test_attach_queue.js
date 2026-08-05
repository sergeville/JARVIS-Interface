#!/usr/bin/env node
// Tests for the attachment QUEUE on jarvis.html.
//
// Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
//    or  node tests/test_attach_queue.js
//
// Serge, 2026-08-05: "when I add two images side-by-side or back-to-back, it
// only catches the last image." The page held ONE attachment and every new
// image overwrote it. Silently -- which is the part that actually hurt: the
// first image was gone with nothing on screen to say so.
//
// What these guard, and why each one is a real way to rebuild the bug:
//
//   ADDING replaces      -- the original defect. One assignment instead of a
//                           push and it is back, looking exactly as it did.
//   ORDER                -- he refers to "the first one" and "the second".
//                           A queue that reorders makes the prompt lie.
//   REMOVING ONE         -- a queue you can only empty wholesale is barely
//                           better than a slot.
//   THE CAP              -- and the re-check inside the reader, because
//                           FileReader is async: several files can pass the
//                           bounds check and land after the queue is full.
//   THE EMPTY STATE      -- the container must hide itself, or an empty
//                           bordered box sits under the input forever.
//   REJECTIONS SPEAK     -- 2026-08-05's other lesson: a drop that produces
//                           no chip and no message is how a file vanishes.
//
// As with the other page tests, the real functions are pulled out of
// jarvis.html and run against a DOM stub, so they cannot drift from what
// ships.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const HTML = path.join(__dirname, '..', 'jarvis.html');
const src = fs.readFileSync(HTML, 'utf8');

// ---- DOM stub -------------------------------------------------------------
function makeNode(tag) {
  const n = {
    tag, className: '', textContent: '', title: '', src: '', alt: '',
    innerHTML: '', style: {}, children: [], _handlers: {},
    append(...cs) { this.children.push(...cs); },
    appendChild(c) { this.children.push(c); },
    addEventListener(ev, fn) { this._handlers[ev] = fn; },
    click() { if (this._handlers.click) this._handlers.click(); },
  };
  // Setting innerHTML = '' is how renderAttachments clears the rows.
  Object.defineProperty(n, 'innerHTML', {
    get() { return ''; },
    set(v) { if (v === '') n.children = []; },
  });
  return n;
}
const attachEl = makeNode('div');
const typedEl = makeNode('input');
typedEl.focus = () => {};
global.document = {
  getElementById: id => (id === 'attach' ? attachEl : null),
  createElement: tag => makeNode(tag),
};

// ---- pull the real functions out of the page ------------------------------
function grab(name) {
  const start = src.indexOf('function ' + name + '(');
  assert.ok(start !== -1, 'function not found in jarvis.html: ' + name);
  let i = src.indexOf('{', start), depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') { depth--; if (depth === 0) { end = j + 1; break; } }
  }
  assert.ok(end !== -1, 'unbalanced braces reading ' + name);
  return src.slice(start, end);
}

// MAX_ATTACH is read from the page too -- a test carrying its own copy of the
// number would keep passing after someone changed it.
const capM = src.match(/const MAX_ATTACH\s*=\s*(\d+)/);
assert.ok(capM, 'MAX_ATTACH not found in jarvis.html');
const MAX_ATTACH = Number(capM[1]);

let attached = [];
let said = [];                 // what showLine() was asked to say
function showLine(who, text) { said.push(who + ': ' + text); }

// FileReader, made synchronous so the tests are deterministic. The real one
// is async, which is exactly why the cap is re-checked inside onload; the
// async case gets its own test below via readLater.
let readLater = null;          // set to an array to defer the callbacks
function FileReader() {
  this.readAsDataURL = (file) => {
    const fire = () => {
      this.result = 'data:' + file.type + ';base64,' + (file._b64 || 'AAAA');
      this.onload();
    };
    if (readLater) readLater.push(fire); else fire();
  };
}

const body = [
  'let attached = [];',
  grab('renderAttachments'),
  grab('setAttachment'),
  grab('clearAttachment'),
  'return {renderAttachments, setAttachment, clearAttachment,' +
  ' get attached(){return attached;}, set attached(v){attached = v;}};',
].join('\n');
const api = new Function('attachEl', 'typedEl', 'showLine', 'FileReader',
                         'MAX_ATTACH', 'document', body)(
  attachEl, typedEl, showLine, FileReader, MAX_ATTACH, global.document);

function file(name, type, size) {
  return {name, type: type || 'image/png', size: size || 1024, _b64: name};
}
function reset() { api.clearAttachment(); said = []; readLater = null; }

// ---- the tests ------------------------------------------------------------
let pass = 0, fail = 0;
function t(name, fn) {
  reset();
  try { fn(); pass++; }
  catch (e) { fail++; console.error('  FAIL ' + name + '\n    ' + e.message); }
}

// --- adding ---------------------------------------------------------------
t('one image lands in the queue', () => {
  assert.strictEqual(api.setAttachment(file('a.png')), 'ok');
  assert.strictEqual(api.attached.length, 1);
  assert.strictEqual(api.attached[0].name, 'a.png');
});

t('THE REGRESSION: a second image joins, it does not replace', () => {
  api.setAttachment(file('a.png'));
  api.setAttachment(file('b.png'));
  assert.strictEqual(api.attached.length, 2, 'second image replaced the first');
});

t('THE REGRESSION: three back-to-back all survive', () => {
  ['a.png', 'b.png', 'c.png'].forEach(n => api.setAttachment(file(n)));
  assert.deepStrictEqual(api.attached.map(a => a.name), ['a.png', 'b.png', 'c.png']);
});

t('order is the order he added them', () => {
  ['z.png', 'm.png', 'a.png'].forEach(n => api.setAttachment(file(n)));
  assert.deepStrictEqual(api.attached.map(a => a.name), ['z.png', 'm.png', 'a.png']);
});

t('the same file twice is kept twice, not de-duplicated', () => {
  api.setAttachment(file('same.png'));
  api.setAttachment(file('same.png'));
  assert.strictEqual(api.attached.length, 2);
});

// --- rendering ------------------------------------------------------------
t('a row is drawn per image', () => {
  api.setAttachment(file('a.png'));
  api.setAttachment(file('b.png'));
  assert.strictEqual(attachEl.children.length, 2);
  attachEl.children.forEach(r => assert.strictEqual(r.className, 'att-row'));
});

t('rows are rebuilt, never appended to', () => {
  api.setAttachment(file('a.png'));
  api.setAttachment(file('b.png'));
  api.setAttachment(file('c.png'));
  assert.strictEqual(attachEl.children.length, 3, 'stale rows left behind');
});

t('the container shows when there is something and hides when empty', () => {
  assert.strictEqual(attachEl.style.display, 'none');
  api.setAttachment(file('a.png'));
  assert.strictEqual(attachEl.style.display, 'flex');
  api.clearAttachment();
  assert.strictEqual(attachEl.style.display, 'none');
});

t('each row carries a thumbnail and the file name', () => {
  api.setAttachment(file('holiday.png'));
  const row = attachEl.children[0];
  const img = row.children.find(c => c.tag === 'img');
  const nm = row.children.find(c => c.className === 'name');
  assert.ok(img && img.src.startsWith('data:image/png'), 'no thumbnail');
  assert.strictEqual(nm.textContent, 'holiday.png');
});

t('a single image is not numbered; several are', () => {
  api.setAttachment(file('a.png'));
  let num = attachEl.children[0].children.find(c => c.className === 'num');
  assert.strictEqual(num.textContent, '', 'numbered a lone image');
  api.setAttachment(file('b.png'));
  const nums = attachEl.children.map(
    r => r.children.find(c => c.className === 'num').textContent);
  assert.deepStrictEqual(nums, ['1.', '2.']);
});

// --- removing -------------------------------------------------------------
t('the row X removes THAT image, not all of them', () => {
  ['a.png', 'b.png', 'c.png'].forEach(n => api.setAttachment(file(n)));
  const x = attachEl.children[1].children.find(c => c.tag === 'button');
  x.click();
  assert.deepStrictEqual(api.attached.map(a => a.name), ['a.png', 'c.png']);
});

t('removing the last one hides the container', () => {
  api.setAttachment(file('a.png'));
  attachEl.children[0].children.find(c => c.tag === 'button').click();
  assert.strictEqual(api.attached.length, 0);
  assert.strictEqual(attachEl.style.display, 'none');
});

t('removing re-numbers the rows that remain', () => {
  ['a.png', 'b.png', 'c.png'].forEach(n => api.setAttachment(file(n)));
  attachEl.children[0].children.find(c => c.tag === 'button').click();
  const nums = attachEl.children.map(
    r => r.children.find(c => c.className === 'num').textContent);
  assert.deepStrictEqual(nums, ['1.', '2.']);
});

t('clearAttachment empties the whole queue', () => {
  ['a.png', 'b.png', 'c.png'].forEach(n => api.setAttachment(file(n)));
  api.clearAttachment();
  assert.strictEqual(api.attached.length, 0);
  assert.strictEqual(attachEl.children.length, 0);
});

// --- the cap --------------------------------------------------------------
t('the queue stops at MAX_ATTACH and says so', () => {
  for (let i = 0; i < MAX_ATTACH; i++) api.setAttachment(file('f' + i + '.png'));
  assert.strictEqual(api.setAttachment(file('one-too-many.png')), 'full');
  assert.strictEqual(api.attached.length, MAX_ATTACH);
  assert.ok(said.some(s => s.includes('limit')), 'hit the cap silently');
});

t('the cap holds when the reads land late (FileReader is async)', () => {
  // Every file passes the bounds check before any of them finishes reading --
  // the real ordering, and the reason the cap is re-checked inside onload.
  readLater = [];
  for (let i = 0; i < MAX_ATTACH + 4; i++) api.setAttachment(file('f' + i + '.png'));
  readLater.forEach(fire => fire());
  assert.strictEqual(api.attached.length, MAX_ATTACH,
                     'async reads overran the cap');
});

// --- rejections -----------------------------------------------------------
t('a non-image is refused and nothing is queued', () => {
  assert.strictEqual(api.setAttachment(file('notes.pdf', 'application/pdf')),
                     'not-image');
  assert.strictEqual(api.attached.length, 0);
});

t('a missing or typeless file is refused, not thrown on', () => {
  assert.strictEqual(api.setAttachment(null), 'not-image');
  assert.strictEqual(api.setAttachment({}), 'not-image');
});

t('an oversized image is refused OUT LOUD', () => {
  assert.strictEqual(api.setAttachment(file('huge.png', 'image/png', 40e6)),
                     'too-big');
  assert.strictEqual(api.attached.length, 0);
  assert.ok(said.some(s => s.includes('32 MB')), 'refused it silently');
});

t('a rejection does not disturb what is already queued', () => {
  api.setAttachment(file('good.png'));
  api.setAttachment(file('notes.pdf', 'application/pdf'));
  api.setAttachment(file('huge.png', 'image/png', 40e6));
  assert.deepStrictEqual(api.attached.map(a => a.name), ['good.png']);
});

// --- the send payload -----------------------------------------------------
t('each entry carries what the socket needs', () => {
  api.setAttachment(file('a.png'));
  const a = api.attached[0];
  ['name', 'mime', 'b64'].forEach(k => assert.ok(a[k], 'missing ' + k));
  assert.ok(!a.b64.startsWith('data:'), 'b64 still carries the data URL prefix');
});

// ---- the page's own send paths, checked as source ------------------------
// These are inside sendTyped()/release() and reach ws/state, so they are read
// rather than run -- but the two shapes they must produce are load-bearing.
t('both send paths gate the list on the server saying multi_image', () => {
  const typed = grab('sendTyped');
  const rel = grab('release');
  assert.ok(typed.includes('serverMultiImage'),
            'typed send ships a list to a server that may not take one');
  assert.ok(rel.includes('serverMultiImage'),
            'spoken send ships a list to a server that may not take one');
});

t('the typed send still carries the one-image shape for an old server', () => {
  const typed = grab('sendTyped');
  assert.ok(/name:\s*take\[0\]\.name/.test(typed),
            'dropped the legacy top-level image shape');
});

t('unsent images stay queued rather than being dropped', () => {
  const typed = grab('sendTyped');
  assert.ok(typed.includes('attached.slice(take.length)'),
            'the remainder is not kept');
  assert.ok(/still attached/.test(typed), 'the remainder is kept silently');
});

console.log('  ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
