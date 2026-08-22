/* 大型地圖的平移與縮放。
 *
 * 把 <svg> 裡既有的內容包進一個 <g data-zoom>，之後所有的變形都作用在那個群組上，
 * 投影的程式碼因此完全不必知道有這回事。群組標了 data-zoom，是為了讓重畫的程式
 * （切換圖層、時段、平假日）認得出它：重畫時清空群組而不是清空整張 svg，
 * 縮放的位置與倍率才不會每按一次控制項就跳回原點。
 *
 * 三件事刻意違反「照著倍率一起放大」的直覺：
 *
 * 其一，線寬不隨倍率變。放到8倍時，一條跟著放大的區界會粗到蓋掉它本來要分隔的填色。
 *
 * 其二，文字反向縮小，維持固定的螢幕字級。地圖放大是為了看清楚小的區，
 * 若標籤跟著放大，中區的標籤會比中區本身還大，等於白放。
 *
 * 其三，倍率超過2.2倍才顯示小區的標籤。全圖時中區只有0.9平方公里，
 * 塞不下標籤所以留給 tooltip；放大之後塞得下了，就該讓它出現。
 *
 * 滾輪是「合作式」的：直接滾動捲頁面並提示，⌘／Ctrl 加滾輪才縮放。
 * 這張圖將近1120單位寬、佔滿版面，若滾輪直接縮放，滑鼠每次經過都會把捲動吃掉。
 * 右上角的「滾輪」開關可以改成直接縮放，選擇記在 sessionStorage，一個分頁內有效。
 */
function enableMapZoom(svg, opts = {}) {
  const NS = 'http://www.w3.org/2000/svg';
  const MAX = opts.max || 12;
  const DEEP = opts.deep || 2.2;          // 超過這個倍率才顯示小區的標籤
  const KEY = 'tc-mapzoom-wheel';

  const vb = svg.viewBox.baseVal;
  const W = vb.width, H = vb.height;
  if (!W || !H) return null;              // 還沒畫、沒有 viewBox 就沒有座標系可算

  const g = document.createElementNS(NS, 'g');
  g.setAttribute('data-zoom', '');
  while (svg.firstChild) g.appendChild(svg.firstChild);
  svg.appendChild(g);
  svg.classList.add('zoomable');

  let k = 1, tx = 0, ty = 0;

  // 讓畫面始終被圖蓋滿：倍率 k 時內容寬 W*k，位移可以從 -(k-1)*W 到 0，
  // 超出這個範圍邊緣就會露出空白。
  const clamp = () => {
    tx = Math.min(0, Math.max(-(k - 1) * W, tx));
    ty = Math.min(0, Math.max(-(k - 1) * H, ty));
  };
  const apply = () => {
    clamp();
    g.setAttribute('transform',
      `translate(${tx.toFixed(2)} ${ty.toFixed(2)}) scale(${k.toFixed(4)})`);
    svg.style.setProperty('--zk', k.toFixed(4));   // 文字用它反向縮小
    svg.classList.toggle('zoomed', k > 1.001);
    svg.classList.toggle('zdeep', k > DEEP);
    if (out) out.textContent = `×${k.toFixed(1)}`;
    if (reset) reset.disabled = k <= 1.001;
  };

  /** 螢幕座標換成 viewBox 座標（變形之前的那一套） */
  const toLocal = (cx, cy) => {
    const r = svg.getBoundingClientRect();
    return [(cx - r.left) / r.width * W, (cy - r.top) / r.height * H];
  };

  /** 以 (cx, cy) 為定點縮放 f 倍：游標底下的那個點不動 */
  function zoomAt(cx, cy, f) {
    const [px, py] = toLocal(cx, cy);
    const next = Math.min(MAX, Math.max(1, k * f));
    if (next === k) return;
    tx = px - (px - tx) * (next / k);
    ty = py - (py - ty) * (next / k);
    k = next;
    apply();
  }
  function zoomCentre(f) {
    const r = svg.getBoundingClientRect();
    zoomAt(r.left + r.width / 2, r.top + r.height / 2, f);
  }
  function reset0() { k = 1; tx = 0; ty = 0; apply(); }

  /* ── 控制列 ────────────────────────────────────────────────────────── */
  // svg 不一定被定位過的容器包著，這裡補一個，浮動的控制列才有東西可以定位。
  let host = svg.parentElement;
  if (!host.classList.contains('mapwrap')) {
    const w = document.createElement('div');
    w.className = 'mapwrap';
    svg.replaceWith(w);
    w.appendChild(svg);
    host = w;
  }
  const bar = document.createElement('div');
  bar.className = 'zoomctl';
  bar.innerHTML =
    '<button type="button" data-a="in"  title="放大" aria-label="放大">+</button>' +
    '<button type="button" data-a="out" title="縮小" aria-label="縮小">−</button>' +
    '<button type="button" data-a="reset" title="重設" aria-label="重設縮放">RESET</button>' +
    '<span class="lvl" aria-live="polite">×1.0</span>' +
    '<button type="button" data-a="wheel" class="wheel" aria-pressed="false"' +
    ' title="開啟後，直接滾動滑鼠滾輪即可縮放">滾輪</button>';
  host.appendChild(bar);
  const out = bar.querySelector('.lvl');
  const reset = bar.querySelector('[data-a="reset"]');
  const wheelBtn = bar.querySelector('[data-a="wheel"]');

  let wheelZoom = false;
  try { wheelZoom = sessionStorage.getItem(KEY) === '1'; } catch { /* 無痕模式 */ }
  const setWheel = on => {
    wheelZoom = on;
    wheelBtn.setAttribute('aria-pressed', String(on));
    try { sessionStorage.setItem(KEY, on ? '1' : '0'); } catch { /* 無痕模式 */ }
  };
  setWheel(wheelZoom);

  bar.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    e.stopPropagation();
    ({ in: () => zoomCentre(1.5), out: () => zoomCentre(1 / 1.5),
       reset: reset0, wheel: () => setWheel(!wheelZoom) })[b.dataset.a]();
  });

  const hint = document.createElement('div');
  hint.className = 'zoomhint';
  hint.textContent = navigator.platform.includes('Mac')
    ? '⌘ ＋ 滾輪可縮放，或按右上角「滾輪」' : 'Ctrl ＋ 滾輪可縮放，或按右上角「滾輪」';
  host.appendChild(hint);
  let hintTimer = 0;
  const showHint = () => {
    hint.classList.add('on');
    clearTimeout(hintTimer);
    hintTimer = setTimeout(() => hint.classList.remove('on'), 1400);
  };

  /* ── 滾輪 ──────────────────────────────────────────────────────────── */
  svg.addEventListener('wheel', e => {
    if (!(e.ctrlKey || e.metaKey || wheelZoom)) { showHint(); return; }
    e.preventDefault();
    // deltaMode 1 是「行」、2 是「頁」，換算成像素，觸控板與段落式滾輪的幅度才相當
    const px = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 100 : 1);
    zoomAt(e.clientX, e.clientY, Math.exp(-px * 0.0022));
  }, { passive: false });

  /* ── 拖曳平移、雙指縮放 ────────────────────────────────────────────── */
  const pts = new Map();
  let last = null, pinch = 0, moved = 0;

  svg.addEventListener('pointerdown', e => {
    if (e.button != null && e.button !== 0) return;
    pts.set(e.pointerId, e);
    moved = 0;
    if (pts.size === 1) last = e;
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      pinch = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
    }
  });

  svg.addEventListener('pointermove', e => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, e);
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      const d = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      if (pinch) zoomAt((a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2, d / pinch);
      pinch = d;
      e.preventDefault();
      return;
    }
    if (k <= 1.001 || !last) return;      // 全圖狀態沒有東西可以平移
    const r = svg.getBoundingClientRect();
    const dx = (e.clientX - last.clientX) / r.width * W;
    const dy = (e.clientY - last.clientY) / r.height * H;
    moved += Math.abs(e.clientX - last.clientX) + Math.abs(e.clientY - last.clientY);
    tx += dx; ty += dy; last = e;
    svg.setPointerCapture?.(e.pointerId);
    apply();
  });

  const end = e => {
    pts.delete(e.pointerId);
    if (pts.size < 2) pinch = 0;
    if (pts.size === 0) last = null;
  };
  svg.addEventListener('pointerup', end);
  svg.addEventListener('pointercancel', end);
  svg.addEventListener('lostpointercapture', end);

  // 拖曳結束時滑鼠正好停在某個區上，不該同時被算成點選那個區
  svg.addEventListener('click', e => {
    if (moved > 6) { e.stopPropagation(); e.preventDefault(); moved = 0; }
  }, true);

  svg.addEventListener('dblclick', e => {
    e.preventDefault();
    zoomAt(e.clientX, e.clientY, e.shiftKey ? 1 / 2 : 2);
  });

  /* ── 鍵盤 ──────────────────────────────────────────────────────────── */
  svg.setAttribute('tabindex', svg.getAttribute('tabindex') ?? '0');
  svg.addEventListener('keydown', e => {
    const step = 60 / k;
    const act = {
      '+': () => zoomCentre(1.5), '=': () => zoomCentre(1.5),
      '-': () => zoomCentre(1 / 1.5), '_': () => zoomCentre(1 / 1.5),
      '0': reset0, Escape: reset0,
      ArrowLeft: () => { tx += step; apply(); }, ArrowRight: () => { tx -= step; apply(); },
      ArrowUp: () => { ty += step; apply(); }, ArrowDown: () => { ty -= step; apply(); },
    }[e.key];
    if (!act) return;
    e.preventDefault();
    act();
  });

  apply();
  return { reset: reset0, zoomCentre, group: g };
}
