"""The header every page shares, defined once. Pages put <!--HEADER--> where it goes; the handler
that serves the page fills it in with header(), which knows from the cookie alone (no query)
whether to show the signed-in links. site.css and site.js style it and run its menus.
"""
from __future__ import annotations

import hashlib
from html import escape
from pathlib import Path

# In the /site.css and /site.js URLs, so a deploy that changes either file isn't served from cache.
VERSION = hashlib.sha256(b"".join(Path(__file__).with_name(f).read_bytes() for f in ("site.css", "site.js"))).hexdigest()[:10]

GITHUB = ('<a class="gh" href="https://github.com/DeleganceAI/tms-ledger" target="_blank" rel="noopener" title="Source on GitHub">'
          '<svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor" aria-hidden="true"><path d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z"/></svg>GitHub</a>')
LOGO = ('<a id="brand" href="/" aria-label="Paranoy home"><svg viewBox="4 10 78 88" aria-hidden="true"><g fill="none" stroke-linecap="round">'
        '<path stroke="currentColor" stroke-width="5" d="M10 86 C18 92 25 85 28 73 C31 59 33 47 36 36"/><circle stroke="currentColor" stroke-width="5" cx="56" cy="36" r="20"/>'
        '<path stroke="currentColor" stroke-width="1.25" d="M38.5 36H73.5M56 18.5V53.5"/><circle stroke="#EF9F27" stroke-width="2" cx="56" cy="36" r="6.5"/></g></svg><span>aranoy</span></a>')
# The dashboard's sections: the second bar, pinned on the dashboard and popping up from its link elsewhere.
DASHBOARD = [("collections", "Overview"), ("activity", "Activity"), ("browse", "Browse"), ("agents", "Agents"), ("npubs", "Npubs"), ("sources", "Sources")]


def header(signed_in: bool, path: str) -> str:
    def link(href: str, text: str) -> str:
        here = path == href or (href != "/" and path.startswith(href + "/"))
        cur = ' aria-current="page"' if here else ""
        return f'<a href="{href}"{cur}>{escape(text)}</a>'
    on_dash = path == "/dashboard"
    sub = "".join(f'<a href="/dashboard#{k}" data-tab="{k}"{" hidden" if k == "npubs" else ""}>{v}</a>' for k, v in DASHBOARD)
    if signed_in:
        links = (link("/", "Collections") + link("/submit", "Submit")
                 + f'<div class="dd">{link("/dashboard", "Dashboard")}<button class="dd-btn" type="button" aria-expanded="false" '
                   f'aria-controls="subnav" aria-label="Dashboard sections">▾</button><div class="mini">{sub}</div></div>'
                 + link("/communities", "Communities") + link("/docs", "Docs")
                 + f'<span class="end"><a id="who-name" href="/connect" title="Your account">Account</a>'
                   f'<button class="btn ghost" id="logout" type="button">Log out</button>{GITHUB}</span>')
    else:
        links = (link("/communities", "Communities") + link("/docs", "Docs") + link("/office", "Office")
                 + f'<span class="end">{GITHUB}<a class="btn ghost" href="/connect">Log in</a><a class="btn" href="/connect#signup">Sign up</a></span>')
    subnav = (f'<nav class="subnav{" pinned" if on_dash else ""}" id="subnav" aria-label="Dashboard sections">{sub}</nav>'
              if signed_in else "")
    chat = '<script src="/chat.js" defer></script>' if signed_in else ""  # the chat is for signed-in people only
    cta = "" if signed_in else '<a class="btn cta-m" href="/connect#signup">Sign up</a>'  # phones: outside the menu
    return (f'<a class="skip" href="#main">Skip to content</a><header class="site" id="site-header">{LOGO}{cta}'
            f'<button id="menu-btn" type="button" aria-label="Menu" aria-expanded="false" aria-controls="site-nav">☰</button>'
            f'<nav id="site-nav" aria-label="Main">{links}</nav></header>{subnav}'
            f'<script src="/site.js?v={VERSION}" defer></script>{chat}')
