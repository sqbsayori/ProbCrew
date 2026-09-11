/**
 * 多 Agent 协作轨迹面板 —— 把"黑盒"变成"可见的协作过程"。
 *
 * 这是本项目最有说服力的演示组件：观众能实时看到
 *   Orchestrator 路由 → 多个 Agent 并行启动 → 工具调用 → Verifier 校验 → HITL 暂停
 * 对应事件协议里的 plan / agent.start / tool.call / agent.end 等。
 *
 * 实现要点：**增量更新 DOM**，不为每个 agent.delta 重渲染整棵树
 * （一次回答会有上千个 delta，全量重渲染会卡）。
 */
import { h } from '../core/dom.js';

const STATUS_TEXT = {
  pending: '待命',
  running: '运行中',
  done: '完成',
  failed: '失败',
  skipped: '跳过',
};

const STATUS_CLASS = {
  pending: 'tag-gray',
  running: 'tag',
  done: 'tag tag-green',
  failed: 'tag tag-red',
  skipped: 'tag tag-gray',
};

/**
 * @param {HTMLElement} container
 * @param {{catalog?: Array<{id,name,icon,accent}>}} [opts]
 */
export function createTrace(container, opts = {}) {
  const catalog = new Map((opts.catalog || []).map((a) => [a.id, a]));
  const rows = new Map(); // agentId -> { root, tools, badge, dur, sum }

  const planBox = h('div', { class: 'trace-plan' });
  const rowsBox = h('div', { class: 'trace-rows' });
  const footer = h('div', { class: 'trace-footer muted small' }, '等待调度…');

  const root = h(
    'div',
    { class: 'trace' },
    h('div', { class: 'trace-section-label' }, '调度计划'),
    planBox,
    h('div', { class: 'trace-section-label' }, 'Agent 协作'),
    rowsBox,
    footer
  );
  container.append(root);

  let startedAt = 0;

  function metaOf(agentId) {
    return catalog.get(agentId) || { id: agentId, name: agentId, icon: '🤖', accent: '#64748b' };
  }

  function ensureRow(agentId) {
    if (rows.has(agentId)) return rows.get(agentId);
    const meta = metaOf(agentId);

    const tools = h('div', { class: 'trace-tools' });
    const badge = h('span', { class: 'tag tag-gray' }, STATUS_TEXT.pending);
    const dur = h('span', { class: 'trace-dur mono' }, '—');
    const sum = h('span', { class: 'trace-sum muted' });

    const row = h(
      'div',
      { class: 'trace-row', dataset: { agent: agentId } },
      h('span', { class: 'trace-ico', style: { background: `${meta.accent}1a`, color: meta.accent } }, meta.icon || '🤖'),
      h(
        'div',
        { class: 'trace-main' },
        h('div', { class: 'trace-name-row' }, h('strong', {}, meta.name), sum),
        tools
      ),
      h('div', { class: 'trace-right' }, dur, badge)
    );

    rowsBox.append(row);
    const entry = { root: row, tools, badge, dur, sum, toolMap: new Map() };
    rows.set(agentId, entry);
    return entry;
  }

  function setStatus(entry, status) {
    entry.badge.className = STATUS_CLASS[status] || 'tag tag-gray';
    entry.badge.textContent = STATUS_TEXT[status] || status;
    entry.root.dataset.status = status;
  }

  const api = {
    /**
     * 处理一条后端事件。未知类型一律忽略（契约要求：前端必须能容忍新增事件）。
     * @param {object} e
     */
    handle(e) {
      switch (e.type) {
        case 'run.start':
          startedAt = performance.now();
          footer.textContent = '正在调度…';
          break;

        case 'context.received': {
          // 页面伴学：助手读到了什么。放在计划之前，让用户先建立信任。
          planBox.innerHTML = '';
          const ok = (e.data && e.data.chars) > 0;
          planBox.append(
            h(
              'div',
              {
                class: 'trace-context',
                style: {
                  fontSize: '11.5px',
                  color: ok ? 'var(--text-2)' : 'var(--warning)',
                  marginBottom: '8px',
                },
              },
              '📄 ',
              e.summary || (ok ? '已读取页面上下文' : '未读取到页面内容')
            )
          );
          if (ok && e.data?.outline) {
            planBox.append(
              h(
                'details',
                { class: 'small muted', style: { marginBottom: '8px' } },
                h('summary', { style: { cursor: 'pointer' } }, '展开页面结构 ▾'),
                h(
                  'pre',
                  {
                    class: 'mono',
                    style: {
                      whiteSpace: 'pre-wrap',
                      background: '#f8fafc',
                      padding: '7px 9px',
                      borderRadius: '7px',
                      marginTop: '5px',
                      fontSize: '11px',
                      maxHeight: '140px',
                      overflow: 'auto',
                    },
                  },
                  e.data.outline
                )
              )
            );
          }
          break;
        }

        case 'plan': {
          planBox.innerHTML = '';
          if (e.reason) {
            planBox.append(h('div', { class: 'trace-reason small muted' }, e.reason));
          }
          const chips = h('div', { class: 'row wrap' });
          for (const s of e.steps || []) {
            const meta = metaOf(s.agent);
            chips.append(
              h(
                'span',
                { class: 'plan-chip', style: { borderColor: meta.accent, color: meta.accent } },
                `${meta.icon || '🤖'} ${s.label || meta.name}`
              )
            );
          }
          chips.append(
            h('span', { class: 'tag tag-gray' }, `意图：${e.intent || '—'}`)
          );
          planBox.append(chips);
          break;
        }

        case 'agent.start': {
          const entry = ensureRow(e.agent);
          setStatus(entry, 'running');
          entry.root.classList.add('is-running');
          break;
        }

        case 'agent.delta': {
          // 不做 DOM 更新（增量文本由回答区负责），只在摘要里显示进度
          const entry = rows.get(e.agent);
          if (entry) {
            const cur = (entry.sum.dataset.len || 0) + (e.text || '').length;
            entry.sum.dataset.len = String(cur);
            entry.sum.textContent = `已生成 ${cur} 字`;
          }
          break;
        }

        case 'tool.call':
        case 'tool.result': {
          const entry = ensureRow(e.agent || rows.keys().next().value || 'system');
          entry.root.classList.remove('is-running');
          let chip = entry.toolMap.get(e.tool);
          if (!chip) {
            chip = h(
              'span',
              { class: 'tool-chip', dataset: { tool: e.tool } },
              h('code', {}, e.tool),
              h('i', { class: 'tool-dot' })
            );
            entry.toolMap.set(e.tool, chip);
            entry.tools.append(chip);
          }
          if (e.type === 'tool.result') {
            chip.classList.add(e.ok ? 'ok' : 'err');
            const info = e.duration_ms ? ` ${e.duration_ms}ms` : '';
            chip.title = `${e.tool}${info}${e.ok ? '' : '（失败）'}`;
          } else {
            chip.classList.add('calling');
            chip.title = `${e.tool}\n入参：${JSON.stringify(e.args || {})}`;
          }
          break;
        }

        case 'agent.end': {
          const entry = ensureRow(e.agent);
          entry.root.classList.remove('is-running');
          setStatus(entry, e.ok === false ? 'failed' : 'done');
          entry.dur.textContent = e.duration_ms != null ? `${e.duration_ms}ms` : '—';
          if (e.summary) {
            entry.sum.textContent = e.summary.replace(/\s+/g, ' ').slice(0, 46);
          }
          break;
        }

        case 'artifact': {
          const entry = ensureRow(e.agent || 'system');
          entry.tools.append(h('span', { class: 'tool-chip artifact-chip' }, `📦 ${e.kind}`));
          break;
        }

        case 'hitl.request': {
          const entry = ensureRow(e.agent || 'verifier');
          setStatus(entry, 'running');
          footer.textContent = '⏸ 已暂停，等待人工确认（HITL）';
          break;
        }

        case 'hitl.resolved': {
          footer.textContent = `人工已处理：${e.action}`;
          break;
        }

        case 'run.end': {
          rows.forEach((entry) => {
            if (entry.root.dataset.status === 'running') setStatus(entry, 'done');
            entry.root.classList.remove('is-running');
          });
          const ms = startedAt ? Math.round(performance.now() - startedAt) : (e.duration_ms ?? 0);
          footer.textContent = `✔ 本轮结束，共 ${rows.size} 个 Agent 参与，耗时 ${ms}ms`;
          break;
        }

        case 'error': {
          footer.innerHTML = `<span style="color:var(--danger)">✖ ${e.message || '未知错误'}</span>`;
          break;
        }

        default:
          break;
      }
    },

    reset() {
      rows.clear();
      planBox.innerHTML = '';
      rowsBox.innerHTML = '';
      footer.textContent = '等待调度…';
      startedAt = 0;
    },
  };

  return api;
}
