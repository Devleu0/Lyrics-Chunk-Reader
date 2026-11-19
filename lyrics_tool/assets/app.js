() => {
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            const b = document.querySelector('#jk-translate');
            if (b) { e.preventDefault(); b.click(); }
        }
    });
    document.addEventListener('click', (e) => {
        const no = e.target.closest('.jk-no');
        const input = document.querySelector('#jk-line-no input');
        if (!no || !input) return;
        input.value = no.textContent.trim();
        input.dispatchEvent(new Event('input', { bubbles: true }));
        setTimeout(() => document.querySelector('#jk-load-line')?.click(), 80);
    });
    const toast = (msg) => {
        document.querySelector('#jk-toast')?.remove();
        const d = Object.assign(document.createElement('div'), { id: 'jk-toast', textContent: msg });
        d.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:9999;'
            + 'max-width:min(90vw,480px);padding:10px 16px;border-radius:8px;background:rgba(30,30,30,.92);'
            + 'color:#fff;font-size:14px;box-shadow:0 4px 16px rgba(0,0,0,.3)';
        document.body.appendChild(d);
        setTimeout(() => d.remove(), 3500);
    };
    // 오프라인 사본: 서버가 미리 보내 둔 곡별 HTML(offline_pack_file). 히스토리 줄을 눌렀는데 서버가 꺼져 있으면
    // 이 사본을 뷰어에 그린다. 서버가 살아 있으면 평소처럼 서버가 연다.
    // 예전 버전은 곡 HTML을 이벤트 값으로 보내 Gradio run history(localStorage)를 수 MB씩 채웠다. 그 기록을 지운다.
    try {
        for (const k of Object.keys(localStorage)) {
            if (k.startsWith('gradio:run-history') && localStorage.getItem(k).includes('"/offline_pack"')) {
                localStorage.removeItem(k);
            }
        }
    } catch {}
    const offline = { songs: {}, msg: '' };
    window.jkOffline = (p) => {
        if (!p) return;
        if (p.reset) offline.songs = {};
        Object.assign(offline.songs, p.add || {});
        const keep = new Set(p.ids || []);
        for (const id of Object.keys(offline.songs)) if (!keep.has(id)) delete offline.songs[id];
        offline.msg = p.msg || offline.msg;
    };
    const serverUp = async () => {
        const ctl = new AbortController();
        const timer = setTimeout(() => ctl.abort(), 1500);
        try { return (await fetch('config', { cache: 'no-store', signal: ctl.signal })).ok; }
        catch { return false; }
        finally { clearTimeout(timer); }
    };
    document.addEventListener('click', (e) => {
        const row = e.target.closest('#jk-history-table [role=row], #jk-history-table tbody tr');
        if (!row) return;
        const cells = [...row.querySelectorAll('[role=gridcell], td')].map(td => td.textContent.trim());
        const song = Object.values(offline.songs).find(s => cells.includes(s.title) && cells.includes(s.when));
        const wrap = document.querySelector('#jk-viewer .jk-wrap');
        if (!song || !wrap) return;
        // 서버가 살아 있으면 Gradio가 그리게 둔다. 꺼졌을 때만 Gradio가 관리하는 뷰어 DOM을 직접 바꾼다.
        serverUp().then(up => {
            if (up) return;
            wrap.parentElement.innerHTML = song.html;
            if (offline.msg) toast(offline.msg);
        });
    }, true);
    // 듣기 (render.TTS_JS): 어구·줄은 숨은 칸(#jk-say)에 요청을 적고 버튼을 눌러 서버 음성(edge-tts)을 받는다.
    // 곡 전체는 아래쪽 재생 막대로 틀고, 재생 위치에 맞춰 지금 읽는 줄을 강조한다.
    const tts = (%TTS%)(toast);
    window.jkTts = tts;
    window.jkToast = toast;
    const bar = Object.assign(document.createElement('div'), { id: 'jk-audio' });
    bar.innerHTML = '<span class="jk-audio-title"></span><audio controls preload="auto"></audio>'
                  + '<button type="button" aria-label="close">✕</button>';
    document.body.appendChild(bar);
    const audio = bar.querySelector('audio');
    let sayId = 0, sayEl = null, timings = [], lastLine = 0;
    const clearReading = () => document.querySelectorAll('#jk-viewer .jk-reading')
        .forEach(x => x.classList.remove('jk-reading'));
    window.jkServerSay = (text, line, el) => {
        const box = document.querySelector('#jk-say textarea, #jk-say input');
        if (!box) return;
        sayEl = el;
        box.value = JSON.stringify({ id: ++sayId, text, line: line ? Number(line) : 0 });
        box.dispatchEvent(new Event('input', { bubbles: true }));
        setTimeout(() => document.querySelector('#jk-say-btn')?.click(), 60);
    };
    window.jkServerStop = () => {
        sayId++;
        audio.pause();
        timings = [];
        clearReading();
        bar.classList.remove('jk-on');
    };
    const showLine = (n) => {
        if (n === lastLine) return;
        lastLine = n;
        clearReading();
        const play = document.querySelector(`#jk-viewer .jk-play[data-line="${n}"]`);
        const line = play?.closest('.jk-line');
        if (!line) return;
        line.classList.add('jk-reading');
        const r = line.getBoundingClientRect();
        if (r.top < 80 || r.bottom > innerHeight - 90) line.scrollIntoView({ block: 'center', behavior: 'smooth' });
    };
    audio.addEventListener('timeupdate', () => {
        if (!timings.length) return;
        const t = audio.currentTime;
        const cur = timings.find(x => t >= x.start && t < x.end + 0.15);
        if (cur) showLine(cur.line);
        else if (lastLine) { lastLine = 0; clearReading(); }
    });
    audio.addEventListener('ended', () => {
        if (sayEl) tts.done(sayEl);
        sayEl = null;
        if (timings.length) { lastLine = 0; clearReading(); }
    });
    bar.querySelector('button').addEventListener('click', () => tts.stop());
    // 요청한 뒤 한참 지나도 재생되지 않으면(서버 오류 등) '읽는 중' 표시를 지운다
    window.jkSayCheck = () => { if (sayEl && audio.paused) { tts.done(sayEl); sayEl = null; } };
    // 서버가 돌려준 음성 재생. p: {id, kind: 'say' | 'song', title, lines: [{line, start, end}]}
    window.jkPlay = (f, p) => {
        if (!f?.url || !p) return;
        if (p.kind === 'say' && p.id !== sayId) return;  // 그 사이 다른 곳을 눌렀다
        if (p.kind === 'song') { tts.stop(); sayEl = null; }
        timings = p.lines || [];
        lastLine = 0;
        bar.querySelector('.jk-audio-title').textContent = p.title || '';
        bar.classList.toggle('jk-on', p.kind === 'song');
        audio.src = f.url;
        audio.play().catch(() => {});
    };
}
