# AGENTS.md

本文件给所有在本仓库工作的 AI 编程助手（Claude、Codex、Cursor 等）阅读。

## 前端 UI：开工前必读

凡是修改 `frontend/` 下的页面、组件或样式，**先完整阅读**：

1. `docs/ui-design-rules.md`：UI 设计规则（唯一标准）
2. `docs/ui-style-preview.html`：视觉参照（亮 / 暗两种主题）

规则与现有代码冲突时，以规则为准；不要模仿旧页面的写法。

### 最重要的几条（完整内容见规则文档）

- 风格：米白底、白卡片、暖灰文字，**陶土橙是唯一强调色**；不用渐变、不用蓝色主按钮。
- 只用 token（`var(--*)`）。组件 CSS 里不写 hex / rgba 字面值，不新增 `:root` 或页面级变量。
- 字号最小 12px；字重只用 400 / 500 / 600；衬线体只用于 ≥20px 的标题和 KPI 数字。
- 按钮、徽章、弹窗、空状态、加载、表格用 `frontend/src/components/ui/` 的组件，不另建样式类。
- 不用 `!important`，不重复定义已有选择器；新页面 CSS 独立成文件，不往 `styles.css` 追加。
- 暗色模式只通过 token 实现，组件里不写 `[data-theme=dark]` 分支。
- 交付前在 1068px（FileMaker WebViewer）、1440px、390px 三个宽度和亮 / 暗两种主题下自检。
- 不要参考或复制 `frontend/src/components/.pm-backup-*` 等备份目录中的代码。

需要规则里没有的新 token 或新组件时，先修改 `docs/ui-design-rules.md`，再写代码。
