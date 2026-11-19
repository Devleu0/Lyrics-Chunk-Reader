(toast) => {
    const tts = window.speechSynthesis;
    const BCP47 = { en: 'en-US', ja: 'ja-JP', zh: 'zh-CN', ko: 'ko-KR', es: 'es-ES', fr: 'fr-FR', de: 'de-DE',
                    pt: 'pt-BR', it: 'it-IT', ru: 'ru-RU', vi: 'vi-VN', th: 'th-TH', id: 'id-ID' };
    const pickVoice = (lang) => {
        const base = lang.split('-')[0];
        const voices = tts.getVoices().filter(v => v.lang.replace('_', '-').toLowerCase().split('-')[0] === base);
        const score = (v) => (/natural|neural|online|google/i.test(v.name) ? 2 : 0)
                           + (v.lang.replace('_', '-').toLowerCase() === lang.toLowerCase() ? 1 : 0);
        return voices.sort((a, b) => score(b) - score(a))[0] || null;
    };
    tts?.getVoices();  // Chrome은 처음 부를 때 목록을 비동기로 채운다
    let current = null, run = 0;
    const mark = (el, on) => {
        if (!el) return;
        el.classList.toggle('jk-speaking', on);
        if (el.classList.contains('jk-play')) el.closest('.jk-line')?.classList.toggle('jk-reading', on);
    };
    const stop = () => {
        run++;
        tts?.cancel();
        window.jkServerStop?.();
        mark(current, false);
        current = null;
    };
    // 브라우저 음성으로 한 번 읽는다. 끝나면 done(ok) — 음성이 없으면 안내하고 false
    const speak = (el, text, done) => {
        const wrap = el.closest('.jk-wrap');
        const code = wrap?.dataset.lang || '';
        const lang = BCP47[code] || code;
        const none = wrap?.dataset.noVoice || `No voice for ${lang}`;
        if (!tts || typeof SpeechSynthesisUtterance === 'undefined') { toast(none); return done?.(false); }
        const voice = lang && pickVoice(lang);
        // 목록이 채워졌는데 맞는 음성이 없으면 기본 음성(다른 언어)으로 엉뚱하게 읽으므로 안내만 한다
        if (lang && !voice && tts.getVoices().length) { toast(none); return done?.(false); }
        const u = new SpeechSynthesisUtterance(text);
        if (lang) u.lang = lang;
        if (voice) u.voice = voice;
        u.rate = parseFloat(document.documentElement.dataset.rate || '1') || 1;
        const end = () => { mark(el, false); if (current === el) current = null; done?.(true); };
        u.onend = end;
        u.onerror = end;
        mark(el, true);
        current = el;
        tts.speak(u);
    };
    const say = (el, text, line) => {
        const wasSame = current === el;
        stop();
        if (wasSame) return;  // 읽는 중에 다시 누르면 멈춤
        if (window.jkServerSay) { current = el; mark(el, true); return window.jkServerSay(text, line, el); }
        speak(el, text);
    };
    // 서버 음성이 끝났을 때(앱) 표시를 지운다
    const done = (el) => { mark(el, false); if (current === el) current = null; };
    document.addEventListener('click', (e) => {
        const el = e.target.closest('.jk-s[data-tts], .jk-play');
        if (!el || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        say(el, el.dataset.tts, el.classList.contains('jk-play') ? el.dataset.line : '');
    });
    document.addEventListener('keydown', (e) => {
        const el = e.target.closest?.('.jk-play');
        if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); el.click(); }
    });
    // 브라우저 음성으로 줄들을 차례로 읽는다(모바일 HTML의 '전체 듣기'). echo면 그 줄 길이만큼 쉬어 따라 해 볼 수 있게
    const readAll = (plays, echo, onDone) => {
        stop();
        const my = run;
        let i = 0;
        const next = () => {
            if (my !== run) return;
            if (i >= plays.length) return onDone?.();
            const el = plays[i++];
            el.scrollIntoView({ block: 'center', behavior: 'smooth' });
            const t0 = Date.now();
            speak(el, el.dataset.tts, (ok) => {
                if (my !== run) return;
                if (!ok) { stop(); return onDone?.(); }
                setTimeout(next, echo ? Date.now() - t0 + 500 : 450);
            });
        };
        next();
    };
    return { speak, stop, readAll, done };
}
