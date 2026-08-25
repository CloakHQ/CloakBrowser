"""Resolver-JS selector-semantics tests.

``cloakbrowser/human/stealth_dom.py`` embeds a JavaScript selector resolver that
runs in the browser's isolated world. Its selector *semantics* (``:has-text``,
``text=``, ``xpath=``, trailing ``>> nth=N``, and the unsupported-grammar
fallback) can't be exercised from pure Python — they need a JS engine + DOM.

This test extracts the exact ``_RESOLVER_BODY`` string that ships and runs it
under Node against recording DOM stubs, asserting each selector routes to the
right engine / element (or reports ``unsupported``). Skipped when ``node`` is not
on PATH; CI has Node (the JS wrapper builds there).
"""
import shutil
import subprocess

import pytest

from cloakbrowser.human.stealth_dom import _RESOLVER_BODY

node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not on PATH")

# Harness: define the shipped resolver body, then drive __resolve() with a
# recording DOM. querySelectorAll/evaluate record their args and return
# caller-supplied matches, so we assert both the classification and the engine.
_HARNESS = r"""
const RESOLVER = %s;

function el(tag, text, kids, attrs){
  attrs = attrs || {};
  const e = {
    tagName: tag, textContent: text || '', children: kids || [],
    id: attrs.id || '', className: attrs.className || '', parentElement: null,
  };
  for (let i = 0; i < e.children.length; i++) {
    e.children[i].parentElement = e;
    e.children[i].previousElementSibling = i ? e.children[i - 1] : null;
  }
  e.contains = (o) => (o === e) || e.children.some(c => c.contains && c.contains(o));
  e.matches = (s) => {
    if (s === '*') return true;
    const id = s.match(/#([\w-]+)/); if (id && e.id !== id[1]) return false;
    const cls = s.match(/\.([\w-]+)/); if (cls && !e.className.split(/\s+/).includes(cls[1])) return false;
    const tagMatch = s.match(/^[a-zA-Z][\w-]*/); if (tagMatch && e.tagName.toLowerCase() !== tagMatch[0].toLowerCase()) return false;
    return true;
  };
  return e;
}

function run(sel, matches, xpathMatches){
  const calls = { css: null, xpath: null };
  const roots = (matches || []).filter(e => !e.parentElement);
  const document = {
    children: roots,
    head: { contains(){ return false; } },
    querySelectorAll(s){ calls.css = s; return (matches || []).slice(); },
    evaluate(xp){ calls.xpath = xp; const m = xpathMatches || [];
      return { snapshotLength: m.length, snapshotItem: i => m[i] }; },
  };
  const src = RESOLVER + `
    return (function(){
      const __SEL = ${JSON.stringify(sel)};
      const el = __resolve(__SEL);
      const cls = (el === 'UNSUPPORTED') ? 'unsupported' : (el === null ? 'not_found' : 'ok');
      return { cls, text: el && el.textContent, tag: el && el.tagName, calls };
    })();`;
  return new Function('document', 'calls', 'XPathResult', src)(document, calls, { ORDERED_NODE_SNAPSHOT_TYPE: 7 });
}

let fails = 0;
function eq(name, got, want){
  if (got !== want){ fails++; console.log('FAIL ' + name + ' | got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want)); }
}

// :has-text on CSS, with trailing nth=0 (.first)
let r = run("button:has-text('Submit') >> nth=0", [ el('BUTTON','Submit'), el('BUTTON','other') ]);
eq('has-text cls', r.cls, 'ok'); eq('has-text picks match', r.text, 'Submit');

// :has-text stays attached to its compound before a combinator.
let correct = el('BUTTON','Go',[],{id:'correct'}); let wrong = el('BUTTON','Wanted',[],{id:'wrong'});
let wantedArticle = el('ARTICLE','Wanted',[correct]); let otherArticle = el('ARTICLE','Other Wanted',[wrong]);
r = run('article:has-text("Wanted") > button', [ wantedArticle, otherArticle ]);
eq('structural has-text target', r.text, 'Go');

// plain CSS + .first
let plainChild = el('SPAN','hi',[],{className:'c'}); let plainParent = el('DIV','hi',[plainChild],{id:'x'});
r = run('#x .c >> nth=0', [ plainParent ]); eq('plain css cls', r.cls, 'ok'); eq('plain css target', r.tag, 'SPAN');

// Playwright orders all light-DOM matches before open-shadow matches.
let shadowButton = el('BUTTON','shadow',[],{id:'shadow'});
let shadowHost = el('DIV','host',[],{id:'host'});
shadowHost.shadowRoot = { children: [shadowButton] };
let normalButton = el('BUTTON','normal',[],{id:'normal'});
r = run('button >> nth=0', [shadowHost, normalButton]);
eq('mixed shadow first', r.text, 'normal');
r = run('button >> nth=1', [shadowHost, normalButton]);
eq('mixed shadow second', r.text, 'shadow');

// chaining and the get_by_* engines we do NOT reimplement stay unsupported
eq('chaining', run('a >> b', [el('A')]).cls, 'unsupported');
eq('internal role', run('internal:role=button', []).cls, 'unsupported');
for (const sel of ['internal:has-text="Go"i', 'internal:has="x"', 'internal:and="x"',
                   'internal:or="x"', 'internal:chain="x"', 'internal:control=enter-frame'])
  eq('unsupported ' + sel, run(sel, []).cls, 'unsupported');

// Engines we DO reimplement route to their engine rather than bailing out.
// (Semantics live in the browser/stub tiers; el() has no childNodes, so text
// comparisons here cannot distinguish full-subtree from immediate fragments.)
eq('internal text routes', run('internal:text="Submit"s', [el('BUTTON','Submit')]).cls, 'ok');
eq('internal text lax routes', run('internal:text=submit', [el('BUTTON','Submit')]).cls, 'ok');
eq('internal text no match', run('internal:text="Nope"s', [el('BUTTON','Submit')]).cls, 'not_found');
// A single-quoted internal body reaches JSON.parse in Playwright and throws.
eq('internal text single quotes', run("internal:text='Submit'", [el('BUTTON','Submit')]).cls, 'unsupported');
// Malformed attribute bodies and unsupported operators are refused, not guessed.
for (const sel of ['internal:attr=[placeholder]', 'internal:attr=[placeholder*="a"]',
                   'internal:attr=[placeholder=a]', 'internal:attr=placeholder="a"'])
  eq('bad attr body ' + sel, run(sel, []).cls, 'unsupported');
// The '>>' guard runs first, so a quoted argument containing '>>' is refused
// (a documented, deliberate under-match) while a trailing nth= still works.
eq('internal text with >> in arg', run('internal:text="a >> b"i', []).cls, 'unsupported');
eq('internal chained', run('internal:text="a"i >> internal:text="b"i', []).cls, 'unsupported');
eq('internal text keeps nth', run('internal:text=submit >> nth=1',
   [el('BUTTON','Submit'), el('BUTTON','Submit two')]).cls, 'ok');

// xpath (explicit prefix and leading //)
r = run('xpath=//button', [], [ el('BUTTON','x') ]); eq('xpath= cls', r.cls, 'ok'); eq('xpath= arg', r.calls.xpath, '//button');
eq('// route', run('//button', [], [ el('BUTTON','x') ]).cls, 'ok');

// text= engine picks the innermost matching element
let inner = el('SPAN','hi'); let outer = el('DIV','hi',[inner]);
r = run('text=hi', [ outer, inner ]); eq('text= cls', r.cls, 'ok'); eq('text= smallest', r.text, 'hi');
eq('text exact quoted case-sensitive miss', run('text="Hi"', [ el('DIV','hi') ]).cls, 'not_found');

// Playwright text extraction skips non-user-content elements.
r = run('text=Hoy', [ el('SCRIPT','Hoy'), el('LI','Hoy') ]);
eq('text skips script', r.cls, 'ok'); eq('text skips script target', r.tag, 'LI');

// Regex, button-like input values, and zero-width normalization.
eq('text regex', run('text=/^Alpha\\d+$/', [ el('BUTTON','Alpha42') ]).cls, 'ok');
let input = el('INPUT',''); input.type = 'button'; input.value = 'Submit Me';
eq('text input value', run('text=Submit Me', [ input ]).cls, 'ok');
eq('text zero width', run('text=foobar', [ el('BUTTON','foo\u200bbar') ]).cls, 'ok');

// :has-text with a regex arg is not reimplemented
eq('has-text regex', run(':has-text(/re/)', [ el('DIV','x') ]).cls, 'unsupported');

// multiple :has-text clauses AND together
r = run("div:has-text('a'):has-text('b')", [ el('DIV','a and b'), el('DIV','only a') ]);
eq('multi has-text cls', r.cls, 'ok'); eq('multi has-text match', r.text, 'a and b');

// nth variants
eq('.last (nth=-1)', run('button >> nth=-1', [ el('BUTTON','1'), el('BUTTON','2') ]).text, '2');
eq('nth=1', run('button >> nth=1', [ el('BUTTON','1'), el('BUTTON','2') ]).text, '2');

// css= prefix, selector lists, and genuine not-found
eq('css= prefix', run('css=button', [ el('BUTTON','1') ]).cls, 'ok');
r = run('button, a', [ el('A','first'), el('BUTTON','second') ]);
eq('selector list cls', r.cls, 'ok'); eq('selector list DOM order', r.tag, 'A');
eq('not found', run('button', []).cls, 'not_found');

// The world generation must fit an Int32: the .NET wrapper carries it as one,
// and an out-of-range value makes every .NET snapshot fail to parse (Snap()
// uses TryGetInt32, so an overflowing gen breaks every humanized .NET action).
const genOnce = new Function(RESOLVER + '\nreturn __state().gen;');
for (let i = 0; i < 200; i++) {
  delete globalThis['__cloakHumanDomV1'];
  const g = genOnce();
  if (!(Number.isInteger(g) && g >= 0 && g <= 2147483647)) {
    fails++; console.log('FAIL gen out of Int32 range | got ' + g);
    break;
  }
}
delete globalThis['__cloakHumanDomV1'];

if (fails) { console.log(fails + ' FAILED'); process.exit(1); }
console.log('ALL PASS');
"""


def test_resolver_selector_semantics():
    import json
    script = _HARNESS % json.dumps(_RESOLVER_BODY)
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"resolver JS failed:\n{result.stdout}\n{result.stderr}"
    assert "ALL PASS" in result.stdout
