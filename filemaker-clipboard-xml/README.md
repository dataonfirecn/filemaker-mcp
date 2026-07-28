# FileMaker API_Test Clipboard XML

这里是一套给本项目 MES callback 测试用的 FileMaker 剪贴板 XML 片段。

目标对象：

- 表：`API_Test`
- 布局：`API_Test`
- 脚本：`MES_UpdateWorkOrder_Test`

## 使用顺序

1. 打开 `File > Manage > Database...`，切到 `Tables` 标签页。
2. 把 `00-api-test-table-with-fields.fmxmlsnippet.xml` 写入 FileMaker 剪贴板格式，直接粘贴。它会创建 `API_Test` 表和字段。
3. 在 Script Workspace 里粘贴 `02-mes-update-workorder-test-script.fmxmlsnippet.xml`。
4. 创建布局 `API_Test`，显示记录来自表 occurrence `API_Test`。
5. 进入布局模式，把 `03-api-test-layout-objects.fmxmlsnippet.xml` 写入 FileMaker 剪贴板格式后直接粘贴。它已经使用从目标文件复制出来的 `com.filemaker.theme.apex_blue` 主题和真实对象样式，并排成 1024 宽的两栏简约布局，不需要再替换主题名。
6. 后端 `.env` 使用：

```bash
MES_FILEMAKER_LAYOUT=API_Test
MES_FILEMAKER_SCRIPT_NAME=MES_UpdateWorkOrder_Test
```

## 关于剪贴板

这些文件是 FileMaker 的 `fmxmlsnippet` XML 文本。FileMaker 不能把普通文本 XML 直接当成 schema/layout/script 对象粘贴，通常需要 MBS Plugin、FM Clipboard Tool、SharpFM、FM Clipboard Thing 或同类工具把 XML 写回 FileMaker 的内部剪贴板格式后再粘贴。

## 文件

- `00-api-test-table-with-fields.fmxmlsnippet.xml`：表定义和字段定义，贴到 Manage Database 的 `Tables` 标签页。
- `02-mes-update-workorder-test-script.fmxmlsnippet.xml`：完整脚本对象。
- `03-api-test-layout-objects.fmxmlsnippet.xml`：从目标 FileMaker 布局复制出来的真实样式布局对象，已排列为 1024 宽两栏布局，贴到 `API_Test` 布局模式。
- `04-test-callback-payload.json`：后端 callback 测试请求体。
- `08-open-new-part-webviewer-script-steps.fmxmlsnippet.xml`：打开 `Create New Part_Web` 的 Card/Dialog 窗口脚本步骤。
- `09-new-part-webviewer-callback-script-steps.fmxmlsnippet.xml`：接收新建零件结果、保存全局变量并关闭当前 WebViewer 窗口的回调脚本步骤。
- `10-part-assets-table-with-fields.fmxmlsnippet.xml`：建立 `PartAssets` 表及
  34 个字段。二进制文件以 COS 为权威来源，表内 `asset_file` 只作为兼容容器。
- `FILEMAKER_TABLE_XML_NOTES.md`：本次成功创建表和字段的格式记录、失败原因和检查命令。
- `FILEMAKER_LAYOUT_XML_NOTES.md`：本次布局对象显示问题的原因、成功策略和检查命令。

## 参考

- Field XML spec: https://github.com/andykear/FileMaker-XML-field-definitions
- Script XML spec: https://github.com/andykear/FileMaker-XMLsnippet-Claude-Skill
- Layout XML spec: https://github.com/andykear/FileMaker-XMLsnippet-Layout-Claude-Skill
- MBS clipboard XML workflow: https://www.mbsplugins.de/archive/2025-08-29/Copy_and_paste_XML_in_FileMake/monkeybreadsoftware_blog_filemaker
