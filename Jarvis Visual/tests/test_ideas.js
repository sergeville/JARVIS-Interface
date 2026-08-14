#!/usr/bin/env node
// Tests for the IDEAS panel -- renderIdeas() and ideasOpen().
//
// Serge, 2026-08-07 ~4:00 PM: "a header just on top of sessions... I'll click
// on that and boom, we have a brand new page that goes to the vault."
//
// This is the only panel on the page that is NOT about work, and most of what
// is asserted here is about it staying that way: nothing on it can start
// anything, and nothing on it counts.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const HTML = path.join(__dirname, '..', 'jarvis.html');
const src = fs.readFileSync(HTML, 'utf8');

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

// ---- DOM stub -------------------------------------------------------------
const nodes = {};
function makeNode(id) {
  return { id, innerHTML: '', style: {}, contains: () => false };
}
for (const id of ['ideas-sec', 'ideas-list', 'ideas', 'ideas-head']) {
  nodes[id] = makeNode(id);
}
const bodyClasses = new Set();
global.document = {
  getElementById: id => nodes[id] || null,
  body: { classList: {
    add: c => bodyClasses.add(c),
    remove: c => bodyClasses.delete(c),
    contains: c => bodyClasses.has(c),
  } },
  addEventListener: () => {},
};

let lastIdeasJson = '';
let ideasLatched = false;
let boardClosedCalls = 0;
function boardOpen(v) { if (v === false) boardClosedCalls++; }
// The vault constants are PARSED OUT of the page rather than restated here,
// so a change to either moves the tests with it instead of against them --
// same rule as BOARD_COLS in test_board.js.
const OBS_CONSTS = src.match(/const OBS_VAULT[\s\S]*?const OBS_NOTE[^\n]*\n/);
assert.ok(OBS_CONSTS, 'the vault link constants are gone from the page');
// setCount is pulled in from the page, not stubbed. renderIdeas gained a
// header count on 2026-08-09 and so genuinely depends on it; a stub here
// would let the real setter rot while these tests stayed green.
eval(OBS_CONSTS[0] + '\n' + grab('obsidianHref') + '\n'
   + grab('esc') + '\n' + grab('setCount') + '\n'
   + grab('renderIdeas') + '\n' + grab('ideasOpen'));

let passed = 0, failed = 0;
function test(name, fn) {
  lastIdeasJson = '';
  bodyClasses.clear();
  nodes['ideas-list'].innerHTML = '';
  nodes['ideas-sec'].style = {};
  try { fn(); passed++; console.log('ok   ' + name); }
  catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
}
const list = () => nodes['ideas-list'].innerHTML;
const I = (title, extra) =>
  Object.assign({ title, raised: '2026-08-07', gist: 'a gist' }, extra || {});

// ---- it shows the ideas ---------------------------------------------------

test('an idea draws its title, its gist and the date it was raised', () => {
  renderIdeas([I('A better mousetrap')]);
  const h = list();
  assert.ok(h.includes('A better mousetrap'), 'no title: ' + h);
  assert.ok(h.includes('a gist'), 'no gist: ' + h);
  assert.ok(h.includes('raised 2026-08-07'), 'no raised date: ' + h);
});

test('every idea is drawn, in the note\'s own order', () => {
  renderIdeas([I('First'), I('Second'), I('Third')]);
  const h = list();
  assert.ok(h.indexOf('First') < h.indexOf('Second'), 'order lost: ' + h);
  assert.ok(h.indexOf('Second') < h.indexOf('Third'), 'order lost: ' + h);
});

test('an idea with no gist still draws, without an empty box', () => {
  renderIdeas([{ title: 'Bare', raised: '', gist: '' }]);
  assert.ok(list().includes('Bare'), 'the idea vanished');
  assert.ok(!list().includes('class="ig"'), 'an empty gist row was drawn');
  assert.ok(!list().includes('raised'), 'an empty raised row was drawn');
});

// ---- the thinking, folded (Serge, 2026-08-07 ~6:00 PM) ---------------------
// "Is it possible to have everything that was spoken so I could see what's on
// file now?" The gist is one line; the argument is the point. It is FOLDED
// rather than always-open because five unrolled ideas would bury the list --
// his own EVENTS rule: fold, never truncate.

test('an idea with thinking carries every paragraph of it', () => {
  renderIdeas([{ title: 'T', raised: '', gist: '',
                 body: ['first thought', 'second thought'] }]);
  assert.ok(list().includes('first thought'), 'the thinking was dropped');
  assert.ok(list().includes('second thought'), 'only the first paragraph survived');
});

test('the thinking is marked foldable and says how much there is', () => {
  renderIdeas([{ title: 'T', raised: '', gist: '', body: ['a', 'b', 'c'] }]);
  assert.ok(/class="icard has-more"/.test(list()), 'the card is not foldable');
  // Read the VISIBLE label, not the whole HTML. The count also lives in the
  // element's data-shut attribute (the folded caption, kept there so the
  // render owns it and the click handler does not recompute it) -- and a
  // first version of this assertion matched THAT, so deleting the visible
  // count passed. Same trap as the two-identical-selectors miss: a guard that
  // matches the wrong occurrence guards nothing.
  const shown = list().match(/<div class="imore"[^>]*>([^<]*)<\/div>/);
  assert.ok(shown, 'the fold hint is gone');
  assert.ok(/3 more/.test(shown[1]),
    'the fold does not say how much is hidden: ' + shown[1]);
});

test('an idea with NO thinking is not dressed up as foldable', () => {
  // A card that invites a click and then does nothing is worse than a plain
  // one. Most of the panel will be these.
  renderIdeas([{ title: 'T', raised: '', gist: 'g', body: [] }]);
  assert.ok(!/has-more/.test(list()), 'a bodyless idea claims to have more');
  assert.ok(!/imore/.test(list()), 'a bodyless idea draws a fold hint');
  assert.ok(!/tabindex/.test(list()), 'a bodyless idea is focusable for nothing');
});

test('an OLD server with no body field does not break the panel', () => {
  // The page reloads on its own; the server needs Serge to restart it. So the
  // page WILL run against a server that knows nothing about bodies, and it has
  // to render the old shape rather than throw.
  assert.doesNotThrow(() => renderIdeas([{ title: 'T', raised: '', gist: 'g' }]));
  assert.ok(list().includes('T'));
  assert.ok(!/has-more/.test(list()));
});

test('THE THINKING IS ESCAPED -- the note is hand-editable and this reaches the DOM', () => {
  renderIdeas([{ title: 'T', raised: '', gist: '',
                 body: ['<img src=x onerror=alert(1)>'] }]);
  assert.ok(!/<img/.test(list()), 'markup from the vault reached the DOM');
  assert.ok(/&lt;img/.test(list()), 'the paragraph was dropped instead of escaped');
});

test('the fold is a fold -- nothing on an idea can start, open or change anything', () => {
  // The panel is read-only BY CONSTRUCTION; that is the whole reason ideas
  // live apart from the board. A click handler is the obvious place for that
  // to erode, so the handler is read here.
  const h = src.match(/function wireIdeaFold\(\)\{[\s\S]*?\n\}\)\(\);/);
  assert.ok(h, 'the fold wiring is gone');
  for (const forbidden of ['move_task', 'task-move', 'task_move', 'ws.send',
                           'approval', 'location', 'window.open']) {
    assert.ok(!h[0].includes(forbidden),
      'the ideas panel reaches out via ' + forbidden + ' -- it is read-only');
  }
  // NARROWED 2026-08-07, not weakened. The ban used to be on `fetch(` itself,
  // which was right while the panel fetched nothing -- then the transcript
  // landed, and a bare-`fetch` ban would have outlawed a READ. The property
  // was never "no network"; it is "nothing here CHANGES anything". So what is
  // guarded now is that every reach-out is a plain GET: no method, no body,
  // no verb of any kind. A POST from this panel still trips this test.
  for (const write of ['method:', "method :", 'POST', 'PUT', 'DELETE',
                       'body:', 'FormData']) {
    assert.ok(!h[0].includes(write),
      'the ideas panel makes a WRITE request (' + write + ') -- an idea is '
      + 'not work, and nothing on this panel may change anything');
  }
});

test('the fold is delegated to the list, not bound per card', () => {
  // renderIdeas rebuilds the list HTML on every change, so per-card handlers
  // would be thrown away with it and the fold would go dead after a poll.
  const h = src.match(/function wireIdeaFold\(\)\{[\s\S]*?\n\}\)\(\);/)[0];
  assert.ok(/list\.addEventListener\('click'/.test(h),
    'the click is not delegated to the list');
});

test('an empty queue HIDES the panel rather than drawing a heading over nothing', () => {
  renderIdeas([I('x')]);
  assert.strictEqual(nodes['ideas-sec'].style.display, '');
  renderIdeas([]);
  assert.strictEqual(nodes['ideas-sec'].style.display, 'none',
    'an empty panel is chrome, not information');
  assert.strictEqual(list(), '', 'stale ideas left behind after emptying');
});

test('emptying the note also CLOSES the sheet', () => {
  // Otherwise the sheet hangs open over the stage with nothing in it and
  // no heading left to click to close it.
  renderIdeas([I('x')]);
  ideasOpen(true);
  assert.ok(bodyClasses.has('ideas-open'));
  renderIdeas([]);
  assert.ok(!bodyClasses.has('ideas-open'), 'the empty sheet stayed open');
});

// ---- it is not a board ----------------------------------------------------

test('a card offers NO control that could start anything', () => {
  // The whole point of the panel. An approve, a move, a drag handle or a
  // status here would make it possible to promote an idea without Serge --
  // which is the one thing the split between the two notes exists to stop.
  renderIdeas([I('A tempting idea')]);
  const h = list();
  for (const bad of ['<button', 'draggable', 'data-act', 'data-status']) {
    assert.ok(!h.includes(bad),
      'the ideas panel grew a control (' + bad + '): ' + h);
  }
});

test('NOTHING on a card counts elapsed time', () => {
  // The hard line, and it is a decision rather than an omission: the board
  // is the half of this system allowed to nag. If this panel starts telling
  // Serge an idea has waited eleven days, he stops saying half-formed
  // things, and that is where the good ones start.
  renderIdeas([I('Old thought', { raised: '2020-01-01' })]);
  const h = list().toLowerCase();
  for (const word of ['days', 'ago', 'stale', 'overdue', 'waiting since']) {
    assert.ok(!h.includes(word),
      'the panel counted how long an idea has waited ("' + word + '"): ' + h);
  }
});

test('a title carrying HTML is escaped', () => {
  // The note is hand-edited and this value reaches the DOM.
  renderIdeas([I('<img src=x onerror=alert(1)>')]);
  assert.ok(!list().includes('<img'), 'markup from the note reached the DOM');
  assert.ok(list().includes('&lt;img'), 'not escaped: ' + list());
});

// ---- opening and closing --------------------------------------------------

test('opening the ideas sheet CLOSES the board', () => {
  // Both sheets are fixed at the same place. Open together, one sits
  // invisibly under the other and his click lands on the wrong thing.
  boardClosedCalls = 0;
  ideasOpen(true);
  assert.strictEqual(boardClosedCalls, 1, 'the board was left open underneath');
});

test('closing drops the latch, so the next click opens again', () => {
  ideasOpen(true);
  ideasLatched = true;
  ideasOpen(false);
  assert.strictEqual(ideasLatched, false, 'the latch stuck shut');
  assert.ok(!bodyClasses.has('ideas-open'));
});

test('a redraw with unchanged data does not rebuild the DOM', () => {
  // The poll runs at 15 Hz. A rebuild on every tick would reset his scroll
  // mid-read -- the same catch the board already carries.
  renderIdeas([I('Steady')]);
  nodes['ideas-list'].innerHTML = 'SENTINEL';
  renderIdeas([I('Steady')]);
  assert.strictEqual(list(), 'SENTINEL', 'the panel rebuilt for no change');
});

// ---- the heading is a heading, not a button -------------------------------

test('the ideas heading carries NO border', () => {
  // This page's own rule: a border says pressable. The heading reacts to a
  // click but is styled as a section title, exactly like Sessions.
  const m = src.match(/#ideas-head \{([^}]*)\}/);
  assert.ok(m, 'the #ideas-head rule is gone');
  assert.ok(!/(^|[^-])border:/.test(m[1]),
    'the ideas heading grew a border: ' + m[1].trim());
});

test('the ideas heading sits ABOVE the sessions card', () => {
  // Serge placed it: "a header just on top of sessions".
  const i = src.indexOf('id="ideas-sec"');
  const j = src.indexOf('<div id="sessions"');
  assert.ok(i !== -1 && j !== -1, 'a section is missing');
  assert.ok(i < j, 'ideas is no longer above sessions');
});

test('the sheet says out loud that it is read-only', () => {
  // A panel that looks like the board must say how it differs, or it will
  // be read as one.
  const m = src.match(/class="isheet-foot"[^>]*>([\s\S]*?)<\/div>/);
  assert.ok(m, 'the ideas sheet lost its footer');
  assert.ok(/read-only/i.test(m[1]), 'the footer no longer says read-only');
});

// ---- the spoken words behind an idea --------------------------------------
// Serge, 2026-08-07 ~6:12 PM: "and then we figured it would be transcript."
// (Appended ABOVE the exit line on purpose -- twelve board tests were once
// added below one and silently never ran.)

test('the transcript block lives OUTSIDE the capped .ib fold', () => {
  // .ib is capped at 1400px so its fold can animate. A conversation put
  // inside it would be clipped, which is the "a line you cannot read is a
  // line never said" failure wearing a stylesheet.
  const render = grab('renderIdeas');
  const ib = render.indexOf('class="ib"');
  const wrap = render.indexOf('itxwrap');
  assert.ok(ib !== -1 && wrap !== -1, 'the idea card lost a block');
  assert.ok(render.indexOf('</div>', ib) < wrap,
    'the transcript block is nested inside the height-capped .ib fold');
});

test('every spoken line goes through esc()', () => {
  // The transcript is a verbatim recording of a human talking and it reaches
  // innerHTML. It is data, never markup -- same rule as the idea body.
  const i = src.indexOf("fetch('/idea-transcript");
  assert.ok(i !== -1, 'the transcript fetch is gone');
  const block = src.slice(i, i + 2600);
  for (const field of ['ln.text', 'ln.t', 'win.date', 'win.from', 'win.to']) {
    assert.ok(block.includes('esc(' + field + ')'),
      field + ' reaches the DOM without esc()');
  }
});

test('the window it is showing is LABELLED, never implied', () => {
  // The note's times are approximate, so this is a stretch of the day around
  // a remembered moment. Showing it unlabelled turns a window into a claim.
  const i = src.indexOf("fetch('/idea-transcript");
  const block = src.slice(i, i + 2600);
  assert.ok(/class="txw"/.test(block) && /win\.from/.test(block)
            && /win\.to/.test(block),
    'the transcript renders lines with no window heading');
});

test('a shortfall is said out loud rather than served as silence', () => {
  const i = src.indexOf("fetch('/idea-transcript");
  const block = src.slice(i, i + 2600);
  assert.ok(/d\.dropped/.test(block),
    'a capped answer is served without saying it was capped');
  assert.ok(/d\.why/.test(block),
    'an empty answer renders as nothing at all, with no reason given');
});

test('clicking inside the transcript does not fold the card shut', () => {
  // Selecting a line to read it would otherwise close the card holding it.
  const i = src.indexOf("list.addEventListener('click'");
  assert.ok(i !== -1, 'the idea click handler is gone');
  const block = src.slice(i, i + 400);
  assert.ok(/closest\('\.itxwrap'\)/.test(block) && /return/.test(block),
    'a click in the transcript still reaches the fold toggle');
});

test('the transcript is fetched on the click, never polled', () => {
  // It must not creep into the /signals tick -- that pays all day for
  // something looked at occasionally.
  assert.ok(!grab('renderIdeas').includes('/idea-transcript'),
    'renderIdeas fetches transcripts as part of the render');
});

// ---- the way out to the vault ---------------------------------------------
// Serge, 2026-08-07 ~8:35 PM: "maybe there should be a link to Obsidian and
// the exact point." (Appended ABOVE the exit line on purpose -- twelve board
// tests were once added below one and silently never ran.)

test('every idea carries a link to its own heading in the vault note', () => {
  renderIdeas([{ title: 'A New Look', raised: '', gist: '' }]);
  const h = list();
  assert.ok(/class="iobs"/.test(h), 'the vault link is gone from the card');
  // `&` is written as `&amp;` because this is an ATTRIBUTE, not a URL bar --
  // esc() is still the right answer for anything reaching the DOM, and the
  // browser hands the decoded form to the OS.
  assert.ok(/href="obsidian:\/\/open\?vault=Jarvis-brain&amp;file=Ideas%23A%20New%20Look"/
    .test(h), 'the link does not aim at the idea\'s own heading: ' + h);
});

test('THE VAULT AND THE NOTE ARE CONSTANTS -- never read from the note', () => {
  // The one thing on this page whose value is handed to the OPERATING SYSTEM.
  // A note that could name its own vault could point this link at anything.
  const f = grab('obsidianHref');
  assert.ok(/vault=['"]\s*\+\s*encodeURIComponent\(OBS_VAULT\)/.test(f),
    'the vault name is no longer the pinned constant, encoded');
  assert.ok(/OBS_VAULT/.test(f) && /OBS_NOTE/.test(f),
    'the constants are gone -- the target is assembled from somewhere else');
  assert.ok(/const OBS_VAULT\s*=\s*'Jarvis-brain'/.test(src),
    'the vault constant no longer names the real vault');
});

test('A TITLE CANNOT ADD A PARAMETER, AN ACTION, OR A SECOND NOTE', () => {
  // Ideas.md is hand-editable, so a heading is untrusted input. Raw, an `&`
  // is structure; encoded, it is punctuation. This is the whole guard.
  renderIdeas([{ title: 'x&action=delete&file=Secret', raised: '', gist: '' }]);
  const m = list().match(/href="([^"]*)"/);
  assert.ok(m, 'the link lost its href');
  const href = m[1].replace(/&amp;/g, '&');
  assert.strictEqual(href.split('&').length, 2,
    'a title injected a second parameter into the URL: ' + href);
  assert.ok(!/action=delete/.test(href), 'a title reached the URL as an ACTION');
  assert.ok(/%26action%3Ddelete/.test(href),
    'the title was not percent-encoded into the file value');
});

test('a title cannot break out of the href attribute, or change the scheme',
  () => {
    renderIdeas([{ title: '" onclick="alert(1)', raised: '', gist: '' }]);
    const h = list();
    assert.ok(!/onclick/.test(h) || /&quot;|%22/.test(h),
      'a title escaped its own attribute');
    // Whatever a title says, the scheme is ours and there is exactly one.
    for (const bad of ['javascript:', 'data:', 'file:', 'obsidian://new',
                       'obsidian://advanced-uri']) {
      assert.ok(!h.includes(bad), 'the card can reach ' + bad);
    }
    assert.strictEqual((h.match(/obsidian:\/\//g) || []).length, 1,
      'a card carries more than one vault link');
  });

test('an idea with no title still links to the note, never to a dead heading',
  () => {
    renderIdeas([{ title: '', raised: '', gist: 'g' }]);
    const href = list().match(/href="([^"]*)"/)[1];
    assert.ok(/file=Ideas$/.test(href),
      'a titleless card points at a heading that cannot exist: ' + href);
  });

test('the link sits OUTSIDE the fold, so a shut card still offers it', () => {
  // A link you must unfold something to find is a link used once.
  const r = grab('renderIdeas');
  const link = r.indexOf('class="iobs"');
  const fold = r.indexOf('class="ib"');
  assert.ok(link !== -1 && fold !== -1, 'the card lost a piece');
  assert.ok(link < fold, 'the vault link moved inside the collapsing body');
});

test('following the link does not fold the card shut behind you', () => {
  const i = src.indexOf("list.addEventListener('click'");
  const block = src.slice(i, i + 500);
  assert.ok(/closest\('\.iobs'\)/.test(block),
    'a click on the vault link still reaches the fold toggle');
});

test('the way out is a LINK -- the panel still changes nothing', () => {
  // The read-only property was never "the panel goes nowhere"; it is
  // "the panel changes nothing". A plain anchor reads. A verb does not.
  const f = grab('obsidianHref');
  for (const verb of ['fetch', 'XMLHttpRequest', 'method:', 'POST', 'body:',
                      'ws.send', 'task_move', 'localStorage']) {
    assert.ok(!f.includes(verb),
      'the vault link grew a verb (' + verb + ') -- it must only READ');
  }
  assert.ok(!/window\.open|location\s*=/.test(grab('renderIdeas')),
    'the card navigates by script instead of by anchor');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
