/**
 * 题目讲解页 —— 本项目「生成 / 验证分权 + 人机协同」的演练场。
 *
 * 流程：Problem Solver 生成步骤（不直接采纳）→ Verifier 独立校验
 *      → 因为解题属于"关键结论"，必定挂起 → 用户在黄色卡片里
 *      「确认 / 修正 / 补充」→ 从断点续跑（不重跑已完成节点）。
 *
 * 左侧原本什么都没有，现在接了**例题库**（/api/problems/examples）：
 * 按章节与难度筛选，点一下就能开始讲解或先填进输入框自己改。
 * 演示时不用现场编题。
 */
import { h, injectStyles, clear, toast } from '../../core/dom.js';
import { createRunPanel } from '../../components/run-panel.js';
import * as api from '../../core/api.js';
import { store } from '../../core/store.js';

injectStyles('/app/features/solver/styles.css');

const LEVEL_CLASS = { 基础: 'tag-green', 进阶: 'tag-amber', 挑战: 'tag-red' };

let panel = null;

export function mount(container) {
  const health = store.get('health');
  const hitlOn = health?.collaboration?.hitl_enabled !== false;

  /* ---------------- 右：运行面板 ---------------- */
  const panelHost = h('div', {});
  panel = createRunPanel(panelHost, {
    placeholder: '把题目贴进来，或从左侧例题库挑一道…',
    examples: [
      '已知 P(B₁)=0.5, P(B₂)=0.3, P(A|B₁)=0.2, P(A|B₂)=0.6，求 P(A)',
      '抛一枚不均匀硬币 10 次，正面概率 0.3，求恰有 4 次正面的概率',
    ],
    hint: 'Ctrl + Enter 发送 · 解题结论会走 HITL 人工确认',
    showTrace: true,
  });

  /* ---------------- 左：例题库 ---------------- */
  const listHost = h('div', { class: 'ex-list' });
  const filterHost = h('div', { class: 'ex-filters' });
  const state = { chapter: '', level: '' };

  async function loadExamples() {
    clear(listHost);
    listHost.append(h('div', { class: 'empty small' }, '正在读取例题库…'));
    try {
      const data = await api.problemExamples({ chapter: state.chapter, level: state.level });
      clear(filterHost);
      clear(listHost);

      // 筛选器
      const chip = (label, value, key) =>
        h(
          'button',
          {
            class: `dist-chip${state[key] === value ? ' active' : ''}`,
            onclick: () => {
              state[key] = state[key] === value ? '' : value;
              loadExamples();
            },
          },
          label
        );

      filterHost.append(
        h('div', { class: 'row wrap' },
          chip('全部章节', '', 'chapter'),
          ...data.filters.chapters.map((c) => chip(c, c, 'chapter'))
        ),
        h('div', { class: 'row wrap mt-8' },
          chip('全部难度', '', 'level'),
          ...data.filters.levels.map((l) => chip(l, l, 'level'))
        )
      );

      if (!data.items.length) {
        listHost.append(h('div', { class: 'empty small' }, '没有符合条件的例题'));
        return;
      }

      for (const ex of data.items) {
        listHost.append(
          h(
            'div',
            { class: 'ex-card' },
            h(
              'div',
              { class: 'ex-head' },
              h('span', { class: `tag ${LEVEL_CLASS[ex.level] || 'tag-gray'}` }, ex.level),
              h('span', { class: 'tag tag-gray' }, ex.chapter)
            ),
            h('h4', { class: 'ex-title' }, ex.title),
            h('p', { class: 'ex-problem' }, ex.problem),
            h(
              'div',
              { class: 'ex-tags' },
              ...(ex.tags || []).map((t) => h('span', { class: 'tag' }, t))
            ),
            ex.hint ? h('div', { class: 'ex-hint' }, '💡 ' + ex.hint) : null,
            h(
              'div',
              { class: 'ex-actions' },
              h(
                'button',
                {
                  class: 'btn btn-sm btn-primary',
                  onclick: () => {
                    panel?.ask(ex.problem);
                    toast('已提交给 Problem Solver', 'info', 1600);
                  },
                },
                '▶ 讲解这道题'
              ),
              h(
                'button',
                {
                  class: 'btn btn-sm',
                  onclick: () => {
                    panel?.fill(ex.problem);
                    toast('已填入输入框，可以自己改', 'info', 1600);
                  },
                },
                '✎ 填入'
              )
            )
          )
        );
      }
    } catch (err) {
      clear(listHost);
      listHost.append(h('div', { class: 'empty small' }, `例题库读取失败：${err.message}`));
    }
  }

  /* ---------------- 装配 ---------------- */
  container.append(
    h(
      'div',
      { class: 'slv-layout' },
      h(
        'aside',
        { class: 'card ex-side' },
        h(
          'div',
          { class: 'card-title' },
          '📝 例题库',
          h('span', { class: 'sub' }, '点一下就能讲解')
        ),
        filterHost,
        h('div', { class: 'mt-12' }, listHost)
      ),
      h(
        'div',
        {},
        h(
          'div',
          { class: 'card' },
          h('div', { class: 'card-title' }, '✏️ 题目讲解（含人机协同演练）'),
          h(
            'p',
            { class: 'small muted' },
            '输入题目后，Problem Solver 会给出逐步解答。注意：解答不会立刻成为最终答案 —— ' +
              'Verifier 会先独立校验（步骤完整性、教材依据、公式完整性），再交由你确认。'
          ),
          h(
            'div',
            { class: 'solver-note' },
            h('div', {}, h('b', {}, '① 生成'), 'Problem Solver 分步解答，含思路分析与易错点'),
            h('div', {}, h('b', {}, '② 验证'), 'Verifier 独立复核，不复用生成者的自述'),
            h(
              'div',
              {},
              h('b', {}, '③ 人审'),
              hitlOn
                ? '关键结论触发 interrupt() 暂停，等你确认'
                : '当前已在配置中关闭 HITL（HITL_ENABLED=false）'
            )
          )
        ),
        panelHost
      )
    )
  );

  loadExamples();
}

export function unmount() {
  panel?.destroy();
  panel = null;
}
