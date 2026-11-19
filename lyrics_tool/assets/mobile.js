(() => {
  const root = document.documentElement;
  const KEY = 'lyrics-jikdok-mobile';
  let prefs = {};
  try { prefs = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch {}
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch {} };
  const fs0 = parseInt(root.dataset.fs, 10) || 15;
  let apply = () => {
    root.dataset.mode = prefs.mode || root.dataset.mode;
    root.classList.toggle('m-hide', !!prefs.hide);
    root.style.setProperty('--m-fs', (prefs.fs || fs0) + 'px');
    document.querySelectorAll('[data-set-mode]').forEach(b =>
      b.setAttribute('aria-pressed', String(b.dataset.setMode === root.dataset.mode)));
    document.querySelector('[data-act="hide"]')?.setAttribute('aria-pressed', String(!!prefs.hide));
  };
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-set-mode], [data-act]');
    if (b) {
      if (b.dataset.setMode) prefs.mode = b.dataset.setMode;
      const act = b.dataset.act;
      if (act === 'hide') { prefs.hide = !prefs.hide; document.querySelectorAll('.m-shown').forEach(x => x.classList.remove('m-shown')); }
      if (act === 'bigger') prefs.fs = Math.min(32, (prefs.fs || fs0) + 1);
      if (act === 'smaller') prefs.fs = Math.max(12, (prefs.fs || fs0) - 1);
      save(); apply(); return;
    }
    const gloss = root.classList.contains('m-hide') && e.target.closest('.jk-t, .jk-tr');
    if (gloss) gloss.classList.toggle('m-shown');  // 가린 뜻은 눌러서 하나씩 확인
  });
  const fit = %FIT%;
  let queued = false;
  const refit = () => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; fit(document); }); };
  const apply0 = apply;
  apply = () => { apply0(); refit(); };
  addEventListener('resize', refit);
  document.fonts?.ready.then(refit);
  apply();
  const toast = (msg) => {
    document.querySelector('#m-toast')?.remove();
    const d = Object.assign(document.createElement('div'), { id: 'm-toast', textContent: msg });
    d.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:99;'
      + 'max-width:90vw;padding:10px 16px;border-radius:8px;background:rgba(30,30,30,.92);color:#fff;font-size:14px';
    document.body.appendChild(d);
    setTimeout(() => d.remove(), 3500);
  };
  const tts = (%TTS%)(toast);
  // 전체 듣기: 화면에 보이는 곡부터 그 곡의 줄을 차례로 읽는다. 다시 누르면 멈춤. '따라 말하기'면 줄마다 그 길이만큼 쉰다
  const readBtn = document.querySelector('[data-act="readall"]');
  const echoBtn = document.querySelector('[data-act="echo"]');
  let reading = false;
  const setReading = (on) => { reading = on; readBtn?.setAttribute('aria-pressed', String(on)); };
  echoBtn?.setAttribute('aria-pressed', String(!!prefs.echo));
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-act="readall"], [data-act="echo"]');
    if (!b) return;
    e.stopImmediatePropagation();
    if (b.dataset.act === 'echo') {
      prefs.echo = !prefs.echo; save(); b.setAttribute('aria-pressed', String(prefs.echo)); return;
    }
    if (reading) { tts.stop(); return setReading(false); }
    const song = document.querySelector('.m-song.m-cur') || document.querySelector('.m-song');
    const plays = [...song.querySelectorAll(`.m-mode[data-mode="${root.dataset.mode}"] .jk-play`)];
    setReading(true);
    tts.readAll(plays, !!prefs.echo, () => setReading(false));
  }, true);
  // 여러 곡: 한 번에 한 곡만 보이고, ⋮ 서랍의 목록이나 곡 끝의 이전·다음으로 바꾼다. 마지막에 본 곡을 기억한다
  const songs = [...document.querySelectorAll('.m-song')];
  const drawer = document.getElementById('m-drawer');
  if (songs.length < 2 || !drawer) return;
  const links = [...drawer.querySelectorAll('.m-toc a')];
  const bookEl = document.querySelector('.m-book');
  const book = document.title;
  const openDrawer = (on) => {
    drawer.classList.toggle('m-open', on);
    document.body.classList.toggle('m-lock', on);
    drawer.setAttribute('aria-hidden', String(!on));
    if (on) links.find(a => a.getAttribute('aria-current') === 'true')?.scrollIntoView({ block: 'center' });
  };
  const show = (i, top = true) => {
    i = Math.max(0, Math.min(songs.length - 1, i | 0));
    if (reading) { tts.stop(); setReading(false); }
    songs.forEach((s, k) => s.classList.toggle('m-cur', k === i));
    links.forEach((a, k) => a.setAttribute('aria-current', String(k === i)));
    const h2 = songs[i].querySelector('h2');
    bookEl.textContent = h2.textContent;
    bookEl.lang = h2.lang;
    prefs.last = Object.assign(prefs.last || {}, { [book]: i }); save();
    // 처음 열 때 주소에 #을 붙이면 브라우저가 그 곡으로 내려가 제목이 막대 밑에 가려진다. 고를 때만 붙인다
    if (top) { history.replaceState(null, '', '#' + songs[i].id); scrollTo(0, 0); }
    refit();
  };
  const fromHash = () => songs.findIndex(s => '#' + s.id === location.hash);
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-act="menu"]')) return openDrawer(true);
    if (e.target.closest('[data-act="close"], .m-shade')) return openDrawer(false);
    const a = e.target.closest('.m-toc a, .m-nav a');
    if (!a) return;
    e.preventDefault();
    show(songs.findIndex(s => '#' + s.id === a.getAttribute('href')));
    openDrawer(false);
  });
  addEventListener('keydown', (e) => { if (e.key === 'Escape') openDrawer(false); });
  addEventListener('hashchange', () => { const i = fromHash(); if (i >= 0) show(i); });
  const h = fromHash();
  show(h >= 0 ? h : (prefs.last || {})[book] || 0, false);
  if (h >= 0) addEventListener('load', () => setTimeout(() => scrollTo(0, 0), 50));  // #song-N으로 열어도 곡 맨 위에서
})();
