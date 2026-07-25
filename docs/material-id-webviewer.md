# 零件编号生成 WebViewer

独立入口：

```text
https://starrc.dataonfire.cn/?page=materialIdWebViewer
```

该地址必须由 FileMaker 自定义函数 `StarRC_WebViewerURL` 添加签名的
`ctx` / `sig`。WebViewer 页面不复用原生 `MaterialIDGenerator_Gen`
布局中的控件，也不新增业务字段。

## FileMaker 布局

- 布局名：`MaterialIDGenerator_WebViewer`
- 表 occurrence：`INDEX_IDGenerator`
- 正文是单一主体区，只保留一个 WebViewer 对象，不包含原布局的顶部导航
- WebViewer 对象名：`wv_material_id_generator`
- WebViewer 尺寸：`1024 × 723`
- 网页内容采用上下单列结构：“编号组成 / 相关零件”在上，“生成结果”在下，
  不需要横向滚动。
- URL 计算：

```filemaker
StarRC_WebViewerURL ( "?page=materialIdWebViewer" )
```

- WebViewer 锁定上、下、左、右四个锚点

原生布局 `MaterialIDGenerator_Gen` 保持不变，作为独立回退入口。

## FileMaker 打开脚本

脚本名：`生成零件编号_WebViewer`

- 脚本显示在“脚本”菜单中，作为独立入口。
- 普通窗口中以 `Card` 窗口打开 `MaterialIDGenerator_WebViewer`。
- 已处于对话框窗口时，改用 `Dialog` 窗口打开，尺寸为 `1024 × 760`。
- 不修改或跳转到原生布局 `MaterialIDGenerator_Gen`。

## WebViewer 使用编号脚本

脚本名：`DOF_IDGen_WebViewer使用`

```filemaker
设置错误捕获 [ 开 ]

设置字段 [ INDEX_IDGenerator::MatMaterial ;
    JSONGetElement ( Get ( 脚本参数 ) ; "material" ) ]
设置字段 [ INDEX_IDGenerator::MatCustomer ;
    JSONGetElement ( Get ( 脚本参数 ) ; "customer" ) ]
设置字段 [ INDEX_IDGenerator::MatSerialNumber ;
    JSONGetElement ( Get ( 脚本参数 ) ; "serial" ) ]
设置字段 [ INDEX_IDGenerator::MatManufacture ;
    JSONGetElement ( Get ( 脚本参数 ) ; "manufacture" ) ]
设置字段 [ INDEX_IDGenerator::MatColor ;
    JSONGetElement ( Get ( 脚本参数 ) ; "color" ) ]
设置字段 [ INDEX_IDGenerator::MatOther ;
    JSONGetElement ( Get ( 脚本参数 ) ; "other" ) ]
设置字段 [ INDEX_IDGenerator::MatOutput ;
    JSONGetElement ( Get ( 脚本参数 ) ; "output" ) ]
设置字段 [ INDEX_IDGenerator::MAT_RELATEDID ;
    JSONGetElement ( Get ( 脚本参数 ) ; "relatedPartNumber" ) ]

执行脚本 [ “DOF_使用ID” ]
```

该桥接脚本隐藏在“脚本”菜单中，并以完全访问权限运行。网页的“使用此编号”
按钮只调用这个脚本；参数写入生成器全局字段后，最终写入零件、带入内外名称、
客户 ID 和零件性质，仍由现有 `DOF_使用ID` 完成。

仓库分工、照片及其他新建零件资料不再放在此独立编号工具中。它们统一由
独立的新建零件 WebViewer 完整流程处理。

## 数据来源

- 性质：布局 `MaterialIDGenerator_Gen` 的值列表 `零件性質`
- 客户：布局 `MaterialIDGenerator_Gen` 的值列表 `客戶2`
- 加工：`MaterialManufactor_EDIT`
- 颜色：`MaterialColor_EDIT`
- 其他：`MaterialOther_EDIT`
- 相关零件：`@零件`，按编号、内部名称、对外名称实时搜索
- 编号与重复检查：`POST /api/material-ids/generate`

网页不缓存跨会话业务数据，每次打开都会重新读取 FileMaker 配置。

## 验收记录

- 物料、客户、加工、颜色、其他选项均能从 FileMaker 加载。
- 测试选择 `CB · 碳纤维` 和 `007 · Simba Dickie HK Ltd.`，生成结果为
  `CB007-001`，自动序号为 `001`。
- 相关零件搜索 `SE2019` 能返回 `SE2019-00` 和 `FHSE2019-00`。
- 为避免修改正式零件记录，验收时没有点击“使用此编号”；写回按钮、桥接脚本
  和现有 `DOF_使用ID` 的连接已完成。

FileMaker 可粘贴脚本片段：

- `filemaker-clipboard-xml/05-material-id-webviewer-use-script.fmxmlsnippet.xml`
- `filemaker-clipboard-xml/06-open-material-id-webviewer-script-steps.fmxmlsnippet.xml`
- `filemaker-clipboard-xml/07-material-id-webviewer-use-script-steps.fmxmlsnippet.xml`
