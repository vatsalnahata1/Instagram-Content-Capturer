const DEFAULTS = { enabled: true, minWatchSeconds: 4, serverUrl: 'http://127.0.0.1:8787', screenshots: 4 };
const $ = id => document.getElementById(id);

function base() { return $('serverUrl').value.replace(/\/$/, ''); }

async function loadSettings() {
  const s = await new Promise(r => chrome.storage.sync.get(DEFAULTS, r));
  $('enabled').checked = !!s.enabled;
  $('minWatchSeconds').value = s.minWatchSeconds;
  $('screenshots').value = s.screenshots;
  $('serverUrl').value = s.serverUrl;
}

function saveSettings() {
  chrome.storage.sync.set({
    enabled: $('enabled').checked,
    minWatchSeconds: Math.max(1, Number($('minWatchSeconds').value) || 4),
    screenshots: Math.max(0, Math.min(8, Number($('screenshots').value) || 0)),
    serverUrl: $('serverUrl').value.trim() || DEFAULTS.serverUrl,
  });
}

async function refresh() {
  const health = $('health');
  try {
    const h = await (await fetch(base() + '/health')).json();
    health.textContent = `server ok · ${h.model}`;
    health.className = 'pill ok';
    const c = h.counts || {};
    $('counts').textContent = `${c.posts_done || 0} posts in bank · ${c.ideas_new || 0} unused ideas` +
      (h.queued ? ` · ${h.queued} queued` : '') + (h.running && h.running.length ? ' · processing' : '');
    const { posts } = await (await fetch(base() + '/posts?limit=8')).json();
    const ul = $('recent');
    ul.innerHTML = '';
    if (!posts.length) ul.innerHTML = '<li class="muted">Nothing captured yet. Watch a reel on instagram.com.</li>';
    for (const p of posts) {
      const li = document.createElement('li');
      const status = p.status === 'done' ? '' : ` [${p.status}${p.error ? ': ' + p.error.slice(0, 80) : ''}]`;
      li.innerHTML = `<b></b><small></small>`;
      li.querySelector('b').textContent = `@${p.creator || '?'} — ${p.topic || ''}${status}`;
      li.querySelector('small').textContent = p.hook ? `hook: ${p.hook}` : (p.media_source ? `via ${p.media_source}` : '');
      ul.appendChild(li);
    }
  } catch (e) {
    health.textContent = 'server offline';
    health.className = 'pill bad';
    $('recent').innerHTML = '<li class="muted">Start it with <code>capturer serve</code> in a terminal.</li>';
    const { activity = [] } = await chrome.storage.local.get({ activity: [] });
    for (const a of activity.slice(0, 5)) {
      const li = document.createElement('li');
      li.textContent = `@${a.creator || a.shortcode}: ${a.status}${a.error ? ' – ' + a.error : ''}`;
      $('recent').appendChild(li);
    }
  }
}

async function ideas() {
  const out = $('ideas');
  out.textContent = 'Thinking… (30-90 seconds)';
  try {
    const res = await fetch(base() + '/ideas', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ count: 5 }) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.status);
    out.textContent = data.ideas.map(i => `#${i.id} ${i.title}\nHook: ${i.hook}\nFormat: ${i.format}\n${i.outline}`).join('\n\n');
  } catch (e) { out.textContent = 'Could not generate ideas: ' + e.message; }
}

for (const id of ['enabled', 'minWatchSeconds', 'screenshots', 'serverUrl']) $(id).addEventListener('change', () => { saveSettings(); refresh(); });
$('ideasBtn').addEventListener('click', ideas);
$('refreshBtn').addEventListener('click', refresh);
loadSettings().then(refresh);
