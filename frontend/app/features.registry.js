/**
 * 本文件由 `scripts/gen_registry.py` 自动生成，请勿手工编辑。
 *
 * 新增页面：在 app/features/ 下新建目录，放入 feature.json 与 index.js，
 * 然后重新运行生成脚本即可。这样多人并行开发不会在同一份清单上冲突。
 */
export const FEATURES = [
  {"id": "admin", "dir": "admin", "title": "学生数据管理", "icon": "🛠️", "route": "admin", "group": "管理", "order": 5, "subtitle": "班级统计 · 学生明细 · 账号与审计"},
  {"id": "workbench", "dir": "workbench", "title": "工作台", "icon": "🏠", "route": "workbench", "group": "概览", "order": 10, "subtitle": "系统总览 · Agent 角色 · 协作拓扑"},
  {"id": "knowledge", "dir": "knowledge", "title": "知识讲解", "icon": "📚", "route": "knowledge", "group": "学习", "order": 20, "subtitle": "检索教材 · 生成讲解 · 推荐交互动画"},
  {"id": "solver", "dir": "solver", "title": "题目讲解", "icon": "✏️", "route": "solver", "group": "学习", "order": 25, "subtitle": "逐步解题 · 独立校验 · 人机协同确认"},
  {"id": "visualize", "dir": "visualize", "title": "分布可视化", "icon": "📊", "route": "visualize", "group": "学习", "order": 30, "subtitle": "SymPy 符号推导 · 交互式 PDF/CDF · Agent 解读"},
  {"id": "assistant", "dir": "assistant", "title": "页面助手", "icon": "🐾", "route": "assistant", "group": "资源", "order": 35, "subtitle": "悬浮球 / 页宠 · 活体读取演示 · 两条投递路线"},
  {"id": "animations", "dir": "animations", "title": "交互动画", "icon": "🎬", "route": "animations", "group": "资源", "order": 40, "subtitle": "8 个自包含 H5 动画 · 可被 Agent 推荐与驱动"},
  {"id": "runs", "dir": "runs", "title": "运行轨迹", "icon": "🧵", "route": "runs", "group": "数据", "order": 45, "subtitle": "多 Agent 协作全过程留档与回放"},
  {"id": "analytics", "dir": "analytics", "title": "学习数据", "icon": "📈", "route": "analytics", "group": "数据", "order": 50, "subtitle": "问答记录 · 薄弱知识点 · 进度追踪"},
  {"id": "architecture", "dir": "architecture", "title": "架构与分工", "icon": "🧩", "route": "architecture", "group": "团队", "order": 60, "subtitle": "事件契约 · 扩展点 · 五人分工与开发计划"}
];
