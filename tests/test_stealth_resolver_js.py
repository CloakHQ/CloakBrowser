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

function el(tag, text, kids){
  const e = { tagName: tag, textContent: text || '', children: kids || [] };
  e.contains = (o) => (o === e) || (e.children || []).some(c => c.contains && c.contains(o));
  return e;
}

function run(sel, matches, xpathMatches){
  const calls = { css: null, xpath: null };
  const document = {
    querySelectorAll(s){ calls.css = s; return (matches || []).slice(); },
    evaluate(xp){ calls.xpath = xp; const m = xpathMatches || [];
      return { snapshotLength: m.length, snapshotItem: i => m[i] }; },
  };
  const src = RESOLVER + `
    return (function(){
      const __SEL = ${JSON.stringify(sel)};
      const el = __resolve(__SEL);
      const cls = (el === 'UNSUPPORTED') ? 'unsupported' : (el === null ? 'not_found' : 'ok');
      return { cls, text: el && el.textContent, calls };
    })();`;
  return new Function('document', 'calls', 'XPathResult', src)(document, calls, { ORDERED_NODE_SNAPSHOT_TYPE: 7 });
}

let fails = 0;
function eq(name, got, want){
  if (got !== want){ fails++; console.log('FAIL ' + name + ' | got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want)); }
}

// :has-text on CSS, with trailing nth=0 (.first)
let r = run("button:has-text('Submit') >> nth=0", [ el('BUTTON','Submit'), el('BUTTON','other') ]);
eq('has-text cls', r.cls, 'ok'); eq('has-text css engine', r.calls.css, 'button'); eq('has-text picks match', r.text, 'Submit');

// plain CSS + .first
r = run('#x .c >> nth=0', [ el('SPAN','hi') ]); eq('plain css cls', r.cls, 'ok'); eq('plain css engine', r.calls.css, '#x .c');

// chaining and get_by_* engines are unsupported
eq('chaining', run('a >> b', [el('A')]).cls, 'unsupported');
eq('internal role', run('internal:role=button', []).cls, 'unsupported');

// xpath (explicit prefix and leading //)
r = run('xpath=//button', [], [ el('BUTTON','x') ]); eq('xpath= cls', r.cls, 'ok'); eq('xpath= arg', r.calls.xpath, '//button');
eq('// route', run('//button', [], [ el('BUTTON','x') ]).cls, 'ok');

// text= engine picks the innermost matching element
let inner = el('SPAN','hi'); let outer = el('DIV','hi',[inner]);
r = run('text=hi', [ outer, inner ]); eq('text= cls', r.cls, 'ok'); eq('text= smallest', r.text, 'hi');
eq('text exact quoted case-sensitive miss', run('text="Hi"', [ el('DIV','hi') ]).cls, 'not_found');

// :has-text with a regex arg is not reimplemented
eq('has-text regex', run(':has-text(/re/)', [ el('DIV','x') ]).cls, 'unsupported');

// multiple :has-text clauses AND together
r = run("div:has-text('a'):has-text('b')", [ el('DIV','a and b'), el('DIV','only a') ]);
eq('multi has-text cls', r.cls, 'ok'); eq('multi has-text css', r.calls.css, 'div'); eq('multi has-text match', r.text, 'a and b');

// nth variants
eq('.last (nth=-1)', run('button >> nth=-1', [ el('BUTTON','1'), el('BUTTON','2') ]).text, '2');
eq('nth=1', run('button >> nth=1', [ el('BUTTON','1'), el('BUTTON','2') ]).text, '2');

// css= prefix + genuine not-found
eq('css= prefix engine', run('css=button', [ el('BUTTON','1') ]).calls.css, 'button');
eq('not found', run('button', []).cls, 'not_found');

if (fails) { console.log(fails + ' FAILED'); process.exit(1); }
console.log('ALL PASS');
"""


def test_resolver_selector_semantics():
    import json
    script = _HARNESS % json.dumps(_RESOLVER_BODY)
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"resolver JS failed:\n{result.stdout}\n{result.stderr}"
    assert "ALL PASS" in result.stdout
