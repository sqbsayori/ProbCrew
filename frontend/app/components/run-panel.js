/**
 * 运行面板（Run Panel）—— 多个 feature 共用的"提问 → 协作 → 产出"交互区。
 *
 * 复用它的意义：知识讲解、题目讲解、分布可视化三个页面的交互骨架完全一样，
 * 差别只在提示语和示例问题。抽成一个组件后：
 *   - 改一次交互，三个页面同时生效；
 *   - 每个人只需要关注自己 Agent 的后端逻辑，不必重复写前端。
 *
 * 它同时负责：流式回答渲染、多 Agent 轨迹、产物挂载、HITL 人工协同。
 */
import { h, clear, toast } from '../core/dom.js';
import { store } from '../core/store.js';
import * as api from '../core/api.js';
import { markdownToHtml } from './markdown.js';
import { renderMathIn } from './katex.js';
import { renderArtifact, destroyArtifacts } from './artifacts.js';
import { createTrace } from './trace.js';

/**
 * @param {HTMLElement} container
 * @param {{
 *   placeholder?: string,
 *   examples?: string[],
 *   hint?: string,
 *   showTrace?: boolean,
 *   autoFocus?: boolean,
 * }} [opts]
 * @returns {{ destroy: () => void, ask: (q:string)=>void }}
 */
export function createRunPanel(container, opts = {}) {
  const {
    placeholder = '例如：贝叶斯公式和全概率公式是什么关系？',
    examples = [],
    hint = '',
    showTrace = true,
  } = opts;

  let controller = null;
  let running = false;
  const blocks = new Map(); // agentId -> { el, body, pending, raf }
  let trace = null;

  /* ---------------- 结构 ---------------- */

  const input = h('textarea', {
    class: 'textarea',
    placeholder,
    rows: 2,
    onkeydown: (ev) => {
      if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) {
        ev.preventDefault();
        submit();
      }
    },
  });

  const sendBtn = h(
    'button',
    { class: 'btn btn-primary', onclick: () => submit() },
    '🚀 开始协作'
  );

  const stopBtn = h(
    'button',
    {
      class: 'btn',
      style: { display: 'none' },
      onclick: () => {
        controller?.abort();
        setRunning(false);
        toast('已停止本轮生成', 'warning');
      },
    },
    '⏹ 停止'
  );

  const exampleRow = h(
    'div',
    { class: 'row wrap mt-8' },
    ...examples.map((q) =>
      h(
        'button',
        {
          class: 'btn btn-sm',
          onclick: () => {
            input.value = q;
            submit();
          },
        },
        q
      )
    )
  );

  const askCard = h(
    'div',
    { class: 'card ask-card' },
    input,
    h(
      'div',
      { class: 'row-between wrap mt-8' },
      h('div', { class: 'small muted' }, hint || 'Ctrl + Enter 快速发送'),
      h('div', { class: 'row' }, stopBtn, sendBtn)
    ),
    examples.length ? exampleRow : null
  );

  const answerBody = h('div', { class: 'answer-body' });
  const artifactHost = h('div', { class: 'artifact-host' });
  const hitlHost = h('div', { class: 'hitl-host' });
  const answerCard = h(
    'div',
    { class: 'card answer-card' },
    h(
      'div',
      { class: 'card-title' },
      '💬 回答',
      h('span', { class: 'sub', id: 'answer-sub' }, '等待提问')
    ),
    answerBody,
    artifactHost,
    hitlHost
  );

  const traceHost = h('div', { class: 'card trace-card' });
  const sideCol = showTrace
    ? h(
        'aside',
        { class: 'side-col' },
        traceHost,
        h(
          'div',
          { class: 'card small muted' },
          h('div', { class: 'card-title' }, 'ℹ️ 怎么看这个面板'),
          h(
            'ul',
            { style: { paddingLeft: '18px', lineHeight: '1.8' } },
            h('li', {}, '「调度计划」是 Orchestrator 的路由决策'),
            h('li', {}, '「Agent 协作」实时显示谁在跑、调了什么工具'),
            h('li', {}, '工具小圆点变绿 = 调用成功，变红 = 失败'),
            h('li', {}, '出现黄色卡片 = 触发了 HITL 人工协同')
          )
        )
      )
    : null;

  const body = h(
    'div',
    { class: showTrace ? 'grid grid-chat mt-16' : 'mt-16' },
    h('div', { class: 'main-col' }, answerCard),
    sideCol
  );

  container.append(askCard, body);

  if (showTrace) {
    traceHost.append(h('div', { class: 'card-title' }, '🔀 多 Agent 协作轨迹'));
    trace = createTrace(traceHost, { catalog: store.get('agents') || [] });
  }

  /* ---------------- 渲染逻辑 ---------------- */

  const setRunning = (v) => {
    running = v;
    sendBtn.disabled = v;
    sendBtn.textContent = v ? '协作中…' : '🚀 开始协作';
    stopBtn.style.display = v ? '' : 'none';
  };

  const setSub = (text) => {
    const el = answerCard.querySelector('#answer-sub');
    if (el) el.textContent = text;
  };

  /** 重置输出区 */
  function resetOutput() {
    destroyArtifacts(artifactHost);
    clear(answerBody);
    clear(artifactHost);
    clear(hitlHost);
    blocks.clear();
    trace?.reset();
    store.resetRun();
    setSub('协作中…');
  }

  /**
   * 为一个 Agent 创建（或取得）流式输出块。
   * 多个 Agent 并行时会有多个块同时增长 —— 这正是"多 Agent 协作"的直观体现。
   */
  function blockFor(agentId) {
    if (blocks.has(agentId)) return blocks.get(agentId);
    const meta = (store.get('agents') || []).find((a) => a.id === agentId) || {};
    const bodyEl = h('div', { class: 'agent-block-body' });
    const el = h(
      'div',
      { class: 'agent-block', dataset: { agent: agentId } },
      h(
        'div',
        { class: 'agent-block-head' },
        h('span', { class: 'agent-block-ico' }, meta.icon || '🤖'),
        h('strong', {}, meta.name || agentId),
        h('span', { class: 'agent-block-state tag' }, '生成中')
      ),
      bodyEl
    );
    const entry = { el, body: bodyEl, text: '', raf: 0 };
    answerBody.append(el);
    blocks.set(agentId, entry);
    return entry;
  }

  /** 节流渲染：一次回答可能有上千个 delta，用 rAF 合并 */
  function scheduleRender(entry) {
    if (entry.raf) return;
    entry.raf = requestAnimationFrame(() => {
      entry.raf = 0;
      entry.body.innerHTML = markdownToHtml(entry.text);
      renderMathIn(entry.body);
    });
  }

  /* ---------------- HITL ---------------- */

  function showHitl(e) {
    clear(hitlHost);
    const ta = h('textarea', {
      class: 'textarea',
      rows: 2,
      placeholder: '如果你选择「修正」或「补充」，请在这里写清楚要改什么…',
    });
    const actions = h(
      'div',
      { class: 'row wrap mt-12' },
      h(
        'button',
        { class: 'btn btn-success', onclick: () => decide('confirm', '') },
        '✅ 确认采纳'
      ),
      h(
        'button',
        {
          class: 'btn',
          onclick: () => {
            if (!ta.value.trim()) return toast('请先写下你的修正内容', 'warning');
            decide('correct', ta.value.trim());
          },
        },
        '✏️ 按我的修正重写'
      ),
      h(
        'button',
        {
          class: 'btn',
          onclick: () => {
            if (!ta.value.trim()) return toast('请先写下要补充的内容', 'warning');
            decide('supplement', ta.value.trim());
          },
        },
        '➕ 补充说明'
      )
    );

    hitlHost.append(
      h(
        'div',
        { class: 'hitl-box' },
        h(
          'div',
          { class: 'row-between wrap' },
          h('strong', {}, '⏸ 人机协同：关键结论待你确认'),
          h('span', { class: 'tag tag-amber' }, 'HITL')
        ),
        h('p', { class: 'small mt-8' }, e.draft || '（无草稿说明）'),
        ta,
        actions
      )
    );
    setSub('已暂停，等待你确认');
  }

  async function decide(action, text) {
    const runId = store.get('run.runId');
    if (!runId) return;
    clear(hitlHost);
    setRunning(true);
    setSub('按你的决定继续…');
    try {
      await api.resolveHitl(runId, { action, text }, handleEvent);
    } catch (err) {
      fail(err);
    } finally {
      setRunning(false);
    }
  }

  /* ---------------- 事件处理 ---------------- */

  function handleEvent(e) {
    trace?.handle(e);
    store.push('run.events', e);

    switch (e.type) {
      case 'run.start':
        store.set('run.runId', e.run_id);
        store.set('run.status', 'running');
        break;

      case 'plan':
        store.set('run.plan', e.steps || []);
        setSub(`意图：${e.intent || '—'}`);
        break;

      case 'agent.start':
        blockFor(e.agent);
        break;

      case 'agent.delta': {
        const entry = blockFor(e.agent);
        entry.text += e.text || '';
        scheduleRender(entry);
        break;
      }

      case 'agent.end': {
        const entry = blockFor(e.agent);
        entry.body.innerHTML = markdownToHtml(entry.text);
        renderMathIn(entry.body);
        const state = entry.el.querySelector('.agent-block-state');
        if (state) {
          state.textContent = e.ok === false ? '失败' : '完成';
          state.className = `agent-block-state tag ${e.ok === false ? 'tag-red' : 'tag-green'}`;
        }
        if (!entry.text.trim()) entry.el.classList.add('agent-block-empty');
        break;
      }

      case 'artifact': {
        store.push('run.artifacts', { kind: e.kind, payload: e.payload });
        artifactHost.append(renderArtifact(e.kind, e.payload || {}));
        break;
      }

      case 'hitl.request':
        store.set('run.status', 'awaiting_hitl');
        showHitl(e);
        break;

      case 'hitl.resolved':
        setSub('继续生成…');
        break;

      case 'run.end': {
        store.set('run.status', 'done');
        store.set('run.answer', e.final_answer || '');
        // 用后端聚合后的最终答案替换逐 Agent 的流式块（含校验说明与 HITL 修正）
        if (e.final_answer) {
          clear(answerBody);
          const finalEl = h('div', { class: 'final-answer' });
          finalEl.innerHTML = markdownToHtml(e.final_answer);
          answerBody.append(finalEl);
          renderMathIn(finalEl);
        }
        setSub('已完成');
        setRunning(false);
        break;
      }

      case 'error':
        store.set('run.error', e.message);
        setSub('出错了');
        clear(answerBody);
        answerBody.append(
          h(
            'div',
            { class: 'empty', style: { color: 'var(--danger)' } },
            `⚠️ ${e.message || '未知错误'}`
          )
        );
        setRunning(false);
        break;

      default:
        break;
    }
  }

  function fail(err) {
    console.error('[run-panel]', err);
    toast(`请求失败：${err.message}`, 'error');
    setRunning(false);
    setSub('请求失败');
  }

  /* ---------------- 发起一次运行 ---------------- */

  async function submit() {
    const query = input.value.trim();
    if (!query) {
      toast('请先输入问题', 'warning');
      input.focus();
      return;
    }
    if (running) return;

    controller?.abort();
    controller = new AbortController();
    resetOutput();
    setRunning(true);

    // 每次提问生成新的会话 id 会丢失学习记录，这里复用同一个会话
    const sessionId = store.get('sessionId') || 'default';

    try {
      await api.streamChat({ query, sessionId }, handleEvent, controller.signal);
    } catch (err) {
      if (err.name !== 'AbortError') fail(err);
    } finally {
      setRunning(false);
      // 通知其他页面（如学习数据）刷新
      document.dispatchEvent(new CustomEvent('run:finished'));
    }
  }

  return {
    ask: (q) => {
      input.value = q;
      submit();
    },
    /** 只填入输入框、不发送（供例题库/推荐问题"填入后自己改"用） */
    fill: (q) => {
      input.value = q;
      input.focus();
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 140) + 'px';
    },
    /** 当前输入框内容 */
    text: () => input.value,
    destroy() {
      controller?.abort();
      destroyArtifacts(artifactHost);
      blocks.forEach((b) => b.raf && cancelAnimationFrame(b.raf));
    },
  };
}
