# FileMaker API_Test Clipboard XML

这里是一套给本项目 MES callback 测试用的 FileMaker 剪贴板 XML 片段。

目标对象：

- 表：`API_Test`
- 布局：`API_Test`
- 脚本：`MES_UpdateWorkOrder_Test`

## 使用顺序

1. 打开 `File > Manage > Database...`，切到 `Tables` 标签页。
2. 把 `00-api-test-table-with-fields.fmxmlsnippet.xml` 写入 FileMaker 剪贴板格式，直接粘贴。它会创建 `API_Test` 表和字段。
   如果只创建了空表，删除空表后试 `00-api-test-table-with-fields-direct-fallback.fmxmlsnippet.xml`。
3. 在 Script Workspace 里粘贴 `02-mes-update-workorder-test-script.fmxmlsnippet.xml`。如果完整脚本对象粘贴不稳定，就手动新建脚本 `MES_UpdateWorkOrder_Test`，再粘贴 `02-mes-update-workorder-test-script-steps.fmxmlsnippet.xml`。
4. 创建布局 `API_Test`，显示记录来自表 occurrence `API_Test`。
5. 从目标布局任意复制一个对象，取得它的 `<ThemeName>`，把 `03-api-test-layout-objects.fmxmlsnippet.xml` 里的 `THEME_NAME_REPLACE_ME` 全部替换成真实值，再切到布局模式粘贴。
6. 后端 `.env` 使用：

```bash
MES_FILEMAKER_LAYOUT=API_Test
MES_FILEMAKER_SCRIPT_NAME=MES_UpdateWorkOrder_Test
```

## 关于剪贴板

这些文件是 FileMaker 的 `fmxmlsnippet` XML 文本。FileMaker 不能把普通文本 XML 直接当成 schema/layout/script 对象粘贴，通常需要 MBS Plugin、FM Clipboard Tool、SharpFM、FM Clipboard Thing 或同类工具把 XML 写回 FileMaker 的内部剪贴板格式后再粘贴。

## 文件

- `00-api-test-table.md`：表、字段、布局、脚本的人工核对说明。
- `00-api-test-table-with-fields.fmxmlsnippet.xml`：表定义和字段定义，贴到 Manage Database 的 `Tables` 标签页。
- `00-api-test-table-with-fields-direct-fallback.fmxmlsnippet.xml`：不包 `ObjectList` 的备用表定义。
- `01-api-test-fields.fmxmlsnippet.xml`：字段定义，贴到 Manage Database 的 `API_Test` 表。
- `02-mes-update-workorder-test-script.fmxmlsnippet.xml`：完整脚本对象。
- `02-mes-update-workorder-test-script-steps.fmxmlsnippet.xml`：只有脚本步骤的备用版本。
- `03-api-test-layout-objects.fmxmlsnippet.xml`：布局 UI 对象，贴到 `API_Test` 布局模式。
- `04-test-callback-payload.json`：后端 callback 测试请求体。

## 参考

- Field XML spec: https://github.com/andykear/FileMaker-XML-field-definitions
- Script XML spec: https://github.com/andykear/FileMaker-XMLsnippet-Claude-Skill
- Layout XML spec: https://github.com/andykear/FileMaker-XMLsnippet-Layout-Claude-Skill
- MBS clipboard XML workflow: https://www.mbsplugins.de/archive/2025-08-29/Copy_and_paste_XML_in_FileMake/monkeybreadsoftware_blog_filemaker
