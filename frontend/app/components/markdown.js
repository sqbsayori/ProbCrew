/**
 * Markdown 渲染器（主站侧）—— **转出共享内核**。
 *
 * 实现已移到 `frontend/shared/markdown.js`，因为悬浮窗也要用同一份
 * （以前两边各一份，写法都漂移了，见 `docs/23` §1）。
 *
 * ⚠️ 对外的导出名**保持不变** —— 调用方（run-panel / artifacts 等）一行都不用改。
 */
export {
  normalizeMath,
  inline,
  markdownToHtml,
  MATH_INLINE_CLASS,
  MATH_BLOCK_CLASS,
} from '../../shared/markdown.js';
