/**
 * 学习数据页。
 *
 * demo 阶段边界（对齐架构重构建议 §2.1）：
 *   只做「读取记录 + 单点正确率排序」的简易诊断，
 *   **不做知识点依赖图（DAG）的级联定位** —— 那依赖内容入库完成，属迭代二。
 * 这一页会把这个边界明确写在界面上，避免评审误以为已经实现。
 *
 * 数据来源：`/api/stats/{session_id}` → SQLite（tools/learning_log.py）
 */
import { h, injectStyles, clear } from '../../core/dom.js';
import { store } from '../../core/store.js';
import * as api from '../../core/api.js';

injectStyles('/app/features/analytics/styles.css');

let onFinished = null;

function statCard(value, label, extra) {
  return h(
    'div',
    { class: 'an-stat' },
    h('strong', {}, String(value)),
    h('span', {}, label),
    extra ? h('em', {}, extra) : null
  );
}

function table(title, columns, rows) {
  if (!rows.length) {
    return h('div', { class: 'card' }, h('div', { class: 'card-title' }, title),
      h('div', { class: 'empty' }, '暂无数据'));
  }
  return h(
    'div',
    { class: 'card' },
    h('div', { class: 'card-title' }, title, h('span', { class: 'sub' }, `${rows.length} 条`)),
    h(
      'div',
      { class: 'table-wrap' },
      h(
        'table',
        { class: 'data' },
        h('thead', {}, h('tr', {}, ...columns.map((c) => h('th', {}, c)))),
        h('tbody', {}, ...rows.map((r) => h('tr', {}, ...r.map((c) => h('td', {}, String(c ?? ''))))))
      )
    )
  );
}

/**
 * 掌握度条形图。
 * 纯 DOM 实现（不需要 canvas）—— 横向条 + 百分比标签，一眼看出最薄弱的知识点。
 */
function masteryChart(weak) {
  if (!weak.length) {
    return h(
      'div',
      { class: 'card' },
      h('div', { class: 'card-title' }, '📊 知识点掌握度'),
      h('div', { class: 'empty' }, '还没有练习数据 —— 做几道题后再回来，这里会显示各知识点的正确率排序。')
    );
  }
  const rows = h('div', { class: 'ma-rows' });
  for (const w of weak) {
    const pct = Math.round((w.accuracy || 0) * 100);
    // 颜色分档：<60% 红、<80% 橙、其余绿 —— 让"最该补的"一眼跳出来
    const color = pct < 60 ? '#ef4444' : pct < 80 ? '#f59e0b' : '#10b981';
    rows.append(
      h(
        'div',
        { class: 'ma-row' },
        h('span', { class: 'ma-topic' }, w.topic),
        h(
          'div',
          { class: 'ma-bar-box' },
          h('div', { class: 'ma-bar', style: { width: `${Math.max(pct, 2)}%`, background: color } })
        ),
        h('span', { class: 'ma-val mono', style: { color } }, `${pct}%`),
        h('span', { class: 'ma-detail small muted' }, `${w.correct}/${w.attempts}`)
      )
    );
  }
  return h(
    'div',
    { class: 'card' },
    h(
      'div',
      { class: 'card-title' },
      '📊 知识点掌握度',
      h('span', { class: 'sub' }, '正确率升序 —— 最上面就是最该补的')
    ),
    rows,
    h(
      'p',
      { class: 'small muted mt-12' },
      'demo 阶段只做「单点正确率排序」，不做知识点依赖图的级联定位（那依赖内容入库完成，属迭代二）。'
    )
  );
}

export function mount(container) {
  const sessionId = store.get('sessionId');
  const host = h('div', {});

  container.append(
    h(
      'div',
      { class: 'card' },
      h(
        'div',
        { class: 'card-title' },
        '📈 学习数据',
        h('span', { class: 'sub' }, `会话 ${sessionId}`)
      ),
      h(
        'p',
        { class: 'small muted' },
        '每次问答都会写入本地 SQLite（backend/data/learning.sqlite）。' +
          '这一页把它读出来，用于展示"学习闭环"的数据基础。'
      ),
      h(
        'div',
        { class: 'row mt-12' },
        h('button', { class: 'btn btn-primary', onclick: () => load() }, '⟲ 刷新数据'),
        h('button', {
          class: 'btn',
          onclick: () => {
            localStorage.removeItem('probstat.session_id');
            location.reload();
          },
        }, '🧹 清空会话（重新开始统计）')
      )
    ),
    host
  );

  async function load() {
    clear(host);
    host.append(h('div', { class: 'empty' }, '加载中…'));
    try {
      const s = await api.learningStats(sessionId, 20);
      clear(host);

      const weak = s.weak_topics || [];
      host.append(
        h(
          'div',
          { class: 'an-stats mt-16' },
          statCard(s.total_qa ?? 0, '累计问答', '来自 qa_log 表'),
          statCard((s.recent || []).length, '最近记录', '最多 20 条'),
          statCard(weak.length, '已记录知识点', '来自 mastery 表'),
          statCard(
            weak.length ? `${Math.round((weak[0].accuracy ?? 0) * 100)}%` : '—',
            '最薄弱项正确率',
            weak.length ? weak[0].topic : '暂无练习数据'
          )
        ),

        // 空态引导：没有记录时不能只显示一张空表
        !s.total_qa
          ? h(
              'div',
              { class: 'card mt-16' },
              h('div', { class: 'card-title' }, '🚀 还没有学习记录'),
              h(
                'p',
                { class: 'small muted' },
                '这一页的数据来自你在这个系统里的真实问答。去问一个问题，回来就能看到记录。'
              ),
              h(
                'div',
                { class: 'row wrap mt-12' },
                h('a', { class: 'btn btn-primary', href: '#/knowledge' }, '📚 去问一个知识点'),
                h('a', { class: 'btn', href: '#/solver' }, '✏️ 去做一道题')
              )
            )
          : null,

        h('div', { class: 'mt-16' }, masteryChart(weak)),

        h('div', { class: 'mt-16' }, 
          table('最近问答', ['提问', '意图'], (s.recent || []).map((r) => [String(r.query).slice(0, 46), r.intent || '—']))
        ),

        h(
          'div',
          { class: 'card mt-16' },
          h('div', { class: 'card-title' }, '🔬 demo 阶段的能力边界'),
          h(
            'ul',
            { class: 'small muted', style: { paddingLeft: '18px', lineHeight: '1.9' } },
            h('li', {}, '✅ 已实现：问答记录、按知识点聚合正确率、单点薄弱排序'),
            h('li', {}, '⏳ 未实现：知识点依赖图（DAG）与「级联定位薄弱根源」'),
            h('li', {}, '原因：依赖图需要内容入库时标注知识点依赖关系，属迭代二；demo 阶段先用扁平映射'),
            h('li', {}, 'learning_stats 工具返回的 note 字段里也写明了这一点，前端不做夸大展示')
          )
        )
      );
    } catch (err) {
      clear(host);
      host.append(
        h('div', { class: 'empty', style: { color: 'var(--danger)' } }, `加载失败：${err.message}`)
      );
    }
  }

  load();

  // 在其他页发起问答后自动刷新 —— 让"学→练→记录"闭环看得见
  onFinished = () => load();
  document.addEventListener('run:finished', onFinished);
}

export function unmount() {
  if (onFinished) document.removeEventListener('run:finished', onFinished);
  onFinished = null;
}
