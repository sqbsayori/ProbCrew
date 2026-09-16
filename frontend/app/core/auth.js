/**
 * 认证与访问控制（前端侧）
 * ======================
 *
 * 三件事：
 *   1. **令牌的存取**（`localStorage['probstat.token']`）；
 *   2. **会话状态**（当前用户放 store，供顶栏/导航/页面读取）；
 *   3. **访问规则**（哪些路由要登录、哪些只有管理员能进）。
 *
 * ## 为什么本文件不 import api.js
 * `api.js` 需要本文件提供 `authHeaders()`，本文件如果反过来 import `api.js`，
 * 就形成循环依赖（ESM 能跑通，但初始化顺序会变得很难预测）。
 * 所以：**本文件自己 fetch 那四个认证端点**，其余请求一律走 `api.js`。
 * 遇到 401 要跳登录页时，也不直接 import router，而是让 bootstrap 注入回调
 * （见 `setUnauthorizedHandler`）—— 装配点只有一个，依赖方向就不会打结。
 *
 * ## ⚠️ 前端权限不是权限
 * `canEnter()` / `canSee()` 只决定"**看不看得见、进不进得去**"，
 * 真正的权限判定在服务端（`kernel/auth.py` 的 `require_admin`）。
 * 把菜单藏起来挡不住任何人直接敲接口地址。
 */
import { bus, EV } from './bus.js';
import { store } from './store.js';

const TOKEN_KEY = 'probstat.token';
const USER_KEY = 'probstat.user';

/** 登录页路由（唯一不需要登录的路由） */
export const LOGIN_ROUTE = 'login';

/** 只有管理员能进的路由。其余路由学生与管理员都能进（管理员也需要能用刷题页）。 */
const ADMIN_ONLY_ROUTES = new Set(['admin']);

/* ------------------------------------------------------------------ *
 * 401 处理（由 bootstrap 注入跳转动作）
 * ------------------------------------------------------------------ */

let unauthorizedHandler = null;

/** 注入"未登录该去哪"的回调。bootstrap 里调一次即可。 */
export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = typeof fn === 'function' ? fn : null;
}

/** 清掉本地会话并跳登录。可被 api.js 在收到 401 时调用。 */
export function handleUnauthorized(reason = '') {
  clearSession();
  if (unauthorizedHandler) unauthorizedHandler(reason);
}

/** api.js 用的异常类型：页面可以 `catch (e) { if (e.status === 401) ... }` */
export class AuthError extends Error {
  constructor(message, status = 401) {
    super(message);
    this.name = 'AuthError';
    this.status = status;
  }
}

/* ------------------------------------------------------------------ *
 * 令牌与用户信息的存取
 * ------------------------------------------------------------------ */

function storage() {
  try {
    return globalThis.localStorage || null;
  } catch {
    return null; // 隐私模式下访问 localStorage 会抛异常
  }
}

export function getToken() {
  return storage()?.getItem(TOKEN_KEY) || '';
}

function readCachedUser() {
  try {
    const raw = storage()?.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/** 写入登录态（令牌 + 用户），并广播 `auth:change`。 */
export function setSession(token, user) {
  const s = storage();
  if (s) {
    if (token) s.setItem(TOKEN_KEY, token);
    if (user) s.setItem(USER_KEY, JSON.stringify(user));
  }
  store.set('user', user || null);
  bus.emit(EV.AUTH_CHANGE, { user: user || null });
}

/** 清掉登录态。**不清 sessionId** —— 会话 id 是匿名追踪用的，与账号无关。 */
export function clearSession() {
  const s = storage();
  s?.removeItem(TOKEN_KEY);
  s?.removeItem(USER_KEY);
  store.set('user', null);
  bus.emit(EV.AUTH_CHANGE, { user: null });
}

/* ------------------------------------------------------------------ *
 * 便捷读取
 * ------------------------------------------------------------------ */

export function currentUser() {
  return store.get('user') || readCachedUser() || null;
}

export function roleOf(user = currentUser()) {
  return user?.role || '';
}

export function displayNameOf(user = currentUser()) {
  return user?.display_name || user?.username || '';
}

export function isLoggedIn() {
  return Boolean(getToken() && currentUser());
}

export function isAdmin(user = currentUser()) {
  return roleOf(user) === 'admin';
}

/** 注入到所有请求的认证头。没登录时是空对象。 */
export function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/* ------------------------------------------------------------------ *
 * 认证请求（自带 fetch —— 见文件头"为什么不 import api.js"）
 * ------------------------------------------------------------------ */

async function authFetch(path, { method = 'GET', body } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    // 网络层失败：后端没起、断网、被 CORS 拦。给人话，不抛原始错误。
    throw new AuthError('无法连接后端，请确认服务已启动', 0);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* 忽略：有些错误响应不是 JSON */
    }
    throw new AuthError(typeof detail === 'string' ? detail : '请求失败', res.status);
  }
  if (res.status === 204) return {};
  try {
    return await res.json();
  } catch {
    return {};
  }
}

/**
 * 登录。成功返回 user 并写入会话。
 *
 * 失败时抛 `AuthError`，`status` 决定页面文案（**三套，别笼统写"登录失败"**）：
 *   401 用户名或密码不正确 · 403 账号已被禁用 · 423 尝试次数过多（detail 里有剩余秒数）
 */
export async function login(username, password) {
  const data = await authFetch('/api/auth/login', {
    method: 'POST',
    body: { username, password },
  });
  setSession(data.token, data.user);
  return data.user;
}

/** 登出：撤销服务端令牌（失败也要清本地，否则用户会卡在"以为已退出"的状态）。 */
export async function logout() {
  try {
    await authFetch('/api/auth/logout', { method: 'POST' });
  } catch (err) {
    console.warn('[auth] 登出请求失败，仍清除本地会话', err);
  }
  clearSession();
}

/**
 * 用本地令牌向后端确认身份。三个用途：
 *   - 启动时校验（令牌可能已在服务端被撤销/过期）；
 *   - 刷新用户信息（管理员改了显示名）；
 *   - **返回 null 表示未登录**，不抛错 —— 启动流程不该被一个 401 打断。
 */
export async function refreshMe() {
  if (!getToken()) return null;
  try {
    const data = await authFetch('/api/auth/me');
    setSession(getToken(), data.user);
    return data.user;
  } catch (err) {
    if (err.status === 401) clearSession();
    return null;
  }
}

/** 改自己密码。成功后会拿到一张新令牌（其他设备的令牌被服务端撤销）。 */
export async function changePassword(oldPassword, newPassword) {
  const data = await authFetch('/api/auth/password', {
    method: 'POST',
    body: { old_password: oldPassword, new_password: newPassword },
  });
  setSession(data.token, data.user);
  return data.user;
}

/* ------------------------------------------------------------------ *
 * 访问规则（导航与守卫共用同一套，避免两处不一致）
 * ------------------------------------------------------------------ */

/** 这个路由需不需要登录？ */
export function needsAuth(route) {
  return route !== LOGIN_ROUTE;
}

/** 这个角色能不能进这个路由？ */
export function canEnter(route, role = roleOf()) {
  if (!needsAuth(route)) return true;
  if (!role) return false;
  if (ADMIN_ONLY_ROUTES.has(route)) return role === 'admin';
  return true;
}

/** 导航里要不要显示这一项？（与 canEnter 同源，只是没登录时什么业务菜单都不显示） */
export function canSee(route, role = roleOf()) {
  return canEnter(route, role);
}

/** 登录成功后该落到哪个页面。 */
export function defaultRoute(role = roleOf()) {
  return role === 'admin' ? 'admin' : 'workbench';
}
