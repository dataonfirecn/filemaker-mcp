# FileMaker 布局剪贴板 XML 成功记录

记录日期：2026-07-01

本记录用于说明 `03-api-test-layout-objects.fmxmlsnippet.xml` 的来源和维护方式。

## 当前策略

布局对象不要凭空手写样式。当前 `03` 文件使用的是从目标 FileMaker 布局复制出来的真实 `LayoutObjectList`。

这次替换后的布局对象特征：

- 主题：`com.filemaker.theme.apex_blue`
- 字体：`华文细黑`
- 画布宽度：1024
- 内容边距：左右各 48
- 排版：两栏表单，单行字段在上，JSON 和错误信息长文本区域在下
- 对象数量：26
- 标签对象：13
- 字段对象：13
- 按钮对象：0
- 字段全部绑定到 `API_Test::...`
- 标签左对齐，显示文案使用更易读的英文标题，例如 `Work Order No`、`FileMaker Result JSON`。

这样做比手写 `ThemeName`、字体、颜色、边框、padding 更稳定，可以避免粘贴后字体回退、文本换行、对象高度异常等问题。

## 为什么旧版显示不对

旧版 `03` 是手写布局对象：

- 使用占位主题 `THEME_NAME_REPLACE_ME`。
- 使用 Helvetica 字体，而目标文件实际使用中文主题字体。
- 字段对象只有少量 `Styles`，缺少 FileMaker 真实复制出来的 `ExtendedAttributes` 和完整 CSS。
- 部分文本框宽度偏小，FileMaker 粘贴后容易重新排版并换行。

布局 XML 比表和脚本更依赖目标文件主题和对象样式，所以最稳的方式是先从目标文件复制真实对象，再在 XML 层替换字段名、位置或文案。

## 粘贴步骤

1. 在 FileMaker 中创建布局 `API_Test`。
2. 布局显示记录来自表 occurrence `API_Test`。
3. 进入 Layout Mode。
4. 用支持 FileMaker 剪贴板格式的工具，把 `03-api-test-layout-objects.fmxmlsnippet.xml` 写入剪贴板。
5. 直接粘贴到布局上。

## 本地检查命令

检查 XML：

```bash
xmllint --noout filemaker-clipboard-xml/03-api-test-layout-objects.fmxmlsnippet.xml
```

检查对象数量和主题：

```bash
xmllint --xpath 'concat("objects=", count(/fmxmlsnippet/Layout/Object), " fields=", count(/fmxmlsnippet/Layout/Object[@type="Field"]), " texts=", count(/fmxmlsnippet/Layout/Object[@type="Text"]), " buttons=", count(/fmxmlsnippet/Layout/Object[@type="Button"]), " theme=", //ThemeName[1])' filemaker-clipboard-xml/03-api-test-layout-objects.fmxmlsnippet.xml
```

成功时应类似：

```text
objects=26 fields=13 texts=13 buttons=0 theme=com.filemaker.theme.apex_blue
```

检查是否还有主题占位符：

```bash
rg 'THEME_NAME_REPLACE_ME' filemaker-clipboard-xml/03-api-test-layout-objects.fmxmlsnippet.xml
```

没有输出才是正常状态。

## 维护原则

- 以后调整布局，优先在 FileMaker 里复制一个显示正确的对象样板出来，再基于真实 XML 修改。
- 不要手写一套新的字体、边框和 CSS。
- 调整版面时优先修改 `Bounds`，尽量保留 FileMaker 复制出来的 `ExtendedAttributes` 和 `FullCSS`。
- 如果新增按钮，先在目标布局里做一个样式正确的按钮并复制 XML，再合并到 `03`。
- 如果字段名变化，同步检查 `API_Test::字段名` 引用。
