/**
 * 文本转义 —— 跨形态共享（主站与悬浮窗共用这一份）。
 *
 * 为什么单独一个文件：它是**安全边界**。渲染器把模型输出当 HTML 插入 DOM，
 * 转义漏一个字符就是 XSS。这份实现必须只有一处，两边都不许再写第二份。
 *
 * 约束（见 `docs/23` §三 R2）：本文件**不许**触碰 `document`/`window`/`fetch` —— 纯函数。
 */

/** HTML 文本转义：`& < > " '` 五个字符全部处理（引号也要，因为会进属性值）。 */
export function escapeHtml(text) {
  return String(text ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );
}

/** 属性值转义：与 escapeHtml 同实现，单独一个名字是为了让调用点意图清楚。 */
export const escapeAttr = escapeHtml;
