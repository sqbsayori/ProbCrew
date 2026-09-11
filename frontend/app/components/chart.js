/**
 * 依赖为零的 Canvas 图表。
 *
 * 为什么不用 ECharts：原型要求离线、免构建、零 CDN。
 * 我们只需要折线/柱状两种图，自己画反而更小更快，
 * 而且能精确控制离散分布（柱状）与连续分布（曲线）的差异。
 */

const CSS = {
  grid: '#eef2f7',
  axis: '#cbd5e1',
  text: '#94a3b8',
  label: '#475569',
};

/** 取一个"好看"的刻度间隔 */
function niceStep(range, targetTicks = 5) {
  const rough = range / targetTicks;
  const mag = 10 ** Math.floor(Math.log10(rough || 1));
  const norm = rough / mag;
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return step * mag;
}

function fmt(v) {
  if (!Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a === 0) return '0';
  if (a >= 1000 || a < 0.01) return v.toExponential(1).replace('e+', 'e');
  return String(Math.round(v * 1000) / 1000);
}

/**
 * 绘制图表。
 * @param {HTMLCanvasElement} canvas
 * @param {{
 *   series: Array<{x:number[], y:number[], color:string, type:'line'|'bar', label?:string, fill?:boolean}>,
 *   xLabel?:string, yLabel?:string, yMin?:number, yMax?:number
 * }} spec
 */
export function drawChart(canvas, spec) {
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(rect.width, 240);
  const height = Math.max(rect.height || 220, 140);

  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const series = (spec.series || []).filter((s) => s && s.x?.length);
  if (!series.length) {
    ctx.fillStyle = CSS.text;
    ctx.font = '13px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('暂无数据', width / 2, height / 2);
    return;
  }

  const pad = { top: 16, right: 16, bottom: spec.xLabel ? 34 : 22, left: 52 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  // 取值范围
  let xMin = Infinity;
  let xMax = -Infinity;
  let yMin = spec.yMin ?? 0;
  let yMax = spec.yMax ?? -Infinity;
  for (const s of series) {
    for (const v of s.x) {
      if (v < xMin) xMin = v;
      if (v > xMax) xMax = v;
    }
    if (spec.yMax == null) {
      for (const v of s.y) if (Number.isFinite(v) && v > yMax) yMax = v;
    }
  }
  if (!Number.isFinite(xMin) || xMax === xMin) {
    xMin = 0;
    xMax = 1;
  }
  if (!Number.isFinite(yMax) || yMax === 0) yMax = 1;
  if (spec.yMin == null) yMin = 0;
  yMax = yMax * 1.08;

  const sx = (v) => pad.left + ((v - xMin) / (xMax - xMin || 1)) * plotW;
  const sy = (v) => pad.top + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;

  // ---- 网格 + Y 轴刻度 ----
  const step = niceStep(yMax - yMin);
  ctx.font = '11px system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let v = yMin; v <= yMax + step * 0.5; v += step) {
    const y = sy(v);
    if (y < pad.top - 1 || y > pad.top + plotH + 1) continue;
    ctx.strokeStyle = CSS.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + plotW, y);
    ctx.stroke();
    ctx.fillStyle = CSS.text;
    ctx.fillText(fmt(v), pad.left - 7, y);
  }

  // ---- 坐标轴 ----
  ctx.strokeStyle = CSS.axis;
  ctx.beginPath();
  ctx.moveTo(pad.left, pad.top);
  ctx.lineTo(pad.left, pad.top + plotH);
  ctx.lineTo(pad.left + plotW, pad.top + plotH);
  ctx.stroke();

  // ---- X 轴刻度 ----
  const xStep = niceStep(xMax - xMin, 6);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.fillStyle = CSS.text;
  for (let v = Math.ceil(xMin / xStep) * xStep; v <= xMax; v += xStep) {
    const x = sx(v);
    ctx.beginPath();
    ctx.moveTo(x, pad.top + plotH);
    ctx.lineTo(x, pad.top + plotH + 4);
    ctx.stroke();
    ctx.fillText(fmt(Math.round(v * 1000) / 1000), x, pad.top + plotH + 7);
  }

  // ---- 数据 ----
  for (const s of series) {
    ctx.strokeStyle = s.color || '#4f46e5';
    ctx.fillStyle = s.color || '#4f46e5';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';

    if (s.type === 'bar') {
      const barW = Math.max(2, Math.min(18, plotW / Math.max(s.x.length, 1) - 2));
      for (let k = 0; k < s.x.length; k += 1) {
        const cx = sx(s.x[k]);
        const top = sy(s.y[k]);
        const base = sy(Math.max(yMin, 0));
        ctx.globalAlpha = 0.82;
        ctx.fillRect(cx - barW / 2, top, barW, Math.max(base - top, 0));
      }
      ctx.globalAlpha = 1;
    } else {
      ctx.beginPath();
      for (let k = 0; k < s.x.length; k += 1) {
        const px = sx(s.x[k]);
        const py = sy(s.y[k]);
        if (k === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();
      if (s.fill) {
        ctx.globalAlpha = 0.12;
        ctx.lineTo(sx(s.x[s.x.length - 1]), sy(yMin));
        ctx.lineTo(sx(s.x[0]), sy(yMin));
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 1;
      }
    }
  }

  // ---- 轴标题 ----
  if (spec.xLabel) {
    ctx.fillStyle = CSS.label;
    ctx.font = '11.5px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText(spec.xLabel, pad.left + plotW / 2, height - 2);
  }
  if (spec.yLabel) {
    ctx.save();
    ctx.translate(11, pad.top + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillStyle = CSS.label;
    ctx.font = '11.5px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(spec.yLabel, 0, 0);
    ctx.restore();
  }
}

/** 生成图例 DOM（与 drawChart 解耦，便于布局） */
export function legend(series) {
  const wrap = document.createElement('div');
  wrap.className = 'chart-legend';
  for (const s of series) {
    const item = document.createElement('span');
    item.className = 'chart-legend-item';
    const dot = document.createElement('i');
    dot.style.background = s.color;
    item.append(dot, document.createTextNode(s.label || ''));
    wrap.append(item);
  }
  return wrap;
}
