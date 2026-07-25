# 产品出入库 Web Viewer 嵌入方案

## 范围

- 页面只显示库存摘要、余额趋势和出入库流水。
- 不显示产品编号、产品名称、图片或其他 FileMaker 已有的基础资料。
- 不显示 StarRC 侧边栏、页面标题栏或其他应用导航。
- 全程只读，不修改 FileMaker 记录、布局或脚本。
- 本次只保留在当前 StarRC 项目和本地 Docker 环境，不部署到 mayakofm。

## 本地预览

```text
http://localhost:8080/?page=productInventory&productSku=C-00180-191&operatorAccount=mock.operator&operatorName=本地测试操作员
```

本地预览依赖 `WEBVIEWER_ALLOW_MOCK_CONTEXT=true`。正式环境不应开放 mock context。

## FileMaker Web Viewer 计算式（本地联调）

将下面的字段名替换为当前产品表里的实际产品编号字段：

```filemaker
Let ( [
  baseUrl = "http://localhost:8080/" ;
  sku = GetAsURLEncoded ( 產品::product_sku ) ;
  operatorAccount = GetAsURLEncoded ( Get ( AccountName ) ) ;
  operatorName = GetAsURLEncoded ( Get ( UserName ) )
] ;
  baseUrl &
  "?page=productInventory" &
  "&productSku=" & sku &
  "&operatorAccount=" & operatorAccount &
  "&operatorName=" & operatorName
)
```

建议 Web Viewer 使用当前红框区域的全部宽高，不额外勾选浏览器导航、状态栏或滚动条选项。页面内部会处理明细滚动。

## FileMaker 脚本

先在布局模式选中 Web Viewer，在检查器中把对象名称设为：

```text
wv_product_inventory
```

然后在脚本工作区新建脚本：

```text
脚本名：产品｜载入出入库 Web Viewer
```

脚本步骤如下。`產品::product_sku` 请替换成当前布局实际使用的产品编号字段。

```filemaker
Allow User Abort [ Off ]
Set Error Capture [ On ]

Set Variable [ $sku ; Value: GetAsText ( 產品::product_sku ) ]

If [ IsEmpty ( $sku ) ]
    Show Custom Dialog [
        Title: "无法载入出入库记录" ;
        Message: "当前记录没有产品编号。"
    ]
    Exit Script [ Text Result: "missing productSku" ]
End If

Set Variable [ $baseUrl ; Value: "http://localhost:8080/" ]
Set Variable [ $operatorAccount ; Value: Get ( AccountName ) ]
Set Variable [ $operatorName ; Value: Get ( UserName ) ]

Set Variable [ $url ; Value:
    $baseUrl &
    "?page=productInventory" &
    "&productSku=" & GetAsURLEncoded ( $sku ) &
    "&operatorAccount=" & GetAsURLEncoded ( $operatorAccount ) &
    "&operatorName=" & GetAsURLEncoded ( $operatorName )
]

Set Web Viewer [
    Object Name: "wv_product_inventory" ;
    URL: $url
]

Set Variable [ $lastError ; Value: Get ( LastError ) ]

If [ $lastError ≠ 0 ]
    Show Custom Dialog [
        Title: "Web Viewer 载入失败" ;
        Message: "FileMaker 错误代码：" & $lastError
    ]
    Exit Script [ Text Result: "error=" & $lastError ]
End If

Exit Script [ Text Result: $url ]
```

### 触发方式

- 在“出入记录”页签或按钮上绑定这个脚本，可以按需载入。
- 如果切换产品记录后必须自动刷新，可将脚本绑定到布局的 `OnRecordLoad` 触发器。
- 如果用户可能在进入布局后仍停留在同一条记录，可同时在 `OnLayoutEnter` 执行，但要避免其他布局共用该触发器时重复载入。

### 调试

脚本最后会把完整 URL 作为脚本结果返回。调试时可以在数据查看器检查：

```filemaker
Get ( ScriptResult )
```

如果 Web Viewer 仍显示上一条产品，可先确认对象名称完全等于 `wv_product_inventory`，然后检查 `$sku` 和 `$url` 的实际值。

## 正式接入

1. 在独立于 mayakofm 的内部主机或容器环境部署当前 frontend/backend。
2. 为该主机配置 HTTPS、FileMaker Data API 凭据和只读账号。
3. 保持 `FILEMAKER_READ_ONLY=true`，并关闭 `WEBVIEWER_ALLOW_MOCK_CONTEXT`。
4. 复用项目现有的 `ctx` / `sig` 短期签名上下文，将产品编号与操作员写入签名载荷。
5. FileMaker Web Viewer 只传 `page=productInventory&ctx=...&sig=...`，不要在客户端保存服务端密钥。
6. 用实际 FileMaker Web Viewer 尺寸复测日期控件、字体缩放、CSV 下载和系统代理设置。

## 数据来源

- 流水布局：`產品庫存_TRANSACTION`
- 产品匹配字段：`ID_產品編號`
- 当前库存：`@products::stock`
- 流水读取上限：500 条
- API：`GET /api/products/{productSku}/inventory-transactions`

返回数据会按日期和记录 ID 建立稳定顺序，计算入库合计、出库合计、净变化与逐笔余额。历史记录没有操作员值时显示 `—`，不会用当前登录人冒充历史操作员。
