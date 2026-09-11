/**
 * 分布可视化页。
 *
 * 两种使用方式，刻意分开：
 *   A. **交互式观察器**（左侧）：直接调 `/api/distributions/...`，毫秒级响应、不花 Token。
 *      这是"能本地算的就别问模型"原则的体现。
 *   B. **Agent 解读**（下方）：把当前选的分布交给 Visualization Agent，
 *      由它用自然语言讲形状与应用场景，并走完整的多 Agent 协作流程。
 *
 * 页面里所有公式与数值都来自后端 SymPy（/api/distributions/{d}/properties），
 * 前端只负责画图与排版 —— 这样"期望方差算错"在架构上就不可能发生。
 */
import { h, injectStyles, debounce, fmtNum } from '../../core/dom.js';
import { store } from '../../core/store.js';
import * as api from '../../core/api.js';
import { drawChart } from '../../components/chart.js';
import { texToHtml } from '../../components/katex.js';
import { createRunPanel } from '../../components/run-panel.js';

injectStyles('/app/features/visualize/styles.css');

const MODE_LABEL = { pdf: 'PDF / PMF', cdf: 'CDF' };

let panel = null;
let observers = [];

export function mount(container) {
  const dists = store.get('distributions') || [];
  if (!dists.length) {
    container.append(
      h('div', { class: 'card' }, h('div', { class: 'card-title' }, '📊 分布可视化'),
        h('div', { class: 'empty' }, '未能读取分布清单（/api/distributions），请确认后端已启动。'))
    );
    return;
  }

  const state = {
    dist: dists[0].key,
    params: Object.fromEntries(dists[0].params.map((p) => [p.key, p.default])),
    mode: 'pdf',
  };

  /* ---------- 左侧：控制面板 ---------- */
  const chips = h('div', { class: 'dist-chips' });
  const paramsBox = h('div', {});
  const modeBox = h('div', { class: 'row mt-12' });

  const buildChips = () => {
    chips.innerHTML = '';
    for (const d of dists) {
      chips.append(
        h(
          'button',
          {
            class: `dist-chip${d.key === state.dist ? ' active' : ''}`,
            onclick: () => {
              state.dist = d.key;
              state.params = Object.fromEntries(d.params.map((p) => [p.key, p.default]));
              buildChips();
              buildParams();
              refresh();
            },
          },
          d.name.split(' ')[0]
        )
      );
    }
  };

  const buildParams = () => {
    const d = dists.find((x) => x.key === state.dist);
    paramsBox.innerHTML = '';
    for (const p of d.params) {
      const out = h('b', {}, fmtNum(state.params[p.key], 3));
      paramsBox.append(
        h(
          'div',
          { class: 'param-row' },
          h('label', {}, h('span', {}, p.label), out),
          h('input', {
            type: 'range',
            min: p.min,
            max: p.max,
            step: p.step,
            value: state.params[p.key],
            oninput: (ev) => {
              state.params[p.key] = Number(ev.target.value);
              out.textContent = fmtNum(state.params[p.key], 3);
              refreshDebounced();
            },
          })
        )
      );
    }
  };

  const buildModes = () => {
    modeBox.innerHTML = '';
    for (const m of ['pdf', 'cdf']) {
      modeBox.append(
        h(
          'button',
          {
            class: `btn btn-sm${state.mode === m ? ' btn-primary' : ''}`,
            onclick: () => {
              state.mode = m;
              buildModes();
              refresh();
            },
          },
          MODE_LABEL[m]
        )
      );
    }
  };

  /* ---------- 右侧：图像与性质 ---------- */
  const pdfCanvas = h('canvas', { class: 'chart-canvas', style: { height: '230px' } });
  const cdfCanvas = h('canvas', { class: 'chart-canvas', style: { height: '200px' } });
  const propBox = h('div', {});
  const statusLine = h('span', { class: 'small muted' }, '');

  /* ---------- 渲染 ---------- */
  async function refresh() {
    statusLine.textContent = '计算中…';
    try {
      const [props, pdfData, cdfData] = await Promise.all([
        api.getJSON(
          `/api/distributions/${state.dist}/properties?${new URLSearchParams(
            Object.entries(state.params).map(([k, v]) => [k, String(v)])
          )}`
        ),
        api.distributionSeries(state.dist, state.params, 'pdf'),
        api.distributionSeries(state.dist, state.params, 'cdf'),
      ]);

      const isDiscrete = props.kind === 'discrete';
      const accent = '#4f46e5';

      drawChart(pdfCanvas, {
        series: [
          {
            x: pdfData.x,
            y: pdfData.y,
            color: accent,
            type: isDiscrete ? 'bar' : 'line',
            fill: !isDiscrete,
          },
        ],
        xLabel: 'x',
        yLabel: isDiscrete ? 'P(X=x)' : 'f(x)',
      });
      drawChart(cdfCanvas, {
        series: [{ x: cdfData.x, y: cdfData.y, color: '#12b886', type: 'line', fill: true }],
        xLabel: 'x',
        yLabel: 'F(x)',
        yMin: 0,
        yMax: 1,
      });

      propBox.innerHTML = '';
      const rows = [
        ['概率函数 PDF / PMF', props.pdf_latex],
        ['分布函数 CDF', props.cdf_latex],
        ['数学期望', props.mean_latex],
        ['方差', props.var_latex],
        ['矩母函数 MGF', props.mgf_latex],
      ];
      for (const [label, tex] of rows) {
        propBox.append(
          h(
            'div',
            { class: 'prop-card' },
            h('div', { class: 'prop-label' }, label),
            h('div', { html: texToHtml(tex, true) })
          )
        );
      }
      statusLine.textContent = `E[X] = ${fmtNum(props.mean)} · Var(X) = ${fmtNum(props.variance ?? props.var)} · σ = ${fmtNum(props.std)}`;
    } catch (err) {
      statusLine.textContent = `计算失败：${err.message}`;
    }
  }
  const refreshDebounced = debounce(refresh, 120);

  buildChips();
  buildParams();
  buildModes();

  const controlPanel = h(
    'div',
    { class: 'card' },
    h('div', { class: 'card-title' }, '⚙️ 参数'),
    chips,
    paramsBox,
    h('div', { class: 'small muted mt-12' }, '显示'),
    modeBox,
    h('div', { class: 'viz-note' }, '拖动滑块即时重算：公式与数值均由后端 SymPy 推导，前端只负责画图。')
  );

  const chartPanel = h(
    'div',
    { class: 'card' },
    h(
      'div',
      { class: 'card-title' },
      '📈 图像',
      h('span', { class: 'sub' }, '上方为原始分布，下方为累积分布')
    ),
    h('div', { class: 'viz-canvas-box' }, h('div', { class: 'viz-caption' }, 'PDF / PMF'), pdfCanvas),
    h('div', { class: 'viz-canvas-box' }, h('div', { class: 'viz-caption' }, 'CDF'), cdfCanvas),
    h('div', { class: 'row-between mt-8' }, statusLine)
  );

  container.append(
    h('div', { class: 'viz-layout' }, controlPanel, h('div', {}, chartPanel, h('div', { class: 'card', style: { marginTop: '16px' } }, h('div', { class: 'card-title' }, '🧮 符号推导结果'), propBox)))
  );

  /* ---------- Agent 解读（复用共享运行面板） ---------- */
  const agentHost = h('div', { class: 'mt-16' });
  container.append(
    h(
      'div',
      { class: 'card mt-16' },
      h('div', { class: 'card-title' }, '🤖 让 Visualization Agent 解读'),
      h(
        'p',
        { class: 'small muted' },
        '上面的观察器是本地计算。如果你想要自然语言的解读（形状特征、典型应用场景），' +
          '可以让 Agent 来做 —— 它同样只引用 SymPy 的结果，不会自己编公式。'
      ),
      h(
        'button',
        {
          class: 'btn btn-primary mt-8',
          onclick: () => {
            const d = dists.find((x) => x.key === state.dist);
            const nums = d.params
              .map((p) => `${p.label.replace(/\s.*/, '')}=${fmtNum(state.params[p.key], 4)}`)
              .join('，');
            panel?.ask(`请解读 ${d.name} 在 ${nums} 下的性质与典型应用场景`);
          },
        },
        '🤖 生成 Agent 解读'
      )
    ),
    agentHost
  );

  panel = createRunPanel(agentHost, {
    placeholder: '例如：二项分布 B(20,0.3) 的期望和方差是多少？',
    examples: ['正态分布 N(0,1) 的性质', '泊松分布 λ=3 的期望方差', '指数分布的无记忆性'],
    hint: 'Agent 会调用 SymPy 工具计算，再做自然语言解读',
    showTrace: true,
  });

  refresh();

  // 窗口尺寸变化时重绘（canvas 需要重新按 DPR 计算）
  const onResize = debounce(() => {
    api.distributionSeries(state.dist, state.params, 'pdf').then((d) => {
      drawChart(pdfCanvas, {
        series: [{ x: d.x, y: d.y, color: '#4f46e5', type: d.kind === 'discrete' ? 'bar' : 'line', fill: d.kind !== 'discrete' }],
        xLabel: 'x',
        yLabel: d.kind === 'discrete' ? 'P(X=x)' : 'f(x)',
      });
    });
  }, 200);
  window.addEventListener('resize', onResize);
  observers.push(() => window.removeEventListener('resize', onResize));
}

export function unmount() {
  panel?.destroy();
  panel = null;
  observers.forEach((off) => off());
  observers = [];
}
