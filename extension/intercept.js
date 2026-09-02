// Runs in the page's own JavaScript world (see manifest "world": "MAIN").
// Instagram loads reel data through fetch/XHR; we read those responses as they arrive and hand
// the useful bits (shortcode -> CDN video link, caption, creator) to the content script.
(function () {
  'use strict';
  if (window.__igccIntercept) return;
  window.__igccIntercept = true;
  const X = window.IGCC_EXTRACT;
  if (!X) return;

  // Everything learned so far, so a content script that starts later can catch up.
  const known = new Map();

  function remember(items) {
    for (const item of items) {
      const prev = known.get(item.shortcode);
      if (prev) {
        for (const k of Object.keys(item)) if (prev[k] == null && item[k] != null) prev[k] = item[k];
      } else {
        known.set(item.shortcode, item);
      }
    }
    if (known.size > 2000) known.delete(known.keys().next().value);
  }

  function publish(text) {
    if (!text || text.length > 15 * 1024 * 1024) return;
    let data;
    try { data = JSON.parse(text.replace(/^for \(;;\);/, '')); } catch (_) { return; }
    let items;
    try { items = X.extractMedia(data); } catch (_) { return; }
    if (!items.length) return;
    remember(items);
    window.postMessage({ type: 'igcc-media', items }, window.location.origin);
  }

  window.addEventListener('message', ev => {
    if (ev.source !== window || !ev.data || ev.data.type !== 'igcc-hello') return;
    if (known.size) window.postMessage({ type: 'igcc-media', items: Array.from(known.values()) }, window.location.origin);
  });

  function interesting(url) {
    return typeof url === 'string' && /instagram\.com\/(graphql|api\/v1)/.test(url);
  }

  const origFetch = window.fetch;
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url);
    const p = origFetch.apply(this, arguments);
    if (interesting(url)) {
      p.then(res => {
        try {
          const ct = res.headers.get('content-type') || '';
          if (/json|javascript|text/.test(ct)) res.clone().text().then(publish).catch(() => {});
        } catch (_) {}
      }).catch(() => {});
    }
    return p;
  };

  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__igccUrl = url;
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    if (interesting(this.__igccUrl)) {
      this.addEventListener('load', function () {
        try { if (this.responseType === '' || this.responseType === 'text') publish(this.responseText); } catch (_) {}
      });
    }
    return origSend.apply(this, arguments);
  };

  // Data embedded in the initial HTML (Instagram inlines the first few posts as JSON).
  function scanInlineScripts() {
    try {
      const scripts = document.querySelectorAll('script[type="application/json"]');
      for (const s of scripts) {
        if (s.textContent && /video_versions|"code"/.test(s.textContent)) publish(s.textContent);
      }
    } catch (_) {}
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scanInlineScripts);
  else scanInlineScripts();
})();
