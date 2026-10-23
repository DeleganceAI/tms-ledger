// Admin chat widget: a launcher at the bottom right of every page that opens a chat panel.
// It renders nothing unless /dashboard/api/chat answers, which it only does for admins.
// One collection per chat, read-only; the conversation lives in this tab's sessionStorage.
(() => {
  const KEY = 'tms-chat';
  const css = `
  #tmsc-btn,#tmsc{color-scheme:dark;--bg:#2b2433;--panel:#342b3e;--line:#4a3f57;--ink:#f4efe6;--ink2:#cbbfd4;--ink3:#9d91a8;--accent:#8ab6f9;--accent2:#2f3a5c;--bad:#f4a6a0;
    --mono:ui-monospace,"SF Mono",Menlo,monospace;font:13px/1.45 Inter,system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink)}
  #tmsc-btn{position:fixed;right:18px;bottom:18px;z-index:2147483000;border:0;border-radius:999px;padding:10px 16px;background:var(--accent);color:#1e1826;font-weight:600;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.25)}
  #tmsc{position:fixed;right:18px;bottom:18px;z-index:2147483001;width:min(440px,calc(100vw - 24px));height:min(640px,calc(100vh - 36px));
    background:var(--panel);border:1px solid var(--line);border-radius:12px;box-shadow:0 18px 50px rgba(0,0,0,.3);display:flex;flex-direction:column;overflow:hidden;
    transform-origin:bottom right;animation:tmsc-in .16s ease-out}
  #tmsc[hidden],#tmsc-btn[hidden]{display:none}
  @keyframes tmsc-in{from{opacity:0;transform:translateY(12px) scale(.97)}to{opacity:1;transform:none}}
  @media(prefers-reduced-motion:reduce){#tmsc{animation:none}}
  #tmsc .hd{display:flex;align-items:center;gap:6px;padding:8px 10px;border-bottom:1px solid var(--line)}
  #tmsc .hd b{font-size:13px}#tmsc .hd .grow{flex:1}
  #tmsc select{font:inherit;font-size:12px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:2px 4px;max-width:150px}
  #tmsc .ib{background:none;border:1px solid var(--line);color:var(--ink2);border-radius:5px;padding:2px 7px;cursor:pointer;font:11px var(--mono)}
  #tmsc .sub{padding:3px 10px;color:var(--ink3);font:10.5px var(--mono);border-bottom:1px solid var(--line)}
  #tmsc .log{flex:1;overflow:auto;padding:10px;display:flex;flex-direction:column;gap:8px}
  #tmsc .empty{color:var(--ink3);font-size:12px}
  #tmsc .msg{white-space:pre-wrap;word-break:break-word}#tmsc .msg.user{align-self:flex-end;background:var(--accent2);padding:6px 10px;border-radius:10px;max-width:85%}
  #tmsc .msg.err{color:var(--bad);font:11px var(--mono)}
  #tmsc .md{white-space:normal}#tmsc .md p{white-space:pre-wrap}#tmsc .md>:first-child{margin-top:0}#tmsc .md>:last-child{margin-bottom:0}
  #tmsc .md p,#tmsc .md ul,#tmsc .md ol,#tmsc .md pre,#tmsc .md blockquote,#tmsc .md table{margin:0 0 8px}#tmsc .md ul,#tmsc .md ol{padding-left:20px}
  #tmsc .md h1,#tmsc .md h2,#tmsc .md h3,#tmsc .md h4{font-size:13.5px;margin:10px 0 4px}
  #tmsc .md code{font:11.5px var(--mono);background:var(--bg);padding:0 3px;border-radius:3px}#tmsc .md pre code{display:block;padding:6px 8px;overflow:auto}
  #tmsc .md blockquote{border-left:3px solid var(--line);padding-left:8px;color:var(--ink2)}
  #tmsc .md table{border-collapse:collapse;font-size:12px}#tmsc .md td,#tmsc .md th{border:1px solid var(--line);padding:2px 6px}
  #tmsc .md a{color:var(--accent)}
  #tmsc .tool{align-self:flex-start;border:1px solid var(--line);border-radius:6px;padding:2px 8px;font:11px var(--mono);color:var(--ink2)}
  #tmsc a.id{font-family:var(--mono);font-size:11px;color:var(--accent);background:var(--accent2);padding:0 3px;border-radius:3px;text-decoration:none}
  #tmsc form{display:flex;gap:6px;padding:8px;border-top:1px solid var(--line)}
  #tmsc textarea{flex:1;min-height:44px;max-height:140px;resize:vertical;font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 8px}
  #tmsc .go{background:var(--accent);color:#1e1826;border:0;border-radius:6px;padding:0 14px;cursor:pointer;font-weight:600}#tmsc .go:disabled{opacity:.5;cursor:default}`;
  // Answers can echo uploaded text, so rendered markdown keeps only these tags and safe links.
  const MD_TAGS = new Set(['P', 'BR', 'HR', 'STRONG', 'B', 'EM', 'I', 'DEL', 'CODE', 'PRE', 'BLOCKQUOTE', 'UL', 'OL', 'LI',
    'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD', 'A']);
  let markedReady = null;
  const loadMarked = () => markedReady ??= new Promise(ok => {
    if (window.marked) return ok();
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/marked@15.0.12/marked.min.js'; s.onload = s.onerror = () => ok();
    document.head.appendChild(s);
  });
  function idLinks(root) {  // 64-hex event ids in text become links to the record
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), nodes = [];
    while (walk.nextNode()) if (/\b[0-9a-f]{64}\b/.test(walk.currentNode.data) && !walk.currentNode.parentElement.closest('a')) nodes.push(walk.currentNode);
    for (const n of nodes) {
      const span = document.createElement('span');
      span.innerHTML = esc(n.data).replace(/\b[0-9a-f]{64}\b/g, id => `<a class="id" href="/dashboard#record=${id}" data-id="${id}" title="${id}">${id.slice(0, 10)}</a>`);
      n.replaceWith(...span.childNodes);
    }
  }
  function md(text) {
    // a <template> is inert: nothing in it loads or runs (no <img onerror>) while it is cleaned
    const tpl = document.createElement('template'), box = tpl.content;
    if (!window.marked) { const p = document.createElement('p'); p.textContent = text; box.append(p); }
    else tpl.innerHTML = marked.parse(text);
    for (const el of [...box.querySelectorAll('*')].reverse()) {
      if (!MD_TAGS.has(el.tagName)) { el.replaceWith(...el.childNodes); continue; }
      const href = el.tagName === 'A' ? el.getAttribute('href') || '' : '';
      for (const a of [...el.attributes]) el.removeAttribute(a.name);
      if (/^(https?:\/\/|\/(?!\/)|#)/i.test(href)) { el.setAttribute('href', href); if (!href.startsWith('/') && !href.startsWith('#')) { el.target = '_blank'; el.rel = 'noopener noreferrer'; } }
    }
    idLinks(box);
    const out = document.createElement('div'); out.append(box);
    return out.innerHTML;
  }
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  let C = {open: false, col: '', messages: [], log: []}, model = '', cols = [], busy = false;
  try { Object.assign(C, JSON.parse(sessionStorage.getItem(KEY) || '{}')); } catch {}
  const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(C)); } catch {} };

  fetch('/dashboard/api/chat').then(r => r.ok ? r.json() : null).then(d => {
    if (!d) return;  // not an admin: nothing on the page
    model = d.model; cols = d.collections;
    if (!cols.includes(C.col)) { C.col = cols[0] || ''; C.messages = []; C.log = []; }
    mount(d.configured);
  }).catch(() => {});

  function mount(configured) {
    document.head.insertAdjacentHTML('beforeend', `<style>${css}</style>`);
    document.body.insertAdjacentHTML('beforeend', `
      <button id="tmsc-btn" type="button" aria-haspopup="dialog" aria-controls="tmsc">Ask the ledger</button>
      <section id="tmsc" role="dialog" aria-label="Chat over a collection" hidden>
        <div class="hd"><b>Chat</b><select id="tmsc-col" aria-label="Collection">${cols.map(c => `<option>${esc(c)}</option>`).join('')}</select>
          <span class="grow"></span><button class="ib" id="tmsc-md" title="Export as Markdown">.md</button><button class="ib" id="tmsc-json" title="Export as JSON">.json</button>
          <button class="ib" id="tmsc-new" title="New chat">new</button><button class="ib" id="tmsc-x" title="Close (Esc)" aria-label="Close">✕</button></div>
        <div class="sub">${esc(model)} · read-only${configured ? '' : ' · no API key set'}</div>
        <div class="log" id="tmsc-log" aria-live="polite"></div>
        <form id="tmsc-form"><textarea id="tmsc-in" aria-label="Question" placeholder="Ask about this collection… Enter sends, Shift+Enter for a new line"></textarea><button class="go" id="tmsc-send">Send</button></form>
      </section>`);
    const $ = id => document.getElementById(id);
    $('tmsc-col').value = C.col;
    const show = open => {
      C.open = open; save();
      $('tmsc').hidden = !open; $('tmsc-btn').hidden = open;
      if (open) { render(); $('tmsc-in').focus(); } else $('tmsc-btn').focus();
    };
    $('tmsc-btn').onclick = () => show(true);
    $('tmsc-x').onclick = () => show(false);
    $('tmsc').addEventListener('keydown', e => { if (e.key === 'Escape') show(false); });
    $('tmsc-new').onclick = () => { C.messages = []; C.log = []; save(); render(); };
    $('tmsc-col').onchange = e => { C.col = e.target.value; C.messages = []; C.log = []; save(); render(); };  // a chat is bound to one collection
    $('tmsc-form').onsubmit = e => {
      e.preventDefault();
      const t = $('tmsc-in').value.trim();
      if (t && !busy && C.col) { $('tmsc-in').value = ''; send(t); }
    };
    $('tmsc-in').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('tmsc-form').requestSubmit(); } };
    // On the dashboard an id opens the record drawer; elsewhere it opens the dashboard on that record.
    $('tmsc-log').addEventListener('click', e => {
      const a = e.target.closest('a.id');
      if (a && typeof window.showDetail === 'function') { e.preventDefault(); window.showDetail(a.dataset.id); }
    });
    $('tmsc-md').onclick = () => download('md', `# Chat over ${C.col}\n\nModel: ${model} · exported ${new Date().toISOString()}\n\n` +
      C.log.map(e => e.type === 'user' ? `**You:** ${e.content}` : e.type === 'answer' ? `**Agent:** ${e.content}` : e.type === 'error' ? `> Error: ${e.error}`
        : `<details><summary>tool: ${e.name}</summary>\n\n\`\`\`json\n${JSON.stringify(e.args, null, 2)}\n\`\`\`\n\n\`\`\`json\n${e.result ?? ''}\n\`\`\`\n</details>`).join('\n\n') + '\n', 'text/markdown');
    $('tmsc-json').onclick = () => download('json', JSON.stringify({collection: C.col, model, exported_at: new Date().toISOString(),
      messages: C.messages, log: C.log}, null, 2), 'application/json');
    if (C.open) show(true);
    loadMarked().then(render);

    function render() {
      const ids = t => esc(t).replace(/\b[0-9a-f]{64}\b/g, id => `<a class="id" href="/dashboard#record=${id}" data-id="${id}" title="${id}">${id.slice(0, 10)}</a>`);
      $('tmsc-log').innerHTML = C.log.length ? C.log.map(e =>
        e.type === 'user' ? `<div class="msg user">${esc(e.content)}</div>`
        : e.type === 'answer' ? `<div class="msg md">${md(e.content)}</div>`
        : e.type === 'error' ? `<div class="msg err">${esc(e.error)}</div>`
        : `<div class="tool">${esc(e.name)}${e.result == null ? ' …' : ` · ${esc(e.ms)}ms`}</div>`).join('')  // arguments and results go in the exports
        : '<div class="empty">Ask a question about this collection. The agent can only read it, and every tool call it makes shows here.</div>';
      $('tmsc-log').scrollTop = $('tmsc-log').scrollHeight;
      $('tmsc-send').disabled = busy || !C.col;
    }

    async function send(text) {
      busy = true; C.log.push({type: 'user', content: text}); render();
      try {
        const r = await fetch('/dashboard/api/chat', {method: 'POST', headers: {'content-type': 'application/json'},
          body: JSON.stringify({collection: C.col, messages: [...C.messages, {role: 'user', content: text}]})});
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`);
        const reader = r.body.getReader(), dec = new TextDecoder();
        let buf = '';
        for (;;) {
          const {done, value} = await reader.read();
          if (done) break;
          buf += dec.decode(value, {stream: true});
          let i;
          while ((i = buf.indexOf('\n\n')) >= 0) {
            const line = buf.slice(0, i); buf = buf.slice(i + 2);
            if (!line.startsWith('data: ')) continue;
            const ev = JSON.parse(line.slice(6));
            if (ev.type === 'tool_call') C.log.push({...ev, result: null});
            else if (ev.type === 'tool_result') Object.assign(C.log.findLast(e => e.id === ev.id) || {}, {result: ev.result, ms: ev.ms});
            else if (ev.type === 'messages') C.messages = ev.messages;
            else C.log.push(ev);
            render();
          }
        }
      } catch (e) { C.log.push({type: 'error', error: String(e.message || e)}); }
      busy = false; save(); render();
    }
  }

  function download(ext, text, type) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], {type}));
    a.download = `chat-${C.col}-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')}.${ext}`;
    a.click(); URL.revokeObjectURL(a.href);
  }
})();
