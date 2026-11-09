// Minimal DOM host for the real installed React DOM reconciler. No mocked React
// hooks/reconciliation, network, browser session or production API is involved.
class TestNode {
  constructor(type, name, owner) {this.nodeType=type; this.nodeName=name; this.tagName=name; this.ownerDocument=owner; this.childNodes=[]; this.parentNode=null; this.attributes={}; this.style={}; this.namespaceURI='http://www.w3.org/1999/xhtml';}
  appendChild(n) {if(n.parentNode)n.parentNode.removeChild(n); this.childNodes.push(n); n.parentNode=this; return n;}
  insertBefore(n,b) {if(n.parentNode)n.parentNode.removeChild(n); const i=this.childNodes.indexOf(b); if(i<0)throw Error('NotFoundError');this.childNodes.splice(i,0,n);n.parentNode=this;return n;}
  removeChild(n) {const i=this.childNodes.indexOf(n);if(i<0)throw Error('NotFoundError');this.childNodes.splice(i,1);n.parentNode=null;return n;}
  get firstChild(){return this.childNodes[0]||null;}
  get options(){const all=n=>n.childNodes.flatMap(c=>[c,...all(c)]);return all(this).filter(n=>n.tagName==='OPTION');}
  get lastChild(){return this.childNodes.at(-1)||null;}
  get nextSibling(){return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this)+1]||null;}
  set textContent(v){if(this.nodeType===3){this._text=String(v);return;}for(const n of this.childNodes)n.parentNode=null;this.childNodes=[];if(v)this.appendChild(this.ownerDocument.createTextNode(String(v)));}
  get textContent(){return this.nodeType===3?(this._text||''):this.childNodes.map(n=>n.textContent).join('');}
  set nodeValue(v){this.textContent=v;} get nodeValue(){return this.textContent;}
  setAttribute(k,v){this.attributes[k]=String(v);}
  removeAttribute(k){delete this.attributes[k];}
  addEventListener(){} removeEventListener(){}
  focus(){this.ownerDocument.activeElement=this;}
  blur(){this.ownerDocument.activeElement=null;}
  getRootNode(){return this.parentNode?this.parentNode.getRootNode():this;}
  contains(n){return n===this||this.childNodes.some(c=>c.contains(n));}
}
const document = new TestNode(9,'#document');document.ownerDocument=document;
document.createElement=name=>new TestNode(1,name.toUpperCase(),document);
document.createElementNS=(ns,name)=>document.createElement(name);
document.createTextNode=text=>{const n=new TestNode(3,'#text',document);n.textContent=text;return n;};
document.documentElement=document.appendChild(document.createElement('html'));document.body=document.documentElement.appendChild(document.createElement('body'));
const window={document,HTMLElement:TestNode,HTMLIFrameElement:class {},addEventListener(){},removeEventListener(){}};
document.defaultView=window;global.window=window;global.document=document;

module.exports = { TestNode, document, window };
