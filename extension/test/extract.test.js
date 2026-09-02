// Run with: node --test extension/test/extract.test.js
const test = require('node:test');
const assert = require('node:assert');
const X = require('../extract.js');

test('shortcode parsing', () => {
  assert.equal(X.shortcodeFromUrl('https://www.instagram.com/reel/AbC1_-/?igsh=x'), 'AbC1_-');
  assert.equal(X.shortcodeFromUrl('https://www.instagram.com/someone/reels/QQ/'), 'QQ');
  assert.equal(X.shortcodeFromPath('/p/Zz9/'), 'Zz9');
  assert.equal(X.shortcodeFromPath('/explore/'), null);
});

test('extractMedia finds posts in nested API responses and merges duplicates', () => {
  const payload = {
    data: {
      xdt_api__v1__clips__home__connected_v2: {
        edges: [
          { node: { media: {
            code: 'ONE', pk: '1',
            video_versions: [{ width: 480, url: 'https://cdn/one_480.mp4' }, { width: 1080, url: 'https://cdn/one_1080.mp4' }],
            user: { username: 'guru' },
            caption: { text: 'Three SOP mistakes' },
            like_count: 12, comment_count: 3, taken_at: 1700000000, video_duration: 31.2,
          } } },
          { node: { media: { code: 'IMG', image_versions2: {}, user: { username: 'photo' } } } },
          { node: { media: { code: 'ONE', caption: null, user: { username: 'guru' } } } },
        ],
      },
    },
  };
  const items = X.extractMedia(payload);
  assert.equal(items.length, 2);
  const one = items.find(i => i.shortcode === 'ONE');
  assert.equal(one.video_url, 'https://cdn/one_1080.mp4');
  assert.equal(one.creator, 'guru');
  assert.equal(one.caption, 'Three SOP mistakes');
  assert.equal(one.like_count, 12);
  assert.equal(one.duration_sec, 31.2);
  const img = items.find(i => i.shortcode === 'IMG');
  assert.equal(img.video_url, null);
});

test('extractMedia ignores nodes with only a code and handles graphql edge captions', () => {
  assert.deepEqual(X.extractMedia({ items: [{ code: 'X' }] }), []);
  const items = X.extractMedia({ shortcode: 'G', owner: { username: 'o' }, edge_media_to_caption: {},
    caption: { edges: [{ node: { text: 'cap' } }] }, video_url: 'https://cdn/g.mp4' });
  assert.equal(items[0].caption, 'cap');
  assert.equal(items[0].video_url, 'https://cdn/g.mp4');
});

test('extractMedia survives cycles and huge inputs', () => {
  const a = { code: 'C', user: { username: 'u' } };
  a.self = a;
  assert.equal(X.extractMedia(a).length, 1);
  const big = { list: Array.from({ length: 50000 }, (_, i) => ({ i })) };
  assert.deepEqual(X.extractMedia(big), []);
});
