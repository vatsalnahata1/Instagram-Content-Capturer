// Pure helpers shared by the page-world interceptor. No DOM, no chrome.* so they can be unit tested.
// Defines window.IGCC_EXTRACT (browser) or module.exports (node tests).
(function (root) {
  'use strict';

  const SHORTCODE_RE = /instagram\.com\/(?:[A-Za-z0-9_.]+\/)?(?:reels?|p|tv)\/([A-Za-z0-9_-]+)/i;

  function shortcodeFromUrl(url) {
    const m = SHORTCODE_RE.exec(url || '');
    return m ? m[1] : null;
  }

  function shortcodeFromPath(pathname) {
    const m = /^\/(?:[A-Za-z0-9_.]+\/)?(?:reels?|p|tv)\/([A-Za-z0-9_-]+)/i.exec(pathname || '');
    return m ? m[1] : null;
  }

  function bestVideoVersion(versions) {
    if (!Array.isArray(versions) || !versions.length) return null;
    // Instagram lists several renditions; prefer the widest one that has a URL.
    const withUrl = versions.filter(v => v && typeof v.url === 'string' && v.url.startsWith('http'));
    if (!withUrl.length) return null;
    withUrl.sort((a, b) => (b.width || 0) - (a.width || 0));
    return withUrl[0].url;
  }

  function captionText(node) {
    const c = node.caption;
    if (!c) return null;
    if (typeof c === 'string') return c;
    if (typeof c.text === 'string') return c.text;
    if (c.edges && c.edges[0] && c.edges[0].node && typeof c.edges[0].node.text === 'string') return c.edges[0].node.text;
    return null;
  }

  function mediaFromNode(node) {
    if (!node || typeof node !== 'object') return null;
    const code = typeof node.code === 'string' ? node.code : (typeof node.shortcode === 'string' ? node.shortcode : null);
    if (!code) return null;
    const videoUrl = bestVideoVersion(node.video_versions) || (typeof node.video_url === 'string' ? node.video_url : null);
    const user = node.user || node.owner || {};
    const item = {
      shortcode: code,
      video_url: videoUrl,
      creator: typeof user.username === 'string' ? user.username : null,
      caption: captionText(node),
      like_count: typeof node.like_count === 'number' ? node.like_count : null,
      comment_count: typeof node.comment_count === 'number' ? node.comment_count : null,
      taken_at: typeof node.taken_at === 'number' ? node.taken_at : null,
      duration_sec: typeof node.video_duration === 'number' ? node.video_duration : null,
    };
    // Only useful if we learned something beyond the code.
    if (!item.video_url && !item.creator && !item.caption) return null;
    return item;
  }

  // Walk an API response and collect every post-like object. Depth and node caps keep it cheap.
  function extractMedia(data, opts) {
    const maxNodes = (opts && opts.maxNodes) || 20000;
    const maxDepth = (opts && opts.maxDepth) || 25;
    const found = new Map();
    let visited = 0;
    const stack = [[data, 0]];
    while (stack.length) {
      const [node, depth] = stack.pop();
      if (!node || typeof node !== 'object' || depth > maxDepth) continue;
      if (++visited > maxNodes) break;
      if (Array.isArray(node)) {
        for (const child of node) stack.push([child, depth + 1]);
        continue;
      }
      const item = mediaFromNode(node);
      if (item) {
        const prev = found.get(item.shortcode);
        // Merge: keep the first non-null value for each field.
        if (prev) {
          for (const k of Object.keys(item)) if (prev[k] == null && item[k] != null) prev[k] = item[k];
        } else {
          found.set(item.shortcode, item);
        }
      }
      for (const key of Object.keys(node)) {
        const v = node[key];
        if (v && typeof v === 'object') stack.push([v, depth + 1]);
      }
    }
    return Array.from(found.values());
  }

  const api = { shortcodeFromUrl, shortcodeFromPath, extractMedia, mediaFromNode, bestVideoVersion };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.IGCC_EXTRACT = api;
})(typeof window !== 'undefined' ? window : globalThis);
