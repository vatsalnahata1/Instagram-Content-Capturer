// Isolated-world content script: watches which reel is playing, decides when you have really
// watched it, gathers metadata, and asks the background worker to file it.
(function () {
  'use strict';

  const SHORTCODE_PATH_RE = /^\/(?:[A-Za-z0-9_.]+\/)?(?:reels?|p|tv)\/([A-Za-z0-9_-]+)/i;
  const NOT_USERNAMES = new Set(['explore', 'reels', 'reel', 'p', 'tv', 'stories', 'direct', 'accounts', 'about', 'legal']);

  const media = new Map();            // shortcode -> data learned from API responses
  const watch = new Map();            // shortcode -> { ms, sent }
  let settings = { enabled: true, minWatchSeconds: 4, screenshots: 4 };
  let lastTick = performance.now();
  let current = null;                 // shortcode currently in view

  chrome.storage.sync.get(settings, s => { settings = Object.assign(settings, s); });
  chrome.storage.onChanged.addListener(changes => {
    for (const k of Object.keys(changes)) if (k in settings) settings[k] = changes[k].newValue;
  });

  window.addEventListener('message', ev => {
    if (ev.source !== window || !ev.data || ev.data.type !== 'igcc-media') return;
    for (const item of ev.data.items || []) {
      const prev = media.get(item.shortcode) || {};
      for (const k of Object.keys(item)) if (prev[k] == null && item[k] != null) prev[k] = item[k];
      media.set(item.shortcode, prev);
    }
  });
  // Ask the page-world interceptor for anything it saw before we started.
  window.postMessage({ type: 'igcc-hello' }, location.origin);

  function shortcodeFor(video) {
    const fromPath = SHORTCODE_PATH_RE.exec(location.pathname);
    // On /reels/<code>/ the URL tracks the reel in view. Elsewhere (home feed, profile grid
    // modal) look for a permalink near the player.
    let container = video.closest('article') || video.closest('[role="dialog"]') || video.parentElement;
    for (let i = 0; i < 6 && container && container !== document.body; i++) {
      const link = container.querySelector('a[href*="/reel/"], a[href*="/reels/"], a[href*="/p/"]');
      if (link) {
        const m = SHORTCODE_PATH_RE.exec(new URL(link.href, location.origin).pathname);
        if (m) return m[1];
      }
      container = container.parentElement;
    }
    return fromPath ? fromPath[1] : null;
  }

  function creatorFor(video) {
    let container = video.closest('article') || video.closest('[role="dialog"]') || video.parentElement;
    for (let i = 0; i < 8 && container && container !== document.body; i++) {
      for (const a of container.querySelectorAll('a[href]')) {
        const m = /^\/([A-Za-z0-9_.]{2,30})\/?$/.exec(new URL(a.href, location.origin).pathname);
        if (m && !NOT_USERNAMES.has(m[1].toLowerCase())) return m[1];
      }
      container = container.parentElement;
    }
    return null;
  }

  function captionFor(video) {
    const container = video.closest('article') || video.closest('[role="dialog"]') || video.parentElement;
    if (!container) return null;
    let best = '';
    for (const el of container.querySelectorAll('h1, span[dir="auto"], div[dir="auto"]')) {
      const t = (el.innerText || '').trim();
      if (t.length > best.length && t.length < 5000) best = t;
    }
    return best || null;
  }

  function visibleArea(el) {
    const r = el.getBoundingClientRect();
    const w = Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0));
    const h = Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
    return w * h;
  }

  function activeVideo() {
    let best = null, bestArea = 0;
    for (const v of document.querySelectorAll('video')) {
      if (v.paused || v.ended) continue;
      const area = visibleArea(v);
      if (area > bestArea) { best = v; bestArea = area; }
    }
    return bestArea > 40000 ? best : null;   // ignore tiny thumbnails
  }

  function toast(text) {
    let el = document.getElementById('igcc-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'igcc-toast';
      el.style.cssText = 'position:fixed;bottom:18px;right:18px;z-index:2147483647;background:#111;color:#fff;' +
        'padding:10px 14px;border-radius:8px;font:13px -apple-system,system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.3);' +
        'opacity:0;transition:opacity .2s;max-width:320px;pointer-events:none';
      document.body.appendChild(el);
    }
    el.textContent = text;
    el.style.opacity = '1';
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.style.opacity = '0'; }, 3500);
  }

  // Draw the playing video onto a canvas. Reels play from same-origin blob: URLs, so this works
  // without any extra permission; a cross-origin CDN src taints the canvas and we return null
  // (the server downloads that link instead).
  function grabFrame(video) {
    try {
      const w = video.videoWidth || 720, h = video.videoHeight || 1280;
      const scale = Math.min(1, 720 / w);
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(w * scale);
      canvas.height = Math.round(h * scale);
      canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL('image/jpeg', 0.8).split(',')[1];
    } catch (_) {
      return null;
    }
  }

  // Grab up to settings.screenshots frames ~1.5s apart while this reel stays on screen.
  function collectFrames(video, code, done) {
    const want = Math.max(0, Math.min(8, Number(settings.screenshots) || 0));
    const frames = [];
    const step = () => {
      if (current === code && !document.hidden && frames.length < want) {
        const f = grabFrame(video);
        if (f) frames.push(f);
        if (f && frames.length < want) { setTimeout(step, 1500); return; }
      }
      done(frames);
    };
    step();
  }

  function send(video, code, frames) {
    const known = media.get(code) || {};
    const src = (video.currentSrc || video.src || '');
    const payload = {
      shortcode: code,
      url: `https://www.instagram.com/reel/${code}/`,
      creator: known.creator || creatorFor(video),
      caption: known.caption || captionFor(video),
      video_url: known.video_url || (src.startsWith('http') ? src : null),
      like_count: known.like_count, comment_count: known.comment_count,
      taken_at: known.taken_at,
      duration_sec: known.duration_sec || (isFinite(video.duration) ? video.duration : null),
      screenshots: frames || [],
      page_url: location.href,
    };
    chrome.runtime.sendMessage({ type: 'capture', payload }, resp => {
      if (chrome.runtime.lastError) { toast('Capturer: extension error, reload the page'); return; }
      if (!resp) return;
      if (resp.ok) toast(`Capturer: ${resp.status === 'skipped' ? 'already in bank' : 'sent'} @${payload.creator || code}`);
      else toast(`Capturer: ${resp.error || 'failed'}`);
    });
  }

  function tick() {
    const now = performance.now();
    const dt = Math.min(now - lastTick, 2000);
    lastTick = now;
    if (!settings.enabled || document.hidden) { current = null; return; }
    const video = activeVideo();
    if (!video) { current = null; return; }
    const code = shortcodeFor(video);
    if (!code) { current = null; return; }
    current = code;
    const w = watch.get(code) || { ms: 0, sent: false };
    w.ms += dt;
    watch.set(code, w);
    const threshold = (settings.minWatchSeconds || 4) * 1000;
    if (!w.sent && w.ms >= threshold) {
      // Instagram's API data (creator, caption, CDN link) normally lands before the video plays.
      // If it has not, wait a moment once rather than falling back to DOM guesses straight away.
      if (!media.has(code) && !w.waited) { w.waited = true; w.ms = threshold - 1500; return; }
      w.sent = true;
      collectFrames(video, code, frames => send(video, code, frames));
    }
  }

  setInterval(tick, 500);
})();
