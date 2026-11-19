(doc) => {
    const MIN = %MIN%;
    const els = [...doc.querySelectorAll('.jk-chunks, .jk-wrap .jk-src')];
    els.forEach(el => { el.style.fontSize = ''; el.classList.remove('jk-tight', 'jk-multi'); });
    const over0 = els.filter(el => el.getClientRects().length && el.scrollWidth > el.clientWidth + 1);
    over0.forEach(el => el.classList.add('jk-tight'));
    const multi = (el) => { el.style.fontSize = ''; el.classList.remove('jk-tight'); el.classList.add('jk-multi'); };
    let todo = over0;
    const scale = new Map();
    for (let pass = 0; pass < 4 && todo.length; pass++) {
        const over = todo.map(el => [el, el.clientWidth, el.scrollWidth]).filter(([, c, w]) => w > c + 1);
        todo = [];
        over.forEach(([el, c, w]) => {
            const s = (scale.get(el) || 1) * (c / w) * 0.98;
            if (s < MIN && (pass > 0 || s < MIN * 0.95)) return multi(el);
            scale.set(el, Math.max(MIN, s));
            el.style.fontSize = Math.max(MIN, s) + 'em';
            todo.push(el);
        });
    }
    todo.filter(el => el.scrollWidth > el.clientWidth + 1).forEach(multi);  // 끝까지 넘치면 줄바꿈
}
