import { describe, it, expect } from 'vitest';
import { OK, NOT_FOUND, UNSUPPORTED, STALE, EVALUATION_FAILED, buildSnapshotJs, buildValidateJs, buildPointerJs, parseResult, evalParsed } from '../src/human/stealthDom.js';

type E = any;
const defaultRect = () => ({ x: 1, y: 2, width: 10, height: 10 });
function node(tag:string, text='', cls=''):E {
  const e:any={tagName:tag.toUpperCase(),nodeType:1,childNodes:[],children:[],firstChild:null,parentElement:null,previousElementSibling:null,nextSibling:null,textContent:text,isConnected:true,disabled:false,readOnly:false,isContentEditable:false,type:'text',value:'',attrs:{},checked:false,style:{display:'block',visibility:'visible'},rect:defaultRect()};
  if(text){const t:any={nodeType:3,nodeValue:text,textContent:text,nextSibling:null,rect:defaultRect()};e.childNodes.push(t);e.firstChild=t;}
  e.getAttribute=(n:string)=>e.attrs[n]??null;e.hasAttribute=(n:string)=>n in e.attrs;e.contains=(x:E)=>x===e||e.children.some((c:E)=>c.contains(x));e.closest=()=>null;e.getRootNode=()=>e.parentElement?e.parentElement.getRootNode():doc;e.getBoundingClientRect=()=>e.rect;e.matches=(s:string)=>s==='*'||s.split('.').every((x,i)=>i?cls.split(' ').includes(x):!x||x===tag);return e;
}
let doc:any;
function append(p:E,c:E){const prev=p.childNodes.at(-1);if(prev)prev.nextSibling=c;c.nextSibling=null;c.parentElement=p;c.previousElementSibling=p.children.at(-1)??null;p.children.push(c);p.childNodes.push(c);p.firstChild=p.childNodes[0]??null;}
function wireOwner(n:E){n.ownerDocument=doc;for(const child of n.childNodes??[])wireOwner(child);}
function run(js:string, roots:E[], point?:E, active?:E, store:any={}){let selected:any=null;doc={children:roots,head:{contains:()=>false},getElementById:(id:string)=>{let hit:any=null;const walk=(n:any)=>{if(n.attrs&&n.attrs.id===id)hit=n;for(const c of n.children??[])walk(c);};for(const r of roots)walk(r);return hit;},activeElement:active??null,querySelectorAll:()=>[],elementFromPoint:()=>point??null,evaluate:()=>({snapshotLength:0,snapshotItem:()=>null}),createRange:()=>({selectNode:(n:any)=>{selected=n;},getBoundingClientRect:()=>selected?.rect??{x:0,y:0,width:0,height:0}})};for(const r of roots){r.getRootNode=()=>doc;wireOwner(r);}const f=new Function('document','XPathResult','getComputedStyle','globalThis','return '+js);return f(doc,{ORDERED_NODE_SNAPSHOT_TYPE:7},(e:E)=>e.style??{display:'block',visibility:'visible'},store);}

describe('protocol',()=>{it('strictly rejects malformed payloads and evaluator failures',async()=>{expect(parseResult({v:2,r:OK,targetId:1,gen:5})).toMatchObject({status:OK});for(const x of [null,{}, {v:1,r:OK,targetId:1,gen:5},{v:2,r:OK},{v:2,r:OK,targetId:1},{v:2,r:STALE,targetId:1.5,gen:5},{v:2,r:STALE,targetId:1,gen:1.5}])expect(parseResult(x)).toEqual({status:EVALUATION_FAILED});expect(parseResult({v:2,r:NOT_FOUND})).toEqual({status:NOT_FOUND});expect(parseResult({v:2,r:UNSUPPORTED})).toEqual({status:UNSUPPORTED});expect(await evalParsed({evaluate:async()=>{throw Error()}},'x')).toEqual({status:EVALUATION_FAILED});});});

describe('shipped resolver',()=>{it('unions only visible display:contents geometry, including nested content',()=>{const target=node('li','Hoy','target');target.style.display='contents';target.rect={x:0,y:0,width:0,height:0};target.childNodes[0].rect={x:5,y:6,width:25,height:10};const targetResult=run(buildSnapshotJs('.target'),[target]);expect(targetResult).toMatchObject({r:OK,visible:true,box:{x:5,y:6,width:25,height:10}});const union=node('div','','union');union.style.display='contents';union.rect={x:0,y:0,width:0,height:0};const left=node('span','left');left.rect={x:10,y:20,width:20,height:10};const right=node('span','right');right.rect={x:40,y:20,width:30,height:10};const nested=node('span','','nested');nested.style.display='contents';nested.rect={x:0,y:0,width:0,height:0};const nestedChild=node('span','nested');nestedChild.rect={x:75,y:20,width:25,height:10};append(nested,nestedChild);const hidden=node('span','hidden');hidden.style.visibility='hidden';hidden.rect={x:1000,y:1000,width:100,height:100};append(union,left);append(union,right);append(union,nested);append(union,hidden);expect(run(buildSnapshotJs('.union'),[union])).toMatchObject({r:OK,visible:true,box:{x:10,y:20,width:90,height:10}});const hiddenText=node('div','hidden text','hidden-text');hiddenText.style={display:'contents',visibility:'hidden'};hiddenText.rect={x:0,y:0,width:0,height:0};hiddenText.childNodes[0].rect={x:5,y:6,width:50,height:10};expect(run(buildSnapshotJs('.hidden-text'),[hiddenText])).toMatchObject({r:OK,visible:false,box:null});});it('executes descendant, child, adjacent, sibling, lists and structural has-text',()=>{const root=node('div');const a=node('span','one','a'), b=node('button','Save','b'), c=node('button','Other','c');append(root,a);append(root,b);append(root,c);for(const s of ['div button','div > button','.a + button','.a ~ button','.no, button:has-text("Save")'])expect(run(buildSnapshotJs(s),[root]).r).toBe(OK);});it('executes exact/lax/regex text and excludes script text (#512)',()=>{const r=node('div'), s=node('span',' Hello   World '), script=node('script','secret');append(r,s);append(r,script);expect(run(buildSnapshotJs('text="Hello World"'),[r]).r).toBe(OK);expect(run(buildSnapshotJs('text=hello world'),[r]).r).toBe(OK);expect(run(buildSnapshotJs('text=/world/i'),[r]).r).toBe(OK);expect(run(buildSnapshotJs('text=secret'),[r]).r).toBe(NOT_FOUND);});it('executes native and ARIA state',()=>{const root=node('div'),disabled=node('button','','disabled'),ariaDisabled=node('button','','aria-disabled'),readonly=node('div','','readonly');disabled.attrs.disabled='';ariaDisabled.attrs.role='button';ariaDisabled.attrs['aria-disabled']='true';readonly.attrs.role='textbox';readonly.attrs['aria-readonly']='true';append(root,disabled);append(root,ariaDisabled);append(root,readonly);expect(run(buildSnapshotJs('.disabled'),[root]).enabled).toBe(false);expect(run(buildSnapshotJs('.aria-disabled'),[root]).enabled).toBe(false);expect(run(buildSnapshotJs('.readonly'),[root]).editable).toBe(false);});it('executes deep shadow ordering, focus, hit testing and stale validation',()=>{const host=node('div'), light=node('button','light'), shadow=node('button','shadow');append(host,light);const disabled=node('button');disabled.attrs.disabled='';append(host,disabled);host.shadowRoot={children:[shadow],elementFromPoint:()=>shadow,activeElement:shadow};shadow.getRootNode=()=>host.shadowRoot;shadow.parentElement=null;expect(run(buildSnapshotJs('button >> nth=2'),[host],host,host).focused).toBe(true);expect(run(buildSnapshotJs('button >> nth=1'),[host]).enabled).toBe(false);expect(run(buildSnapshotJs('button'),[host],host,host).focused).toBe(false);expect(run(buildPointerJs('button >> nth=2',1,2),[host],host).hit).toBe(true);const world:any={};const snap=run(buildSnapshotJs('button'),[host],host,host,world);expect(run(buildValidateJs('button',snap.targetId,snap.gen,1,2),[host],host,host,world).r).toBe(OK);expect(run(buildValidateJs('button',999,snap.gen,1,2),[host],host,host,world).r).toBe(STALE);expect(run(buildValidateJs('button',snap.targetId,snap.gen+1,1,2),[host],host,host,world).r).toBe(STALE);expect(run(buildValidateJs('button',snap.targetId,snap.gen,1,2),[host],host,host,{}).r).toBe(STALE);});});

describe('internal engines',()=>{
  const id=(r:any)=>r.box?.x;   // distinct rects identify WHICH element matched

  it('internal:attr i-flag is case-insensitive SUBSTRING on the raw value',()=>{
    const root=node('div');
    const p1=node('input');p1.attrs.placeholder='Your Email';p1.rect={x:11,y:0,width:5,height:5};
    const t1=node('span');t1.attrs.title='  Go  ';t1.rect={x:22,y:0,width:5,height:5};
    append(root,p1);append(root,t1);
    // 'mail' matches 'Your Email' -- substring, not equality
    expect(id(run(buildSnapshotJs('internal:attr=[placeholder="mail"i]'),[root]))).toBe(11);
    // raw value: no trim, no whitespace normalization
    expect(run(buildSnapshotJs('internal:attr=[title="Go"s]'),[root]).r).toBe(NOT_FOUND);
    expect(id(run(buildSnapshotJs('internal:attr=[title="  Go  "s]'),[root]))).toBe(22);
    expect(id(run(buildSnapshotJs('internal:attr=[title="go"i]'),[root]))).toBe(22);
  });

  it('internal:testid is strict equality, never a prefix match',()=>{
    const root=node('div');
    const a=node('button');a.attrs['data-testid']='submit-button';a.rect={x:31,y:0,width:5,height:5};
    const b=node('button');b.attrs['data-testid']='submit';b.rect={x:32,y:0,width:5,height:5};
    append(root,a);append(root,b);
    expect(id(run(buildSnapshotJs('internal:testid=[data-testid="submit"s]'),[root]))).toBe(32);
    expect(run(buildSnapshotJs('internal:testid=[data-testid="sub"s]'),[root]).r).toBe(NOT_FOUND);
  });

  it('internal:attr supports a regex value and rejects unsupported grammar',()=>{
    const root=node('div');
    const el=node('span');el.attrs.title='Go42';el.rect={x:41,y:0,width:5,height:5};
    append(root,el);
    expect(id(run(buildSnapshotJs('internal:attr=[title=/^Go\\d+$/]'),[root]))).toBe(41);
    for(const bad of ['internal:attr=[title]','internal:attr=[title*="Go"]',
                      'internal:attr=[title=Go]','internal:attr=title="Go"'])
      expect(run(buildSnapshotJs(bad),[root]).r).toBe(UNSUPPORTED);
  });

  it('internal:text exact is the full subtree, unlike the public text= engine',()=>{
    const root=node('div');
    const btn=node('button','Hello');btn.rect={x:51,y:0,width:5,height:5};
    const span=node('span','World');span.rect={x:52,y:0,width:5,height:5};
    append(btn,span);append(root,btn);
    expect(id(run(buildSnapshotJs('internal:text="HelloWorld"s'),[root]))).toBe(51);
    // the public engine compares immediate fragments, so it does NOT match
    expect(run(buildSnapshotJs('text="HelloWorld"'),[root]).r).toBe(NOT_FOUND);
  });

  it('internal:text keeps the smallest match via direct children only',()=>{
    const root=node('div');
    const gp=node('div','X');gp.rect={x:61,y:0,width:5,height:5};
    const sect=node('section');sect.rect={x:62,y:0,width:5,height:5};
    const deep=node('span','X');deep.rect={x:63,y:0,width:5,height:5};
    append(sect,deep);append(gp,sect);append(root,gp);
    // section's own text matches too, so the innermost element wins
    expect(id(run(buildSnapshotJs('internal:text="X"s'),[root]))).toBe(63);
  });

  it('internal:label resolves labelledby, then aria-label, then native labels',()=>{
    const root=node('div');
    const ref=node('span','Referenced');ref.attrs.id='lbref';ref.rect={x:71,y:0,width:5,height:5};
    const byRef=node('input');byRef.attrs['aria-labelledby']='lbref';byRef.rect={x:72,y:0,width:5,height:5};
    const fallback=node('input');fallback.attrs['aria-labelledby']='missing';
    fallback.attrs['aria-label']='Fallback';fallback.rect={x:73,y:0,width:5,height:5};
    const native=node('input');native.rect={x:74,y:0,width:5,height:5};
    const lbl=node('label','Password');native.labels=[lbl];
    const divLabel=node('div','x');divLabel.attrs['aria-label']='Div Label';divLabel.rect={x:75,y:0,width:5,height:5};
    const hidden=node('input');hidden.type='hidden';hidden.rect={x:76,y:0,width:5,height:5};
    hidden.labels=[node('label','HiddenLabel')];
    for(const e of [ref,byRef,fallback,native,divLabel,hidden])append(root,e);
    expect(id(run(buildSnapshotJs('internal:label="Referenced"i'),[root]))).toBe(72);
    expect(id(run(buildSnapshotJs('internal:label="Fallback"i'),[root]))).toBe(73);
    expect(id(run(buildSnapshotJs('internal:label="Password"i'),[root]))).toBe(74);
    expect(id(run(buildSnapshotJs('internal:label="Div Label"i'),[root]))).toBe(75);
    // a hidden input contributes no native label
    expect(run(buildSnapshotJs('internal:label="HiddenLabel"i'),[root]).r).toBe(NOT_FOUND);
  });

  it('public text= excludes a shadow host whose shadow content also matches',()=>{
    // Regression: __elementText concatenates shadow text into the host, so the
    // host matches too. contains() cannot see into a shadow root, so the old
    // smallest-element filter kept the host and (being light DOM) returned it
    // first. Playwright returns the shadow child.
    const host=node('div','','host');host.rect={x:81,y:0,width:5,height:5};
    const shadowChild=node('button','ShadowText');shadowChild.rect={x:82,y:0,width:5,height:5};
    host.shadowRoot={children:[shadowChild],childNodes:[shadowChild],
                     elementFromPoint:()=>shadowChild,activeElement:null};
    shadowChild.getRootNode=()=>host.shadowRoot;shadowChild.parentElement=null;
    expect(id(run(buildSnapshotJs('text=ShadowText'),[host]))).toBe(82);
    expect(id(run(buildSnapshotJs('internal:text="ShadowText"i'),[host]))).toBe(82);
  });

  it('leaves role, chaining and single-quoted bodies unsupported',()=>{
    const root=node('div','x');
    for(const sel of ['internal:role=button[name="Go"i]','internal:has-text="Go"i',
                      'internal:control=enter-frame','#a >> #b',
                      "internal:text='Go'"])
      expect(run(buildSnapshotJs(sel),[root]).r).toBe(UNSUPPORTED);
  });
});
