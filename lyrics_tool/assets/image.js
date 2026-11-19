async (f) => {
    if (!f?.url) return;
    const p = await (await fetch(f.url)).json();
    const frame = document.createElement('iframe');
    frame.style.cssText = `position:fixed;left:-20000px;top:0;width:${p.width}px;height:100px;border:0;`;
    document.body.appendChild(frame);
    try {
        const d = frame.contentDocument;
        d.open();
        d.write('<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0">' + p.html
                + '</body></html>');
        d.close();
        await d.fonts?.ready;
        (%FIT%)(d);  // 한 줄이 폭을 넘으면 그 줄만 줄인다 (render.FIT_CSS)
        const node = d.body.firstElementChild;
        const w = p.width, h = Math.ceil(node.getBoundingClientRect().height);
        const xhtml = new XMLSerializer().serializeToString(node);
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}">`
                  + `<foreignObject x="0" y="0" width="${w}" height="${h}">${xhtml}</foreignObject></svg>`;
        const img = new Image();
        await new Promise((ok, bad) => {
            img.onload = ok; img.onerror = bad;
            img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
        });
        const scale = Math.max(0.5, Math.min(2, Math.sqrt(16e6 / (w * h)), 32000 / h));
        const c = document.createElement('canvas');
        c.width = Math.round(w * scale);
        c.height = Math.round(h * scale);
        const ctx = c.getContext('2d');
        ctx.scale(scale, scale);
        ctx.drawImage(img, 0, 0, w, h);
        const blob = await new Promise(r => c.toBlob(r, 'image/png'));
        if (!blob) throw new Error('empty canvas');
        const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: p.name });
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    } catch (e) {
        console.error(e);
        alert(p.fail);
    } finally {
        frame.remove();
    }
}
