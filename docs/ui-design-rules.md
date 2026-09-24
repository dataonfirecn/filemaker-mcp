# StarRC 后台 UI 设计规则 v0.2：暖调纸感风格

> 适用范围：`frontend/` 下所有内部后台页面、FileMaker WebViewer 页面、客户门户。
> 目标读者：任何在本仓库写前端的人或 AI。**写任何 UI 代码前先读本文件。**
> 视觉参照：`docs/ui-style-preview.html`（在浏览器打开，右上角可切换亮/暗）。
> 本版替代 v0.1（冷灰 + teal）。审计数据见文末附录。

---

## 1. 风格定位

参照 Claude 网站的气质：**温暖、克制、像纸一样安静**，把注意力留给数据本身。

| 关键词 | 落到界面上 |
|---|---|
| 暖 | 米白/象牙色背景，暖灰文字和边框，没有冷蓝灰 |
| 克制 | 只有一个强调色（陶土橙），其余全部是中性色；用边框和留白分层，少用阴影 |
| 纸感 | 页面底是米色，内容卡片是纯白的"纸"；无渐变、无玻璃拟态、无霓虹色 |
| 人文 | 页面标题、详情名称、KPI 数字用衬线体；操作、表格、表单用无衬线体 |
| 轻 | 细线图标（1.75 描边），中等字重，最重只到 600 |

它不是照搬 Claude 的品牌：不使用 Claude/Anthropic 的 logo、字体授权文件或插画，只借鉴配色温度、字体搭配和留白节奏。

---

## 2. Design Tokens

全部定义在 `frontend/src/styles/tokens.css`（唯一来源）。组件里只能写 `var(--*)`。

### 2.1 颜色：亮色

```css
:root {
  /* 背景层次：页面米色 → 侧栏略深 → 卡片纯白 */
  --color-bg:             #F5F4EE;  /* 页面底（象牙色） */
  --color-sidebar:        #EFEDE4;  /* 侧边导航 */
  --color-surface:        #FFFFFF;  /* 卡片、表格、弹窗、输入框 */
  --color-surface-muted:  #FAF9F5;  /* 卡片内分区、只读字段、代码块 */
  --color-surface-hover:  #F2F0E8;  /* 行悬停、菜单悬停 */
  --color-surface-active: #E9E6DB;  /* 导航选中、按下 */

  /* 文字（全部带一点暖色） */
  --color-text:           #141413;  /* 标题、正文 */
  --color-text-secondary: #3D3D3A;  /* 次级正文、表格正文 */
  --color-text-muted:     #6B6A64;  /* 标签、说明、表头 */
  --color-text-faint:     #A3A29A;  /* 占位符、禁用（不用于必须读的信息） */

  /* 线 */
  --color-border:         #E3E0D5;
  --color-border-strong:  #D1CDBF;
  --color-divider:        #ECEAE2;

  /* 强调色：陶土橙（全站唯一彩色主色） */
  --color-accent:         #C96442;  /* 品牌标识、图标强调、图表主色 */
  --color-primary:        #B5573A;  /* 主按钮底色（白字对比 4.8:1） */
  --color-primary-hover:  #A34E33;
  --color-primary-text:   #AE5234;  /* 链接、选中文字（米底上 4.7:1） */
  --color-primary-soft:   #F6E7DF;  /* 选中底、强调徽章底 */
  --color-focus-ring:     rgba(201, 100, 66, 0.25);

  /* 语义色：低饱和，前景 / 浅底两档 */
  --color-success: #2F7D4F;  --color-success-soft: #E6F0E6;
  --color-warning: #9A6210;  --color-warning-soft: #F8EDD5;
  --color-danger:  #B3372E;  --color-danger-soft:  #F7E3DF;
  --color-info:    #2F6690;  --color-info-soft:    #E3ECF3;
  --color-neutral: #6B6A64;  --color-neutral-soft: #EFEDE6;
}
```

### 2.2 颜色：暗色

暗色也是暖的（炭灰带棕），不是纯黑、也不是蓝黑。

```css
[data-theme="dark"] {
  --color-bg:             #262624;
  --color-sidebar:        #1F1E1D;
  --color-surface:        #30302E;
  --color-surface-muted:  #2B2A28;
  --color-surface-hover:  #383835;
  --color-surface-active: #41403C;

  --color-text:           #FAF9F5;
  --color-text-secondary: #DDDBD2;
  --color-text-muted:     #A6A49B;
  --color-text-faint:     #75736C;

  --color-border:         #43423E;
  --color-border-strong:  #55534E;
  --color-divider:        #3A3936;

  --color-accent:         #D97757;
  --color-primary:        #D97757;  /* 暗色下主按钮用深色字 */
  --color-primary-hover:  #E38A6C;
  --color-on-primary:     #1F1E1D;
  --color-primary-text:   #E8927A;
  --color-primary-soft:   rgba(217, 119, 87, 0.16);
  --color-focus-ring:     rgba(217, 119, 87, 0.35);

  --color-success: #7DBE8F;  --color-success-soft: rgba(125, 190, 143, 0.14);
  --color-warning: #E0B25C;  --color-warning-soft: rgba(224, 178, 92, 0.14);
  --color-danger:  #EB8B80;  --color-danger-soft:  rgba(235, 139, 128, 0.14);
  --color-info:    #8DB6D9;  --color-info-soft:    rgba(141, 182, 217, 0.14);
  --color-neutral: #A6A49B;  --color-neutral-soft: rgba(166, 164, 155, 0.14);
}
```
亮色下 `--color-on-primary: #FFFFFF`。

**用色规则**
- 陶土橙只用于：主按钮、链接、选中态、焦点环、品牌标识、图表第一序列。一屏里橙色面积不超过约 5%。
- 状态颜色只表达语义：入库/增加/完成 = success；出库/减少/错误 = danger；待处理/缺料 = warning；只读/说明 = info；草稿/未知 = neutral。
- 数值正负：`+` success、`-` danger，全站一致。
- **禁止**：渐变、纯黑 `#000`、纯冷灰（`#f8fafc` 这类 slate 色）、蓝色主按钮、彩色卡片边框。

### 2.3 字体

```css
--font-serif: "Source Serif 4", "Songti SC", "Noto Serif SC", "STSong", Georgia, serif;
--font-sans:  "Inter", -apple-system, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
--font-mono:  ui-monospace, "SF Mono", Menlo, Consolas, monospace;
```

- 字体文件 **自托管**（放 `frontend/public/fonts/`，woff2），不从 Google Fonts 加载——国内网络和 FileMaker WebViewer 里经常加载失败。
- 中文衬线用系统宋体兜底；**衬线只用于 ≥20px 的文字**，小字号中文宋体难读。

| 用途 | 字体 | 字号 / 字重 / 行高 |
|---|---|---|
| 页面标题 | serif | 24px / 500 / 1.3 |
| 详情页主体名称（零件名、订单号） | serif | 28px / 500 / 1.25 |
| KPI 大数字 | serif | 32px / 500 / 1.1，`tabular-nums` |
| 空状态标题 | serif | 20px / 500 |
| 卡片标题 | sans | 15px / 600 |
| 正文、输入框 | sans | 14px / 400 / 1.55 |
| 按钮、表格正文、字段值 | sans | 13px / 500（按钮）、400（正文） |
| 字段标签、表头、说明 | sans | 12px / 500 / muted |
| 编号（零件号、PI、UUID、批次） | mono | 13px / 400 |

Token：
```css
--text-xs: 12px; --text-sm: 13px; --text-base: 14px; --text-md: 15px;
--text-lg: 20px; --text-xl: 24px; --text-2xl: 28px; --text-3xl: 32px;
--weight-regular: 400; --weight-medium: 500; --weight-semibold: 600;
```
- 最小 12px；只用 400 / 500 / 600 三种字重（**不再使用 700 以上**）。
- 标题不靠加粗突出，靠衬线体和字号。
- 不用全大写字母间距标签（`LETTER-SPACING` 那种），中文界面不需要。

### 2.4 间距、圆角、阴影

```css
/* 4px 网格 */
--space-1: 4px;  --space-2: 8px;  --space-3: 12px; --space-4: 16px;
--space-5: 20px; --space-6: 24px; --space-8: 32px; --space-10: 40px;

/* 圆角：比 v0.1 略大，更柔和 */
--radius-sm:   6px;    /* 徽章、表格内按钮 */
--radius-md:   8px;    /* 按钮、输入框、下拉 */
--radius-lg:   12px;   /* 卡片、表格容器 */
--radius-xl:   16px;   /* 弹窗、搜索大输入框 */
--radius-full: 999px;  /* 胶囊、头像 */

/* 阴影：几乎不用，靠边框分层 */
--shadow-sm: 0 1px 2px rgba(20, 20, 19, 0.04);
--shadow-md: 0 4px 20px rgba(20, 20, 19, 0.06);  /* 下拉、浮层、聚焦的大输入框 */
--shadow-lg: 0 16px 48px rgba(20, 20, 19, 0.14); /* 弹窗 */
```
- 页面外边距：桌面 32px，WebViewer 20px，手机 16px。卡片内边距 20px，卡片间距 16px。
- 卡片 = 白底 + `1px var(--color-border)` + `--radius-lg`，**不加阴影**。卡片里不再套卡片，分区用 `--color-surface-muted` 或分割线。

### 2.5 尺寸、图标、断点、层级

```css
--control-sm: 30px;  --control-md: 36px;  --control-lg: 44px;  /* PDA/触屏用 lg */
--table-row: 44px;   --table-row-compact: 36px;
--sidebar-width: 248px; --sidebar-collapsed: 64px;

--icon-sm: 14px; --icon-md: 16px; --icon-lg: 20px;  /* lucide strokeWidth 统一 1.75 */

--bp-tablet: 1180px; --bp-narrow: 900px; --bp-mobile: 640px;
--z-sticky: 10; --z-dropdown: 100; --z-drawer: 200; --z-modal: 300; --z-toast: 400;
```

---

## 3. 页面骨架

| 类型 | 用于 | 结构 |
|---|---|---|
| A. 后台页面 | 侧边导航内的模块 | 侧栏（`--color-sidebar`）+ 主区（`--color-bg`）→ PageHeader → 内容 |
| B. WebViewer 页面 | 嵌入 FileMaker 的独立页 | 细顶栏（米色底，标题 + 状态 + 刷新/关闭）→ 内容；按 1068px 宽设计 |
| C. 客户门户 | 外部客户 | 顶部导航 → PageHeader → 内容；英文文案 |

**PageHeader**
```
页面标题（serif 24/500）                         [次按钮] [主按钮]
一句说明（sans 13, muted，可选）
```
- 顶栏和页面标题区都是米色背景，和页面底融为一体，**不做深色顶栏、不做 hero 大图区**。
- 每页最多一个主按钮。

**侧边导航**
- 底色 `--color-sidebar`，无右边框阴影，只用 1px `--color-border`。
- 分组标题：12px / 500 / muted，不加粗、不大写。
- 导航项：高 36px，圆角 8px，图标 16px；悬停 `--color-surface-hover`；选中 `--color-surface-active` + 文字 `--color-text` 600。**选中不用彩色底、不用左侧色条。**
- 计数徽章：neutral 色，不用彩色。

---

## 4. 基础组件

放在 `frontend/src/components/ui/`，全站复用，页面里不再自建同类样式。

### Button
| 变体 | 样式 |
|---|---|
| primary | `--color-primary` 底，`--color-on-primary` 字 |
| secondary | 白底 + `1px --color-border-strong`，文字 `--color-text` |
| ghost | 透明底，悬停 `--color-surface-hover` |
| danger | 白底 + 红字 + 红边框；只在二次确认弹窗里才用红底 |

尺寸 30 / 36 / 44，圆角 8px，字号 13px / 500，图标 16px 在左、间距 6px。悬停只变底色，不做位移、不加阴影。

**IconButton（仅图标按钮）**：「返回」「刷新」这类页面级辅助操作不写文字，用 `<IconButton label="返回列表">`：无边框无底色、图标 16px、`--color-text-muted`，悬停变 `--color-surface-hover` + `--color-text`；`label` 同时作为 `aria-label` 和悬停提示，必填；`loading` 时图标旋转。主操作（保存、提交、新增）仍用带文字的 Button。

### Input / Select / Textarea
- 白底，`1px --color-border-strong`，圆角 8px，高度与按钮同档。
- 聚焦：边框 `--color-accent` + `0 0 0 3px var(--color-focus-ring)`。
- 全局搜索框可用大号样式：高 44px、圆角 16px、`--shadow-md`（Claude 输入框的感觉）。
- label 在上：12px / 500 / muted，与控件间距 6px；必填 `*` 用 danger 色。
- 只读字段：`--color-surface-muted` 底，无边框。

### Badge
- `<Badge tone="success|warning|danger|info|neutral|accent">`，高 22px，12px / 500，圆角 `--radius-full`，soft 底 + 同色字，可带 6px 圆点。
- 业务状态 → tone 映射集中在 `utils/statusTone.ts`。

### Card
- 头部：标题 sans 15/600 + 可选说明 12px muted + 右侧操作；头部与内容之间留白 16px，不强制加分割线。
- 字段网格：label 12px muted 在上，value 14px 在下；列间 24px、行间 16px。

### KPI 卡片
- label 12px muted → 数字 serif 32/500 → 单位/说明 12px muted。数字颜色默认 `--color-text`，只有正负差值才用语义色。

### Table
- 容器：白底卡片，圆角 12px。
- 表头：**无底色**，12px / 500 / muted，下边框 `--color-border`。
- 行：高 44px，行间 `--color-divider` 细线，悬停 `--color-surface-hover`，选中 `--color-primary-soft`。
- 数字右对齐 + `tabular-nums`；编号用 mono；空值 `—`（faint 色）。
- 大数据表用 AG Grid，只允许一个主题 `ag-theme-starrc`，从 token 映射。

### Modal
- 遮罩 `rgba(20,20,19,0.4)`；面板白底、圆角 16px、`--shadow-lg`；宽 440 / 640 / 960。
- 标题 serif 20/500；底部按钮右对齐，主按钮在最右。

### Empty / Loading / Error
- EmptyState：20px 线条图标（muted）→ serif 20px 标题 → 13px 说明 → 可选按钮；居中，无插画。
- Loading：列表和卡片用骨架条（`--color-surface-hover` 呼吸动画），按钮内用 16px 旋转图标。
- Error：`<Alert tone="danger">`，soft 底，写清"发生了什么 + 可以怎么做"。

### 图表（recharts）
- 序列色顺序：`--color-accent` → `#6B8E9B` → `#B8A07E` → `#8A7CA8` → `#7A9A6E`（全部低饱和暖调）。
- 网格线 `--color-divider`，坐标轴文字 12px muted，不画外框。

---

## 5. 动效

- 时长 120–180ms，缓动 `cubic-bezier(0.2, 0, 0, 1)`；只动颜色、透明度、背景。
- 弹窗淡入 + 轻微上移 4px；不做弹跳、缩放、旋转（加载图标除外）。
- 尊重 `prefers-reduced-motion`。

---

## 6. 文案

- 内部后台简体中文；客户门户英文。语气平实、完整句，不用感叹号。
- 按钮动词开头："保存"、"导出 CSV"、"生成零件编号"。
- 空值 `—`；数量"数字 + 单位"（`50 pcs`），单位 muted；日期 `YYYY-MM-DD`；金额 `US$1,234.00`。

---

## 7. 给 AI 的硬性规则

1. 写 UI 前先读本文件和 `docs/ui-style-preview.html`。
2. 只用 `tokens.css` 里的变量；不新增 `:root` 或页面级变量。需要新 token 先改本文件。
3. 组件 CSS 中不出现 hex / rgba 字面值、不在 token 表里的字号 / 圆角 / 阴影。
4. 不使用渐变、蓝色主按钮、700 以上字重、12px 以下字号。
5. 按钮、徽章、弹窗、空状态、加载、表格用 `components/ui/` 的组件，不另建样式类。
6. 不使用 `!important`，不重复定义已有选择器；新页面 CSS 独立成文件，不往 `styles.css` 追加。
7. 暗色模式只通过 token 实现，组件里不写 `[data-theme=dark]` 分支。
8. 交付前在 1068px / 1440px / 390px 三个宽度、亮暗两种主题下截图自检，无水平滚动。

### 自检命令（在 `frontend/src` 下）
```bash
grep -rnE "#[0-9a-fA-F]{3,8}\b|rgba?\(" --include=*.css . | grep -v tokens.css   # 字面颜色
grep -rnE "font-size:\s*([0-9]|1[01])(\.[0-9]+)?px" --include=*.css .           # 小于 12px
grep -rnE "font-weight:\s*([7-9][0-9]{2})" --include=*.css .                    # 700 以上
grep -rnE "linear-gradient|radial-gradient" --include=*.css .                   # 渐变
grep -rn "!important" --include=*.css .
```

---

## 8. 迁移顺序

1. 新建 `styles/tokens.css`（第 2 节），自托管 Source Serif 4。旧变量名（`--teal`、`--pm-*`、`--npw-*`、`--mid-*`）先做成指向新 token 的别名，**这一步就能让全站换上新配色**。
2. 全局替换：`body` 背景 → `--color-bg`；字号 < 12px → 12px；字重 ≥ 700 → 600；删除所有渐变。
3. 实现 Button / Badge / Card / Modal / EmptyState / PageHeader / Sidebar，逐页替换。
4. 页面标题、详情名称、KPI 数字换成衬线体。
5. 拆分 `styles.css`，删除重复选择器和 `!important`，删除 `components/.pm-backup-20260922/`。
6. 最后删除旧变量别名。

---

## 附录：v0.1 审计数据（2026-09-23）

颜色值 594 个 · 主色 5 套 · 变量体系 5 套 · 字号 45 种（9px 用 136 次）· 字重 19 种（90% ≥ 750）· 圆角 37 种 · 阴影 94 种 · padding 215 种 · 控件高度 113 种 · 图标尺寸 26 种 · 断点 25 个 · z-index 23 个 · 重复定义 ≥3 次的选择器 111 个 · `!important` 46 处 · 按钮样式 22 套 · 状态标签 34 套 · 空状态 18 套。
