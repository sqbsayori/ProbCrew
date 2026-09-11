/**
 * 知识点讲解页。
 *
 * 这一页刻意写得薄 —— 交互骨架全在共享组件 `run-panel.js` 里。
 * 但它不再是"一个空输入框"：左侧有**课程目录**（来自 /api/knowledge/chapters），
 * 点任意一节就直接提问。用户一进页面就知道系统里有什么内容、能问什么。
 *
 * 负责 Knowledge Agent（后端 app/agents/knowledge.py）的同学只需要关心后端逻辑。
 */
import { h, injectStyles, clear, toast } from '../../core/dom.js';
import { createRunPanel } from '../../components/run-panel.js';
import * as api from '../../core/api.js';

injectStyles('/app/features/knowledge/styles.css');

const EXAMPLES = [
  '什么是全概率公式？',
  '中心极限定理讲的是什么？',
  '边缘分布怎么求？',
  '独立和互斥有什么区别？',
];

/** 保存本页创建的运行面板，路由切走时必须销毁（里面有动画 iframe） */
let panel = null;

/* ------------------------------------------------------------------ *
 * 课程目录
 * ------------------------------------------------------------------ */

function renderChapters(host, onPick) {
  clear(host);
  host.append(h('div', { class: 'empty small' }, '正在读取课程目录…'));

  api
    .knowledgeChapters()
    .then((data) => {
      clear(host);

      host.append(
        h(
          'div',
          { class: 'kb-meta small muted' },
          `${data.chapter_count} 章 · ${data.section_count} 个知识点`
        )
      );

      for (const ch of data.chapters) {
        const list = h('div', { class: 'kb-sections' });
        const toggle = h(
          'button',
          {
            class: 'kb-chapter',
            onclick: () => {
              const hidden = list.style.display === 'none';
              list.style.display = hidden ? '' : 'none';
              toggle.classList.toggle('open', hidden);
            },
          },
          h('span', { class: 'kb-ch-id' }, ch.id),
          h('span', { class: 'kb-ch-title' }, ch.title),
          h('span', { class: 'kb-ch-count' }, `${ch.section_count} 节`)
        );

        for (const sec of ch.sections) {
          list.append(
            h(
              'button',
              {
                class: 'kb-section',
                title: sec.summary || '',
                onclick: () => onPick(sec.question),
              },
              h('span', { class: 'kb-sec-title' }, sec.title),
              sec.formula
                ? h('code', { class: 'kb-sec-formula mono' }, sec.formula)
                : null
            )
          );
        }

        // 默认展开第一章，其余折叠 —— 页面一进来就有内容感
        const isFirst = ch === data.chapters[0];
        list.style.display = isFirst ? '' : 'none';
        if (isFirst) toggle.classList.add('open');

        host.append(h('div', { class: 'kb-chapter-box' }, toggle, list));
      }
    })
    .catch((err) => {
      clear(host);
      host.append(
        h('div', { class: 'empty small' }, `课程目录读取失败：${err.message}`)
      );
    });
}

/* ------------------------------------------------------------------ *
 * 页面
 * ------------------------------------------------------------------ */

export function mount(container) {
  const chapterHost = h('div', { class: 'kb-tree' });

  const askTip = h(
    'p',
    { class: 'small muted' },
    'Knowledge Agent 会先在你的教材知识库中检索相关章节，再组织讲解；' +
      '如果检索到的知识点有对应的交互动画，会自动挂在回答下方，点开即可播放。'
  );

  container.append(
    h(
      'div',
      { class: 'kb-layout' },
      /* 左：课程目录 */
      h(
        'aside',
        { class: 'card kb-side' },
        h(
          'div',
          { class: 'card-title' },
          '📖 课程目录',
          h('span', { class: 'sub' }, '点击任意一节直接提问')
        ),
        chapterHost
      ),
      /* 右：运行面板 */
      h(
        'div',
        {},
        h('div', { class: 'card knowledge-tip' }, h('div', { class: 'card-title' }, '📚 知识点讲解'), askTip),
        (() => {
          const host = h('div', { class: 'mt-16' });
          panel = createRunPanel(host, {
            placeholder: '例如：贝叶斯公式和全概率公式是什么关系？',
            examples: EXAMPLES,
            hint: 'Ctrl + Enter 发送 · 讲解会附带公式卡与交互动画',
            showTrace: true,
          });
          return host;
        })()
      )
    )
  );

  renderChapters(chapterHost, (question) => {
    panel?.ask(question);
    toast('已按目录发起提问', 'info', 1600);
  });
}

export function unmount() {
  // 必须显式销毁：回答区里可能挂着动画 iframe，
  // 而部分动画（markov-chain）有停不掉的渲染循环，只清 DOM 不够。
  panel?.destroy();
  panel = null;
}
