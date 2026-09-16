/**
 * 学生数据管理页（管理员）
 * ======================
 *
 * 三个 tab：
 *   · **学生** —— 班级统计 + 学生列表 + 详情（逐题明细）+ 重置密码 / 禁用 / 删除数据
 *   · **账号** —— 只读的管理员列表（新增管理员走 CLI，**页面刻意不提供入口**）
 *   · **审计** —— 谁在什么时候看了谁的数据（合规要求：管理员看学生数据必须留痕）
 *
 * 三条与本页强相关的约定：
 * 1. **前端不是权限**。本页只是"看得见"；服务端 `require_admin` 才是判定点。
 *    学生就算手敲 `#/admin` 也会被路由守卫弹回，就算绕过守卫也只会拿到 403。
 * 2. **删除是不可逆的**，所以要求输入用户名二次确认（防手滑点错人）。
 * 3. 本页所有敏感动作（看明细 / 导出 / 删除 / 重置 / 禁用）后端都会写审计，
 *    写不进去就整体中止 —— 所以这里看到"操作失败"时，别急着重试，先看审计。
 */
import { h, clear, toast } from '../../core/dom.js';
import * as api from '../../core/api.js';
import { store } from '../../core/store.js';

const TABS = [
  { key: 'students', label: '学生' },
  { key: 'accounts', label: '账号' },
  { key: 'audit', label: '审计' },
];

/** 组件状态（每次 mount 重置） */
let state = null;

export function mount(container) {
  state = {
    tab: 'students',
    overview: null,
    students: null,
    accounts: null,
    audit: null,
    page: 1,
    pageSize: 20,
    q: '',
    sort: 'created_at',
    order: 'asc',
    detail: null, // 当前展开的学生详情
    error: '',
    loading: true,
  };
  render(container);
  loadOverview(container);
  loadStudents(container);
}

export function unmount() {
  state = null;
}

/* ------------------------------------------------------------------ *
 * 骨架
 * ------------------------------------------------------------------ */

function render(root) {
  clear(root);

  const me = store.get('user');
  root.append(
    h(
      'div',
      { class: 'page-head' },
      h(
        'div',
        { class: 'page-head-main' },
        h('h1', { class: 'page-head-title' }, '学生数据管理'),
        h(
          'p',
          { class: 'page-head-sub' },
          `当前账号：${me?.display_name || me?.username || '—'}（管理员） · 数据只存本地库`
        )
      ),
      h(
        'div',
        { class: 'page-head-actions' },
        h('button', { class: 'btn btn-sm', onclick: () => reload(root) }, '⟲ 刷新'),
        h('button', { class: 'btn btn-sm', onclick: () => exportCsv() }, '⬇ 导出 CSV'),
        h('button', { class: 'btn btn-sm btn-primary', onclick: () => openImport(root) }, '＋ 批量导入')
      )
    )
  );

  // tab 条
  const tabs = h('div', { class: 'toolbar' });
  for (const t of TABS) {
    tabs.append(
      h(
        'button',
        {
          class: `dist-chip${state.tab === t.key ? ' active' : ''}`,
          onclick: () => {
            state.tab = t.key;
            render(root);
            if (t.key === 'accounts' && !state.accounts) loadAccounts(root);
            if (t.key === 'audit' && !state.audit) loadAudit(root);
          },
        },
        t.label
      )
    );
  }
  root.append(tabs);

  if (state.error) {
    root.append(h('div', { class: 'hint-box danger' }, `⚠️ ${state.error}`));
  }

  const host = h('div', { id: 'admin-tab-host' });
  root.append(host);
  if (state.tab === 'students') renderStudents(host, root);
  if (state.tab === 'accounts') renderAccounts(host);
  if (state.tab === 'audit') renderAudit(host);
}

function reload(root) {
  state.overview = null;
  state.students = null;
  state.accounts = null;
  state.audit = null;
  state.error = '';
  render(root);
  loadOverview(root);
  if (state.tab === 'students') loadStudents(root);
  if (state.tab === 'accounts') loadAccounts(root);
  if (state.tab === 'audit') loadAudit(root);
}

/* ------------------------------------------------------------------ *
 * 数据加载（失败一律落到 state.error，绝不白屏）
 * ------------------------------------------------------------------ */

async function loadOverview(root) {
  try {
    state.overview = await api.adminOverview();
    renderCurrent(root);
  } catch (err) {
    state.error = `统计加载失败：${err.message}`;
    renderCurrent(root);
  }
}

async function loadStudents(root) {
  try {
    state.students = await api.adminStudents({
      page: state.page, page_size: state.pageSize, q: state.q,
      sort: state.sort, order: state.order,
    });
  } catch (err) {
    state.error = `学生列表加载失败：${err.message}`;
  }
  renderCurrent(root);
}

async function loadAccounts(root) {
  try {
    // 账号 tab 只读：管理员账号由 CLI 维护，页面不提供增删改
    state.accounts = await api.adminStudents({ page: 1, page_size: 100, sort: 'created_at' });
  } catch (err) {
    state.error = `账号列表加载失败：${err.message}`;
  }
  renderCurrent(root);
}

async function loadAudit(root) {
  try {
    state.audit = await api.adminAudit({ page: 1, page_size: 100 });
  } catch (err) {
    state.error = `审计加载失败：${err.message}`;
  }
  renderCurrent(root);
}

/** 只重画当前 tab（避免每次数据回来都把 tab 条重建、把输入框焦点弄丢） */
function renderCurrent(root) {
  const host = root.querySelector?.('#admin-tab-host');
  if (!host) return;
  if (state.tab === 'students') renderStudents(host, root);
  if (state.tab === 'accounts') renderAccounts(host);
  if (state.tab === 'audit') renderAudit(host);
}

/* ------------------------------------------------------------------ *
 * tab：学生
 * ------------------------------------------------------------------ */

function renderStudents(host, root) {
  clear(host);

  // 统计卡
  const o = state.overview;
  const cards = h('div', { class: 'stat-grid' });
  const items = o
    ? [
        ['学生数', o.student_count, '人'],
        ['总作答', o.total_attempts, '次'],
        ['平均正确率', (o.avg_accuracy * 100).toFixed(1), '%'],
        ['用过提示的比例', (o.hinted_rate * 100).toFixed(1), '%'],
      ]
    : [['学生数', '—'], ['总作答', '—'], ['平均正确率', '—'], ['用过提示的比例', '—']];
  for (const [label, value, unit] of items) {
    cards.append(
      h(
        'div',
        { class: 'stat-card' },
        h('div', { class: 'stat-label' }, label),
        h('div', { class: 'stat-value' }, String(value), unit ? h('span', { class: 'stat-unit' }, unit) : null)
      )
    );
  }
  host.append(cards);

  // 工具栏：搜索
  const search = h('input', {
    class: 'input',
    placeholder: '搜索用户名或姓名…',
    value: state.q,
    onkeydown: (e) => {
      if (e.key === 'Enter') {
        state.q = e.target.value.trim();
        state.page = 1;
        loadStudents(root);
      }
    },
  });
  host.append(
    h(
      'div',
      { class: 'toolbar', style: { marginTop: '16px' } },
      h('span', { class: 'toolbar-label' }, '搜索'),
      search,
      h('button', {
        class: 'btn btn-sm',
        onclick: () => { state.q = search.value.trim(); state.page = 1; loadStudents(root); },
      }, '应用'),
      h('div', { class: 'toolbar-spacer' }),
      h('span', { class: 'muted small' }, state.students ? `共 ${state.students.total} 人` : '加载中…')
    )
  );

  // 详情面板（点某一行后展开在列表上方）
  if (state.detail) host.append(detailPanel(state.detail, root));

  // 列表
  const s = state.students;
  if (!s) {
    host.append(h('div', { class: 'skeleton skeleton-block' }));
    return;
  }
  if (!s.items.length) {
    host.append(
      h('div', { class: 'empty-state' },
        h('div', { class: 'empty-state-ico' }, '👥'),
        h('div', { class: 'empty-state-title' }, '还没有学生'),
        h('div', { class: 'empty-state-text' }, '用右上角「批量导入」上传名单，或让学生自己联系管理员建号。'))
    );
    return;
  }

  const table = h('table', { class: 'data table data-table' });
  table.append(
    h('thead', {},
      h('tr', {},
        h('th', {}, '用户名'),
        h('th', {}, '姓名'),
        h('th', {}, '状态'),
        h('th', { class: 'col-num' }, '作答'),
        h('th', { class: 'col-num' }, '正确率'),
        h('th', { class: 'col-num' }, '用提示'),
        h('th', {}, '最近登录'),
        h('th', { class: 'col-actions' }, '操作')))
  );
  const tbody = h('tbody', {});
  for (const st of s.items) {
    tbody.append(
      h('tr', { class: 'row-clickable' },
        h('td', { class: 'mono' }, st.username),
        h('td', {}, st.display_name || '—'),
        h('td', {}, statusTag(st.status)),
        h('td', { class: 'col-num' }, String(st.attempts)),
        h('td', { class: 'col-num' }, `${(st.accuracy * 100).toFixed(1)}%`),
        h('td', { class: 'col-num' }, String(st.hint_used_total)),
        h('td', { class: 'small muted' }, fmtTime(st.last_login_at) || '从未'),
        h('td', { class: 'col-actions' },
          h('button', { class: 'btn btn-sm', onclick: () => showDetail(st.user_id, root) }, '详情'),
          h('button', { class: 'btn btn-sm', onclick: () => resetPassword(st, root) }, '重置密码'),
          h('button', {
            class: 'btn btn-sm',
            onclick: () => setStatus(st, st.status === 'disabled' ? 'active' : 'disabled', root),
          }, st.status === 'disabled' ? '启用' : '禁用'),
          h('button', { class: 'btn btn-sm', onclick: () => deleteData(st, root) }, '删除数据')))
    );
  }
  table.append(tbody);
  host.append(h('div', { class: 'table-wrap' }, table));

  // 分页
  const pages = Math.max(1, Math.ceil(s.total / s.page_size));
  host.append(
    h('div', { class: 'pager' },
      h('span', { class: 'pager-info' }, `第 ${s.page} / ${pages} 页`),
      h('button', {
        class: 'btn btn-sm', disabled: s.page <= 1,
        onclick: () => { state.page -= 1; loadStudents(root); },
      }, '上一页'),
      h('button', {
        class: 'btn btn-sm', disabled: s.page >= pages,
        onclick: () => { state.page += 1; loadStudents(root); },
      }, '下一页'))
  );
}

function detailPanel(detail, root) {
  const box = h('div', { class: 'card' });
  box.append(
    h('div', { class: 'card-title' },
      `明细 · ${detail.user.display_name || detail.user.username}`,
      h('span', { class: 'sub' }, `（打开这一页已被记入审计）`),
      h('div', { class: 'toolbar-spacer' }),
      h('button', { class: 'btn btn-sm btn-ghost', onclick: () => { state.detail = null; renderCurrent(root); } }, '收起'))
  );

  const st = detail.stats || {};
  box.append(
    h('div', { class: 'row wrap', style: { gap: '16px', marginBottom: '10px' } },
      h('span', { class: 'tag' }, `作答 ${st.attempts ?? 0}`),
      h('span', { class: 'tag tag-green' }, `答对 ${st.correct ?? 0}`),
      h('span', { class: 'tag tag-red' }, `错题 ${st.wrong_items ?? 0}`),
      h('span', { class: 'tag tag-amber' }, `用提示 ${st.hint_used_total ?? 0}`),
      h('span', { class: 'tag tag-gray' }, `正确率 ${((st.accuracy ?? 0) * 100).toFixed(1)}%`))
  );

  const rows = detail.recent_attempts || [];
  if (!rows.length) {
    box.append(
      h('div', { class: 'empty-state' },
        h('div', { class: 'empty-state-ico' }, '📄'),
        h('div', { class: 'empty-state-title' }, '这个学生还没有作答记录'))
    );
    return box;
  }
  const table = h('table', { class: 'data data-table' });
  table.append(h('thead', {}, h('tr', {},
    h('th', {}, '题目'), h('th', {}, '结果'), h('th', { class: 'col-num' }, '第几次'),
    h('th', { class: 'col-num' }, '提示'), h('th', { class: 'col-num' }, '耗时'), h('th', {}, '时间'))));
  const tb = h('tbody', {});
  for (const a of rows) {
    tb.append(h('tr', {},
      h('td', { class: 'mono small' }, a.item_id),
      h('td', {}, a.correct ? h('span', { class: 'tag tag-green' }, '对') : h('span', { class: 'tag tag-red' }, '错')),
      h('td', { class: 'col-num' }, String(a.attempt_no)),
      h('td', { class: 'col-num' }, String(a.hint_used)),
      h('td', { class: 'col-num' }, a.duration_ms ? `${(a.duration_ms / 1000).toFixed(1)}s` : '—'),
      h('td', { class: 'small muted' }, fmtTime(a.created_at))));
  }
  table.append(tb);
  box.append(h('div', { class: 'table-wrap' }, table));
  return box;
}

/* ------------------------------------------------------------------ *
 * tab：账号（只读）
 * ------------------------------------------------------------------ */

function renderAccounts(host) {
  clear(host);
  host.append(
    h('div', { class: 'hint-box' },
      '管理员账号由命令行维护（安全考虑：页面上能创建管理员＝一个提权入口）。',
      h('div', { class: 'mono small mt-8' }, 'python scripts/manage_users.py create --username <名字> --role admin'))
  );
  const s = state.accounts;
  if (!s) {
    host.append(h('div', { class: 'skeleton skeleton-block' }));
    return;
  }
  const admins = s.items; // 列表接口目前只列学生；管理员列表由 /api/admin/students 之外的来源补
  const table = h('table', { class: 'data data-table' });
  table.append(h('thead', {}, h('tr', {},
    h('th', {}, '用户名'), h('th', {}, '姓名'), h('th', {}, '角色'), h('th', {}, '状态'), h('th', {}, '最近登录'))));
  const tb = h('tbody', {});
  for (const a of admins) {
    tb.append(h('tr', {},
      h('td', { class: 'mono' }, a.username),
      h('td', {}, a.display_name || '—'),
      h('td', {}, h('span', { class: 'role-badge' }, '学生')),
      h('td', {}, statusTag(a.status)),
      h('td', { class: 'small muted' }, fmtTime(a.last_login_at) || '从未')));
  }
  table.append(tb);
  host.append(h('div', { class: 'table-wrap' }, table));
}

/* ------------------------------------------------------------------ *
 * tab：审计
 * ------------------------------------------------------------------ */

const ACTION_LABEL = {
  login: '登录', logout: '登出', login_failed: '登录失败',
  user_create: '建号', user_import: '批量建号',
  password_reset: '重置密码', password_change: '改自己密码',
  user_disable: '禁用账号', user_enable: '启用账号',
  data_delete: '删除学生数据', export_csv: '导出 CSV',
  view_detail: '查看学生明细',
};

function renderAudit(host) {
  clear(host);
  const a = state.audit;
  if (!a) {
    host.append(h('div', { class: 'skeleton skeleton-block' }));
    return;
  }
  if (!a.items.length) {
    host.append(h('div', { class: 'empty-state' },
      h('div', { class: 'empty-state-ico' }, '🧾'),
      h('div', { class: 'empty-state-title' }, '还没有审计记录')));
    return;
  }
  const table = h('table', { class: 'data data-table' });
  table.append(h('thead', {}, h('tr', {},
    h('th', {}, '时间'), h('th', {}, '操作者'), h('th', {}, '动作'), h('th', {}, '对象'), h('th', {}, '详情'))));
  const tb = h('tbody', {});
  for (const it of a.items) {
    tb.append(h('tr', {},
      h('td', { class: 'small muted' }, fmtTime(it.created_at)),
      h('td', {}, it.actor_username || it.actor_id || '—'),
      h('td', {}, h('span', { class: 'tag tag-gray' }, ACTION_LABEL[it.action] || it.action)),
      h('td', {}, it.target_username || it.target_id || '—'),
      h('td', { class: 'small mono muted' }, JSON.stringify(it.detail || {}).slice(0, 60))));
  }
  table.append(tb);
  host.append(h('div', { class: 'table-wrap' }, table));
}

/* ------------------------------------------------------------------ *
 * 操作
 * ------------------------------------------------------------------ */

async function showDetail(userId, root) {
  try {
    state.detail = await api.adminStudent(userId);
  } catch (err) {
    toast(`读取明细失败：${err.message}`, 'error', 4000);
    return;
  }
  renderCurrent(root);
}

async function resetPassword(st, root) {
  if (!confirm(`重置 ${st.username} 的密码？\n他的所有登录会话会被立刻踢下线。`)) return;
  try {
    const r = await api.adminResetPassword(st.user_id);
    alert(`已重置 ${st.username} 的密码：\n\n${r.new_password}\n\n只显示这一次，请立刻告知本人。`);
  } catch (err) {
    toast(`重置失败：${err.message}`, 'error', 4000);
  }
}

async function setStatus(st, status, root) {
  const verb = status === 'disabled' ? '禁用' : '启用';
  if (!confirm(`${verb} ${st.username}？`)) return;
  try {
    const r = await api.adminSetStatus(st.user_id, status);
    toast(`已${verb}${r.revoked_tokens ? `（踢下线 ${r.revoked_tokens} 个会话）` : ''}`, 'success');
    loadStudents(root);
    loadOverview(root);
  } catch (err) {
    toast(`${verb}失败：${err.message}`, 'error', 4000);
  }
}

async function deleteData(st, root) {
  // 输入用户名二次确认：删除不可逆，防手滑点错人
  const typed = prompt(
    `删除 ${st.username} 的全部作答/问答/掌握度记录？\n\n此操作不可逆。请输入用户名以确认：`
  );
  if (typed !== st.username) {
    if (typed !== null) toast('用户名不一致，已取消', 'warning');
    return;
  }
  try {
    const r = await api.adminDeleteData(st.user_id);
    const n = Object.values(r.deleted || {}).reduce((a, b) => a + b, 0);
    toast(`已删除 ${n} 条记录，账号已脱敏`, 'success');
    state.detail = null;
    loadStudents(root);
    loadOverview(root);
  } catch (err) {
    toast(`删除失败：${err.message}`, 'error', 4500);
  }
}

async function exportCsv() {
  try {
    const blob = await api.adminDownloadCsv();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'students.csv';
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    toast(`导出失败：${err.message}`, 'error', 4000);
  }
}

function openImport(root) {
  const area = h('textarea', {
    class: 'textarea mono',
    rows: 8,
    placeholder: 'username,display_name,password\ns01,张三,\ns02,李四,Passw0rd123',
  });
  const result = h('div', { class: 'small' });
  const btn = h('button', { class: 'btn btn-primary', onclick: submit }, '开始导入');

  async function submit() {
    btn.disabled = true;
    try {
      const r = await api.adminImportStudents(area.value);
      clear(result);
      result.append(
        h('div', {}, `✔ 新建 ${r.created} 人 · 跳过 ${r.skipped.length} · 失败 ${r.failed.length}`)
      );
      if (r.initial_passwords?.length) {
        result.append(
          h('div', { class: 'hint-box warn mt-8' },
            '这些是自动生成的初始密码，**只显示这一次**，请立刻抄走：',
            h('pre', { class: 'mono small' },
              r.initial_passwords.map((p) => `${p.username}\t${p.password}`).join('\n')))
        );
      }
      if (r.failed?.length) {
        result.append(h('div', { class: 'hint-box danger mt-8' },
          h('pre', { class: 'mono small' },
            r.failed.map((f) => `第 ${f.line} 行：${f.reason}`).join('\n'))));
      }
      loadStudents(root);
      loadOverview(root);
    } catch (err) {
      toast(`导入失败：${err.message}`, 'error', 4500);
    } finally {
      btn.disabled = false;
    }
  }

  const panel = h('div', { class: 'card' },
    h('div', { class: 'card-title' }, '批量导入学生（CSV）',
      h('span', { class: 'sub' }, '表头：username, display_name, password（密码留空则自动生成）')),
    area,
    h('div', { class: 'row mt-12' }, btn,
      h('span', { class: 'muted small' }, '最多 500 行 / 256 KB')),
    result);

  const host = root.querySelector?.('#admin-tab-host');
  if (host) {
    clear(host);
    host.append(panel);
  } else {
    toast('导入面板只在「学生」tab 可用', 'warning');
  }
}

/* ------------------------------------------------------------------ *
 * 小工具
 * ------------------------------------------------------------------ */

function statusTag(status) {
  if (status === 'active') return h('span', { class: 'tag tag-green' }, '正常');
  if (status === 'disabled') return h('span', { class: 'tag tag-amber' }, '已禁用');
  return h('span', { class: 'tag tag-gray' }, status || '—');
}

function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(Number(ts) * 1000);
  if (Number.isNaN(d.getTime())) return '';
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
