/**
 * 产物（Artifact）渲染器。
 *
 * 后端 Agent 不直接吐 HTML，而是发 `artifact` 事件（见 events.schema.json），
 * 由前端决定怎么渲染。好处：
 *   - 前端换皮/换图表库不影响后端；
 *   - 同一条产物可以复用到不同页面（比如动画在「动画」页和「知识讲解」里都能挂）；
 *   - 产物可序列化，能落盘做评估与回放。
 *
 * 支持 kind：animation | chart | formula | steps | table | text
 */
import { h, esc } from '../core/dom.js';
import { drawChart, legend } from './chart.js';
import { markdownToHtml } from './markdown.js';
import { renderMathIn, texToHtml } from './katex.js';
import { createAnimationPlayer } from './animation-player.js';

/** 记录本次渲染出来的播放器，便于统一销毁（动画 iframe 必须显式销毁） */
function trackPlayer(el, player) {
  el._player = player;
}

/** 递归销毁元素内所有动画播放器 */
export function destroyArtifacts(root) {
  root?.querySelectorAll?.('*').forEach((n) => {
    if (n._player) {
      try {
        n._player.destroy();
      } catch {
        /* 忽略 */
      }
      n._player = null;
    }
  });
}

/* ------------------------------------------------------------------ */

function renderFormula(payload) {
  const items = payload.items || [];
  return h(
    'div',
    { class: 'artifact artifact-formula' },
    h('div', { class: 'artifact-head' }, '📐 ', payload.title || '关键公式'),
    h(
      'div',
      { class: 'formula-list' },
      ...items.map((tex) =>
        h('div', { class: 'formula-item', html: texToHtml(tex, true) })
      )
    )
  );
}

function renderSteps(payload) {
  const steps = payload.steps || [];
  return h(
    'div',
    { class: 'artifact artifact-steps' },
    h(
      'div',
      { class: 'artifact-head' },
      '🪜 ',
      payload.title || '解题步骤',
      h('span', { class: 'tag tag-gray', style: { marginLeft: '8px' } }, `${steps.length} 步`)
    ),
    h(
      'div',
      { class: 'steps-list' },
      ...steps.map((s) =>
        h(
          'div',
          { class: 'step-card' },
          h(
            'div',
            { class: 'step-card-head' },
            h('span', { class: 'step-no' }, `Step ${s.index}`),
            h('strong', {}, s.title || '')
          ),
          h('div', { class: 'step-body', html: markdownToHtml(s.body || '') })
        )
      )
    )
  );
}

function renderTable(payload) {
  const cols = payload.columns || [];
  const rows = payload.rows || [];
  const table = h(
    'table',
    { class: 'data' },
    h('thead', {}, h('tr', {}, ...cols.map((c) => h('th', {}, String(c))))),
    h(
      'tbody',
      {},
      ...rows.map((r) => h('tr', {}, ...r.map((c) => h('td', {}, String(c ?? '')))))
    )
  );
  return h(
    'div',
    { class: 'artifact artifact-table' },
    h('div', { class: 'artifact-head' }, '📋 ', payload.title || '数据表'),
    h('div', { class: 'table-wrap' }, table)
  );
}

function renderChart(payload) {
  const wrap = h('div', { class: 'artifact artifact-chart' });
  const isDiscrete = payload.kind === 'discrete';

  const pdfCanvas = h('canvas', { class: 'chart-canvas', style: { height: '210px' } });
  const cdfCanvas = h('canvas', { class: 'chart-canvas', style: { height: '190px' } });

  wrap.append(
    h(
      'div',
      { class: 'artifact-head' },
      '📊 ',
      payload.title || '分布图像',
      h(
        'span',
        { class: 'tag tag-gray', style: { marginLeft: '8px' } },
        `E[X]=${fmtNum(payload.mean)}  Var(X)=${fmtNum(payload.var)}`
      )
    ),
    legend([
      { color: '#4f46e5', label: isDiscrete ? 'PMF' : 'PDF' },
      { color: '#12b886', label: 'CDF' },
    ]),
    h('div', { class: 'chart-block' }, h('div', { class: 'chart-caption' }, isDiscrete ? '概率质量函数 PMF' : '概率密度函数 PDF'), pdfCanvas),
    h('div', { class: 'chart-block' }, h('div', { class: 'chart-caption' }, '累积分布函数 CDF'), cdfCanvas)
  );

  // 元素入 DOM 后才能量到宽高，故延后一帧绘制
  requestAnimationFrame(() => {
    drawChart(pdfCanvas, {
      series: [
        {
          x: payload.pdf?.x || [],
          y: payload.pdf?.y || [],
          color: '#4f46e5',
          type: isDiscrete ? 'bar' : 'line',
          label: isDiscrete ? 'PMF' : 'PDF',
          fill: !isDiscrete,
        },
      ],
      xLabel: 'x',
      yLabel: isDiscrete ? 'P(X=x)' : 'f(x)',
    });
    drawChart(cdfCanvas, {
      series: [
        {
          x: payload.cdf?.x || [],
          y: payload.cdf?.y || [],
          color: '#12b886',
          type: 'line',
          label: 'CDF',
          fill: true,
        },
      ],
      xLabel: 'x',
      yLabel: 'F(x)',
      yMin: 0,
      yMax: 1,
    });
  });

  return wrap;
}

function renderAnimation(payload) {
  const player = createAnimationPlayer({
    url: payload.url,
    title: payload.title,
    description: payload.description || payload.reason || '',
    controls: payload.controls || {},
    height: 560,
  });
  const el = h('div', { class: 'artifact artifact-animation' }, player.el);
  trackPlayer(el, player);
  return el;
}

function renderText(payload) {
  return h('div', {
    class: 'artifact artifact-text',
    html: markdownToHtml(payload.content || ''),
  });
}

function fmtNum(v) {
  if (v == null || !Number.isFinite(Number(v))) return '—';
  const n = Number(v);
  if (Math.abs(n) >= 10000 || (n !== 0 && Math.abs(n) < 0.001)) return n.toExponential(2);
  return String(Math.round(n * 10000) / 10000);
}

const RENDERERS = {
  formula: renderFormula,
  steps: renderSteps,
  table: renderTable,
  chart: renderChart,
  animation: renderAnimation,
  text: renderText,
};

/**
 * 渲染一条产物。
 * @param {'animation'|'chart'|'formula'|'steps'|'table'|'text'} kind
 * @param {object} payload
 * @returns {HTMLElement}
 */
export function renderArtifact(kind, payload = {}) {
  const fn = RENDERERS[kind];
  if (!fn) {
    return h(
      'div',
      { class: 'artifact' },
      h('div', { class: 'artifact-head' }, `未知产物类型：${esc(kind)}`)
    );
  }
  const el = fn(payload);
  if (kind !== 'chart') renderMathIn(el);
  return el;
}
