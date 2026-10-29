'use strict';
window.I18n = (() => {
  // English source strings; Chinese translations live in locales.js.
  const pairs = window.APP_TRANSLATIONS;
  const en = new Map(pairs), zh = new Map(pairs.map(([a,b])=>[b,a]));
  let language = 'zh';
  try { language = (localStorage.getItem('key-press-detection-language')||localStorage.getItem('fasterrcnn-language')) === 'en' ? 'en' : 'zh'; } catch {}
  const interpolate = (value,params) => value.replace(/\{(\w+)\}/g,(_,key)=>String(params[key]??`{${key}}`));
  function t(source,params={}) {
    const translated = language==='en' ? (en.get(source)||source) : (zh.get(source)||source);
    return interpolate(translated,params);
  }
  function message(value) {
    const source=String(value??'');
    if(en.has(source)||zh.has(source)) return t(source);
    let m=source.match(/^(\w+) must be (a number|a boolean)\.$/);
    if(m)return t(m[2]==='a number'?"{key} must be a number.":"{key} must be a boolean.",{key:m[1]});
    return source; // Keep unrecognized diagnostics verbatim, including file paths.
  }
  const nodes=[],attributes=[];
  function bind(root=document.body) {
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
    let node;
    while((node=walker.nextNode())) {
      if(node.parentElement?.closest('[data-i18n-ignore],script,style'))continue;
      if(en.has(node.textContent.trim())||zh.has(node.textContent.trim()))nodes.push([node,node.textContent]);
    }
    root.querySelectorAll('[placeholder],[aria-label],[title],[alt]').forEach(el=>{
      for(const attr of ['placeholder','aria-label','title','alt']) {
        const value=el.getAttribute(attr); if(value&&(en.has(value)||zh.has(value)))attributes.push([el,attr,value]);
      }
    });
    apply();
  }
  function apply() {
    document.documentElement.lang=language==='zh'?'zh-CN':'en';
    for(const [node,source] of nodes)if(node.isConnected)node.textContent=source.replace(source.trim(),t(source.trim()));
    for(const [el,attr,source] of attributes)el.setAttribute(attr,t(source));
  }
  function set(value) {
    language=value==='en'?'en':'zh';
    try{localStorage.setItem('key-press-detection-language',language);}catch{}
    apply();
    document.dispatchEvent(new CustomEvent('languagechange'));
  }
  return {t,message,bind,set,get language(){return language;}};
})();
