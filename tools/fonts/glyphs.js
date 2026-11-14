/* glyphs.js: the browser half of the font pipeline, shared by raster.html and the themes' sizing pages.

   - raster(spec): glyph coverage of a face at one size, exactly as raster/<id>.json stores it
     (one glyph at a time on a transparent canvas, 4-bit alpha, ink box relative to the pen on
     the baseline). Deterministic for a given browser: raster.html and a sizing page give the
     same file.
   - makeFont(raster, chars, bpp) / font.render(...): a port of tools/patch/pfont.py (PFont and
     render), so a page can show text exactly as uk_text draws it, and count its bytes.

   Kinds of font: disp (Big Shoulders Display 800), num (Barlow Condensed 600), mono (IBM Plex
   Mono 500), icons (drawn glyphs: the mock's speaker S, muted speaker M, headphones H). */
(function (root) {
'use strict';
const ASCII = Array.from({length: 95}, (_, i) => String.fromCharCode(32 + i)).join('');
const FAMILIES = 'Barlow+Condensed:wght@500;600&family=Big+Shoulders+Display:wght@700;800&family=IBM+Plex+Mono:wght@400;500';
const KINDS = {
  disp: {font: px => `800 ${px}px "Big Shoulders Display"`, chars: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-'},
  num: {font: px => `600 ${px}px "Barlow Condensed"`, chars: '0123456789.-−∞ '},
  mono: {font: px => `500 ${px}px "IBM Plex Mono"`, chars: 'ascii·−∞'},
  icons: {draw: 'icons', chars: 'SMH'},
};
function spec(kind, px){
  const k = KINDS[kind];
  return k.draw ? {id: kind + px, draw: k.draw, size: px, chars: k.chars}
                : {id: kind + px, font: k.font(px), chars: k.chars};
}
function fontCss(){ return 'https://fonts.googleapis.com/css2?family=' + FAMILIES + '&display=block'; }
async function loadFonts(){
  if (!document.querySelector('link[data-glyphs]')){
    const link = document.createElement('link');
    link.rel = 'stylesheet'; link.href = fontCss(); link.dataset.glyphs = '1';
    document.head.appendChild(link);
    await new Promise((ok, bad) => { link.onload = ok; link.onerror = () => bad(new Error('the Google Fonts stylesheet did not load')); });
  }
  for (const k of Object.values(KINDS)) if (k.font){
    const faces = await document.fonts.load(k.font(20), 'AZaz09');
    if (!faces.length) throw new Error('font not loaded: ' + k.font(20));
  }
}

/* drawn glyphs: (g, ch, x, y, s) draws character ch in an s-px box with its top-left at x, y; returns the advance */
const DRAW = {
  icons(g, ch, x, y, s){
    g.fillStyle = '#fff'; g.strokeStyle = '#fff'; g.lineWidth = 2;
    if (ch === 'H'){
      g.beginPath(); g.arc(x + s * .5, y + s * .55, s * .42, Math.PI, 0); g.stroke();
      g.fillRect(x + s * .06, y + s * .55, s * .24, s * .42); g.fillRect(x + s * .7, y + s * .55, s * .24, s * .42);
      return s;
    }
    g.beginPath(); g.moveTo(x, y + s * .35); g.lineTo(x + s * .3, y + s * .35); g.lineTo(x + s * .62, y);
    g.lineTo(x + s * .62, y + s); g.lineTo(x + s * .3, y + s * .65); g.lineTo(x, y + s * .65); g.closePath(); g.fill();
    g.beginPath();
    if (ch === 'M'){ g.moveTo(x + s * .8, y + s * .3); g.lineTo(x + s * 1.15, y + s * .7); g.moveTo(x + s * 1.15, y + s * .3); g.lineTo(x + s * .8, y + s * .7); }
    else { g.arc(x + s * .62, y + s / 2, s * .3, -0.9, 0.9); g.moveTo(x + s * .62 + s * .55 * Math.cos(-0.9), y + s / 2 + s * .55 * Math.sin(-0.9)); g.arc(x + s * .62, y + s / 2, s * .55, -0.9, 0.9); }
    g.stroke();
    return s * 1.25;
  },
};

/* one glyph at a time on a transparent canvas, white ink: alpha = coverage (grey-scale, no subpixel AA) */
// The browser that rendered a raster, as "Chrome 152 (macOS)". Rasters can differ by a pixel
// between engines, so each file records it; the full user-agent string is not kept.
function engineName() {
  const ua = navigator.userAgent;
  const m = /(Firefox|Edg|Chrome)\/(\d+)/.exec(ua) || /(Version)\/(\d+)/.exec(ua);
  const os = /Mac OS X/.test(ua) ? 'macOS' : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : 'other';
  return m ? `${m[1] === 'Version' ? 'Safari' : m[1]} ${m[2]} (${os})` : 'unknown';
}

function raster(sp){
  const chars = [...new Set([...sp.chars.replace('ascii', ASCII)])];
  const px = sp.draw ? sp.size : parseFloat(sp.font.match(/(\d+(?:\.\d+)?)px/)[1]);
  const W = Math.ceil(px * 4), H = Math.ceil(px * 3), ox = Math.ceil(px), base = Math.ceil(px * 2);
  const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
  const g = cv.getContext('2d', {willReadFrequently: true});
  const glyphs = {};
  for (const ch of chars){
    g.clearRect(0, 0, W, H);
    g.font = sp.font || '10px sans-serif'; g.textBaseline = 'alphabetic'; g.textAlign = 'left'; g.fillStyle = '#fff';
    if ('letterSpacing' in g) g.letterSpacing = '0px';
    let adv;
    if (sp.draw){ adv = DRAW[sp.draw](g, ch, ox, base - px, px); }
    else { g.fillText(ch, ox, base); adv = g.measureText(ch).width; }
    const d = g.getImageData(0, 0, W, H).data;
    let x0 = W, x1 = -1, y0 = H, y1 = -1;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (d[(y * W + x) * 4 + 3]){
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
    const rows = [];
    for (let y = y0; y <= y1; y++){
      let s = '';
      for (let x = x0; x <= x1; x++) s += Math.round(d[(y * W + x) * 4 + 3] * 15 / 255).toString(16);
      rows.push(s);
    }
    glyphs[ch] = x1 < 0 ? {adv, x: 0, y: 0, rows: []} : {adv, x: x0 - ox, y: y0 - base, rows};
  }
  g.font = sp.font || '10px sans-serif';
  const m = g.measureText('Hxg');
  return {id: sp.id, font: sp.font || ('drawn: ' + sp.draw), px, ascent: m.fontBoundingBoxAscent,
          descent: m.fontBoundingBoxDescent, engine: engineName(),
          coverage: '4-bit alpha, one hex digit per pixel', glyphs};
}

/* ---- a port of tools/patch/pfont.py ---- */
function pyRound(v){                               // Python's round(): halves to even
  const f = Math.floor(v), d = v - f;
  return d > .5 ? f + 1 : d < .5 ? f : (f % 2 === 0 ? f : f + 1);
}
function level(v, bpp){ return bpp === 1 ? (v >= 8 ? 1 : 0) : v <= 1 ? 0 : v <= 7 ? 1 : v <= 13 ? 2 : 3; }
function avg565(a, b){ return (a & b) + (((a ^ b) & 0xF7DE) >> 1); }
function ramp(ink, bg){ const h = avg565(ink, bg); return [bg, avg565(bg, h), avg565(ink, h), ink]; }
function rgb565(r, g, b){ return (Math.floor((r * 31 + 127) / 255) << 11) | (Math.floor((g * 63 + 127) / 255) << 5) | Math.floor((b * 31 + 127) / 255); }
function hex565(hex){ return rgb565(parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)); }
function to_rgb(c){ return [Math.floor((c >> 11) * 255 / 31), Math.floor(((c >> 5) & 63) * 255 / 63), Math.floor((c & 31) * 255 / 31)]; }

function makeFont(r, chars, bpp = 2, alias = {}){
  chars = [...new Set([...chars])].sort();
  const src = {};
  for (const c of chars){
    const s = alias[c] || c;
    if (!r.glyphs[s]) throw new Error(`${r.id}: ${JSON.stringify(s)} not in the raster`);
    src[c] = r.glyphs[s];
  }
  const inked = Object.values(src).filter(g => g.rows.length);
  const top = Math.min(...inked.map(g => g.y));
  const bot = Math.max(...inked.map(g => g.y + g.rows.length));
  const per = bpp === 1 ? 8 : 1;
  const H = Math.ceil((bot - top) / per) * per;
  const glyphs = {};
  for (const [c, g] of Object.entries(src)){
    let adv = pyRound(g.adv);
    if (!g.rows.length){ glyphs[c] = {adv, off: 0, w: 0, cols: []}; continue; }
    let off = g.x; const w = g.rows[0].length;
    if (off < 0) off = 0;
    if (off + w > adv) adv = off + w;
    const cols = [];
    for (let x = 0; x < w; x++){
      const col = new Array(H).fill(0);
      g.rows.forEach((row, y) => { col[g.y - top + y] = level(parseInt(row[x], 16), bpp); });
      cols.push(col);
    }
    glyphs[c] = {adv, off, w, cols};
  }
  const order = Object.keys(glyphs).sort();
  const f = {id: r.id, top, H, bpp, glyphs, first: order[0].charCodeAt(0), last: order[order.length - 1].charCodeAt(0)};
  f.width = (text, spacing = 0) => [...text].reduce((s, c) => s + (glyphs[c] ? glyphs[c].adv + spacing : 0), 0);
  f.glyphBytes = c => {
    const cols = glyphs[c].cols;
    if (bpp === 1) return cols.length * H / 8;
    const stream = cols.flat();
    let n = 0, i = 0;
    while (i < stream.length){ let j = i; while (j < stream.length && stream[j] === stream[i] && j - i < 63) j++; n++; i = j; }
    return n + 1;
  };
  f.size = () => 9 + (f.last - f.first + 1) + 5 * order.length + order.reduce((s, c) => s + f.glyphBytes(c), 0);
  /* fb: a Uint16Array of 320 x 170 RGB565 pixels, row-major; returns the last column of the last cell */
  f.render = (fb, text, x, y, ink, bg, align = 0, spacing = 0, W = 320, Hs = 170) => {
    const wd = f.width(text, spacing);
    if (align === 1) x = x - wd + 1; else if (align === 2) x = x - Math.floor(wd / 2);
    const cols = bpp === 2 ? ramp(ink, bg) : [bg, ink];
    for (const c of text){
      const g = glyphs[c]; if (!g) continue;
      for (let r = 0; r < g.adv + spacing; r++){
        const cx = x + r; if (cx < 0 || cx >= W) continue;
        const col = r >= g.off && r < g.off + g.w ? g.cols[r - g.off] : null;
        for (let k = 0; k < H; k++){ const yy = y + k; if (yy >= 0 && yy < Hs) fb[yy * W + cx] = col ? cols[col[k]] : bg; }
      }
      x += g.adv + spacing;
    }
    return x - 1;
  };
  return f;
}

root.Glyphs = {ASCII, KINDS, FAMILIES, spec, fontCss, loadFonts, DRAW, raster, makeFont, pyRound, level,
               avg565, ramp, rgb565, hex565, to_rgb};
})(window);
