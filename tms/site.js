// The shared header (tms/site.py): the phone menu, the dashboard's pop-up second bar, the signed-in
// name and Log out. Pages that need the account fetch /api/me themselves.
(() => {
  const $ = id => document.getElementById(id), header = $('site-header'), sub = $('subnav'), dd = header.querySelector('.dd-btn')
  const setMenu = open => { header.classList.toggle('open', open); $('menu-btn').setAttribute('aria-expanded', String(open)) }
  $('menu-btn').onclick = () => setMenu(!header.classList.contains('open'))
  // Off the dashboard, the ▾ next to Dashboard (or hovering it) pops the second bar up under the header.
  const setSub = open => { if (!sub || sub.classList.contains('pinned')) return
    document.documentElement.style.setProperty('--hh', header.offsetHeight + 'px')
    sub.classList.toggle('on', open); dd?.setAttribute('aria-expanded', String(open)) }
  if (dd) {  // a click pins it open (or closes what a click opened); hovering opens it until the pointer leaves
    let t, clicked = false; const wrap = dd.parentNode
    dd.onclick = () => { clicked = !(clicked && sub.classList.contains('on')); setSub(clicked) }
    for (const el of [wrap, sub]) {
      el.addEventListener('mouseenter', () => { clearTimeout(t); if (matchMedia('(hover: hover)').matches) setSub(true) })
      el.addEventListener('mouseleave', () => { t = setTimeout(() => { if (!clicked) setSub(false) }, 250) })
    }
  }
  document.addEventListener('click', e => { if (!header.contains(e.target) && !sub?.contains(e.target)) { setMenu(false); setSub(false) } })
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { setMenu(false); setSub(false) } })
  $('logout')?.addEventListener('click', async () => { await fetch('/logout', {method: 'POST'}); location.href = '/' })
  if ($('who-name')) fetch('/api/me').then(r => r.ok ? r.json() : null).then(me => {
    if (!me) return
    $('who-name').textContent = me.profile?.name || me.email || me.npub.slice(0, 12) + '…'
    // Npubs is for collection owners and site admins (the dashboard asks its API for admins).
    if (me.collections?.some(c => c.role === 'owner'))
      document.querySelectorAll('[data-tab="npubs"]').forEach(a => { a.hidden = false })
  }).catch(() => {})
  // The dashboard's sections are hash links: mark the current one.
  const mark = () => document.querySelectorAll('a[data-tab]').forEach(a =>
    location.pathname === '/dashboard' && (location.hash.slice(1) || 'collections') === a.dataset.tab
      ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current'))
  mark(); addEventListener('hashchange', mark)
})()
