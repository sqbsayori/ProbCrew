/**
 * 运行轨迹页 —— 把"多 Agent 到底怎么协作的"完整露出来。
 *
 * 后端其实一直在留档：每次提问产生的所有事件都按序记在 `run.events` 里
 * （`kernel/runs.py`），但前端只有一个实时轨迹面板，**问完就没了**。
 * 这一页接的是 `/api/runs` 与 `/api/runs/{id}/timeline`，用途有三：
 *
 *   1. 演示：答辩时回放"刚才那一轮到底发生了什么"，而不是只看最终答案；
 *   2. 调试：哪一步慢、哪个工具失败、路由为什么这样决策，一目了然；
 *   3. 评估：这份轨迹就是后续做 RAGAS / 自建 Eval 的数据集雏形。
 *
 * 诚实提示：运行记录当前存在**内存**里，服务重启即清空。页面上明确写着，
 * 不让人误以为这是持久化的历史。
 */
import { h, injectStyles, clear, toast } from '../../core/dom.js';
import * as api from '../../core/api.js';

injectStyles('/app/features/runs/styles.css');

let selectedId = null;

const STATUS_META = {
  done: { label: '已完成', cls: 'tag-green' },
  awaiting_hitl: { label: '等待人工确认', cls: 'tag-amber' },
  running: { label: '进行中', cls: 'tag' },
  error: { label: '出错', cls: 'tag-red' },
};

function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/* ------------------------------------------------------------------ *
 * 列表
 * ------------------------------------------------------------------ */

function renderList(host, data, onPick) {
  clear(host);

  const stats = h(
    'div',
    { class: 'run-stats' },
    h('div', { class: 'run-stat' }, h('strong', {}, String(data.count)), h('span', {}, '本次启动后的运行')),
    h('div', { class: 'run-stat' }, h('strong', {}, String(data.total_events)), h('span', {}, '事件总数')),
    h(
      'div',
      { class: 'run-stat' },
      h('strong', {}, String(data.items.filter((i) => i.hitl).length)),
      h('span', {}, '触发过 HITL')
    )
  );
  host.append(stats, h('div', { class: 'run-note small muted' }, 'ⓘ ' + data.note));

  if (!data.items.length) {
    host.append(
      h(
        'div',
        { class: 'card' },
        h('div', { class: 'empty' }, '还没有运行记录。'),
        h(
          'p',
          { class: 'small muted', style: { textAlign: 'center' } },
          '去「知识讲解」或「题目讲解」问一个问题，回来这里就能看到完整的协作轨迹。'
        )
      )
    );
    return;
  }

  const wrap = h('div', { class: 'run-list' });
  for (const r of data.items) {
    const st = STATUS_META[r.status] || STATUS_META.done;
    wrap.append(
      h(
        'div',
        {
          class: `run-card${r.run_id === selectedId ? ' active' : ''}`,
          onclick: () => onPick(r.run_id),
        },
        h(
          'div',
          { class: 'run-card-head' },
          h('span', { class: `tag ${st.cls}` }, st.label),
          r.hitl ? h('span', { class: 'tag tag-amber' }, 'HITL') : null,
          h('span', { class: 'run-time mono' }, fmtTime(r.created_at))
        ),
        h('div', { class: 'run-query' }, r.query),
        h(
          'div',
          { class: 'run-meta small muted' },
          `意图 ${r.intent || '—'} · ${r.agents.length} 个 Agent · ` +
            `${r.tools.length} 次工具调用 · ${r.event_count} 个事件 · ` +
            `${r.answer_len} 字答案` +
            (r.agent_ms ? ` · Agent 累计 ${r.agent_ms}ms` : '')
        ),
        r.agents.length
          ? h(
              'div',
              { class: 'run-agents' },
              ...r.agents.map((a) => h('span', { class: 'tag tag-gray' }, a))
            )
          : null,
        r.errors.length ? h('div', { class: 'run-err small' }, '⚠️ ' + r.errors.join('；')) : null
      )
    );
  }
  host.append(wrap);
}

/* ------------------------------------------------------------------ *
 * 详情（时间轴）
 * ------------------------------------------------------------------ */

function renderDetail(host, timeline, onBack) {
  clear(host);
  const s = timeline.summary;

  host.append(
    h(
      'div',
      { class: 'card' },
      h(
        'div',
        { class: 'row-between wrap' },
        h('div', { class: 'card-title', style: { margin: '0' } }, '🧵 轨迹详情'),
        h(
          'button',
          { class: 'btn btn-sm', onclick: onBack },
          '← 返回列表'
        )
      ),
      h('div', { class: 'run-detail-query' }, s.query),
      h(
        'div',
        { class: 'row wrap mt-8' },
        h('span', { class: 'tag tag-gray' }, `意图 ${s.intent || '—'}`),
        h('span', { class: 'tag tag-gray' }, `${s.event_count} 个事件`),
        h('span', { class: 'tag tag-gray' }, `${timeline.delta_count} 个流式片段`),
        s.agent_ms ? h('span', { class: 'tag tag-gray' }, `Agent 累计 ${s.agent_ms}ms`) : null,
        h('span', { class: 'tag tag-gray mono' }, s.run_id)
      )
    )
  );

  // 阶段时间轴
  const phasesBox = h('div', { class: 'card mt-16' }, h('div', { class: 'card-title' }, '⏱ 阶段时间轴'));
  for (const ph of timeline.phases) {
    const items = h('div', { class: 'tl-items' });
    for (const it of ph.items) {
      const detailText =
        it.detail && it.detail.args
          ? JSON.stringify(it.detail.args)
          : it.detail && it.detail.summary
            ? it.detail.summary
            : it.detail && it.detail.title
              ? it.detail.title
              : '';
      items.append(
        h(
          'div',
          { class: 'tl-item' },
          h('span', { class: 'tl-dot' }),
          h('div', { class: 'tl-body' },
            h('div', { class: 'tl-label' }, it.label),
            detailText ? h('div', { class: 'tl-detail mono' }, detailText.slice(0, 160)) : null
          )
        )
      );
    }
    phasesBox.append(
      h(
        'div',
        { class: 'tl-phase' },
        h('div', { class: 'tl-phase-head' }, `${ph.icon} ${ph.title}`),
        items
      )
    );
  }
  host.append(phasesBox);

  // 最终答案
  if (timeline.answer) {
    const ans = h('div', { class: 'card mt-16' }, h('div', { class: 'card-title' }, '📤 最终答案'));
    const body = h('div', { class: 'run-answer' });
    host.append(ans);
    ans.append(body);
    // 复用全局的 markdown + KaTeX 渲染
    import('../../components/markdown.js').then(async (md) => {
      const { renderMathIn } = await import('../../components/katex.js');
      body.innerHTML = md.markdownToHtml(timeline.answer);
      renderMathIn(body);
    });
  }

  // 原始事件（调试用）
  const raw = h('pre', { class: 'run-raw mono' }, JSON.stringify(timeline.events, null, 1));
  host.append(
    h(
      'details',
      { class: 'card mt-16' },
      h('summary', { class: 'card-title', style: { cursor: 'pointer' } },
        `🔬 原始事件流（${timeline.events.length} 条，展开查看）`),
      raw
    )
  );
}

/* ------------------------------------------------------------------ *
 * 页面
 * ------------------------------------------------------------------ */

export function mount(container) {
  const listHost = h('div', {});
  const detailHost = h('div', {});

  container.append(
    h(
      'div',
      { class: 'card' },
      h(
        'div',
        { class: 'card-title' },
        '🧵 运行轨迹',
        h('span', { class: 'sub' }, '每次提问的完整协作过程都留了档')
      ),
      h(
        'p',
        { class: 'small muted' },
        '这里能看到 Orchestrator 怎么路由、哪些 Agent 并行跑了、调了哪些工具、' +
          'Verifier 校验了什么、HITL 在哪一步挂起。这些数据同时是后续做评估（RAGAS）的数据集雏形。'
      ),
      h(
        'div',
        { class: 'row mt-12' },
        h('button', { class: 'btn btn-primary', onclick: () => load() }, '⟲ 刷新'),
        h(
          'button',
          {
            class: 'btn',
            onclick: async () => {
              try {
                await navigator.clipboard.writeText(location.origin + '/api/runs');
                toast('已复制接口地址', 'success', 1600);
              } catch {
                toast('复制失败，可手动访问 /api/runs', 'warning');
              }
            },
          },
          '🔗 复制接口地址'
        )
      )
    ),
    listHost,
    detailHost
  );

  async function load() {
    clear(detailHost);
    selectedId = null;
    clear(listHost);
    listHost.append(h('div', { class: 'empty mt-16' }, '加载中…'));
    try {
      const data = await api.listRuns(50);
      renderList(listHost, data, async (runId) => {
        selectedId = runId;
        clear(detailHost);
        detailHost.append(h('div', { class: 'empty mt-16' }, '正在读取轨迹…'));
        try {
          const tl = await api.runTimeline(runId);
          listHost.innerHTML = '';
          renderDetail(detailHost, tl, () => load());
        } catch (err) {
          clear(detailHost);
          detailHost.append(h('div', { class: 'empty mt-16' }, `轨迹读取失败：${err.message}`));
        }
      });
    } catch (err) {
      clear(listHost);
      listHost.append(h('div', { class: 'empty mt-16' }, `加载失败：${err.message}`));
    }
  }

  load();
}

export function unmount() {
  selectedId = null;
}
