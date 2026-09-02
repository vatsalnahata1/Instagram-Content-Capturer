// Service worker: forwards captures from the content script to the local capturer server and
// keeps a small activity log for the popup.

const DEFAULTS = { enabled: true, minWatchSeconds: 4, serverUrl: 'http://127.0.0.1:8787', screenshots: 4 };

async function getSettings() {
  return new Promise(resolve => chrome.storage.sync.get(DEFAULTS, s => resolve(Object.assign({}, DEFAULTS, s))));
}

function setBadge(text, color) {
  chrome.action.setBadgeText({ text });
  if (color) chrome.action.setBadgeBackgroundColor({ color });
}

async function log(entry) {
  const { activity = [] } = await chrome.storage.local.get({ activity: [] });
  activity.unshift(Object.assign({ at: Date.now() }, entry));
  await chrome.storage.local.set({ activity: activity.slice(0, 30) });
}

async function postCapture(serverUrl, payload) {
  const res = await fetch(serverUrl.replace(/\/$/, '') + '/capture', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `server responded ${res.status}`);
  return body;
}

async function handleCapture(payload) {
  const settings = await getSettings();
  if (!settings.enabled) return { ok: false, error: 'capture is paused' };
  setBadge('…', '#555');
  try {
    const result = await postCapture(settings.serverUrl, Object.assign({}, payload, { source: 'extension' }));
    await log({ shortcode: payload.shortcode, creator: payload.creator, status: result.status });
    setBadge(result.status === 'skipped' ? '=' : '✓', '#2e7d32');
    setTimeout(() => setBadge('', null), 2500);
    return { ok: true, status: result.status };
  } catch (e) {
    const offline = /Failed to fetch|NetworkError/.test(String(e));
    const error = offline ? 'server not running (capturer serve)' : String(e.message || e);
    await log({ shortcode: payload.shortcode, creator: payload.creator, status: 'failed', error });
    setBadge('!', '#c62828');
    return { ok: false, error };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === 'capture') {
    handleCapture(msg.payload).then(reply);
    return true; // async reply
  }
  return false;
});

chrome.runtime.onInstalled.addListener(() => setBadge('', null));
