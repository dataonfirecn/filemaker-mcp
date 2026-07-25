# 内部订单合并 WebViewer

## 页面入口

```text
https://starrc.dataonfire.cn/?page=internalOrderMerge&customerId=CU004&customerName=SARL%20IMODEL&currency=USD
```

普通浏览器直接打开这个地址时必须使用内部员工账号登录；从 FileMaker 的 WebViewer 打开时，`StarRC_WebViewerURL` 会追加 HMAC-SHA256 签名的 `ctx` / `sig`，因此自动建立 `filemaker` 会话，不显示登录页。

页面通过 WebViewer 会话首次一次性读取当前客户的全部订单并缓存在页面内存中，默认只显示 `内部订单`；顶部切换到 `全部` 时仅做前端过滤，不会再次请求 FileMaker。首次进入和主动刷新时会显示覆盖整个页面的加载遮罩，避免加载期间重复操作。列表支持按单号搜索、点击表头排序和 25 / 50 / 100 条分页；表格上方与下方各有一条状态栏，同时显示总数据量、当前记录范围、当前页/总页数及完整分页按钮。`訂單分類` 与 `訂單確認` 经过去重后显示在独立“标签”列，不再混入“状态”列。勾选后，表格上方立即显示已选条数、金额合计、`NB…` 内部单号和“查看汇总并合并”按钮；点击后先调用只读预览接口，确认弹窗同时列出来源订单以及按产品编号合并后的出货明细（产品编号、产品名称、汇总数量）。

## WebViewer 对象

- 对象名：`wv_internal_order_merge`
- 位置：独立布局 `客户｜订单合并 WebViewer`，布局上下文必须继续使用 `客戶`
- 建议启用：允许 JavaScript 在 Web Viewer 中执行 FileMaker 脚本
- 布局正文只保留这个 WebViewer；当前对象位置为 `0, 0`，尺寸为 `1024 × 768`
- 检查器「定位」中已锁定上、下、左、右四个锚点，并锁定对象本身；窗口变化时 WebViewer 会同步伸缩

客户资料页的 `合并内部订单` 按钮当前执行：

```filemaker
新建窗口 [
  风格: 浮动文档 ;
  名称: "内部订单合并" ;
  使用布局: "客户｜订单合并 WebViewer"
]
```

目标布局使用相同的 `客戶` 表 occurrence，因此当前客户记录和 URL 计算上下文会保留。原来的 `内部订单合并选择` 布局与客户资料页订单选项卡内的旧 WebViewer 暂时保留，作为回退入口；按钮已不再进入它们。

## 统一 URL 自定义函数

在 `文件 > 管理 > 自定义函数…` 中创建：

- 函数名：`StarRC_WebViewerURL`
- 参数：`relativeURL`
- 所有帐户均可使用

```filemaker
Let ( [
  // StarRC 独立线上地址（不是 Mayako）
  baseURL = "https://starrc.dataonfire.cn/" ;
  // 必须与服务器 WEBVIEWER_CONTEXT_SECRET 完全相同；轮换时两边一起修改
  secret = "<线上 WebViewer 签名密钥>" ;
  normalizedBaseURL = baseURL & If ( Right ( baseURL ; 1 ) = "/" ; "" ; "/" ) ;
  normalizedRelativeURL = If (
    Left ( relativeURL ; 1 ) = "/" ;
    Right ( relativeURL ; Length ( relativeURL ) - 1 ) ;
    relativeURL
  ) ;
  contextJSON = JSONSetElement ( "{}" ;
    [ "operator.account" ; Get ( AccountName ) ; JSONString ] ;
    [ "operator.name" ; Get ( UserName ) ; JSONString ] ;
    [ "operator.privilege" ; Get ( AccountPrivilegeSetName ) ; JSONString ] ;
    [ "operator.persistentId" ; Get ( PersistentID ) ; JSONString ] ;
    [ "customerId" ; 客戶::ID ; JSONString ] ;
    [ "customerName" ; 客戶::公司 ; JSONString ] ;
    [ "currency" ; 客戶::currency ; JSONString ]
  ) ;
  contextBase64 = Base64EncodeRFC ( 4648 ; contextJSON ) ;
  ctx = Substitute ( contextBase64 ;
    [ "+" ; "-" ] ; [ "/" ; "_" ] ; [ "=" ; "" ] ;
    [ Char ( 13 ) ; "" ] ; [ Char ( 10 ) ; "" ]
  ) ;
  sig = Substitute (
    Lower ( HexEncode ( CryptAuthCode ( ctx ; "SHA256" ; secret ) ) ) ;
    [ Char ( 13 ) ; "" ] ; [ Char ( 10 ) ; "" ]
  ) ;
  separator = If ( PatternCount ( normalizedRelativeURL ; "?" ) > 0 ; "&" ; "?" )
] ;
  normalizedBaseURL & normalizedRelativeURL &
  separator & "ctx=" & GetAsURLEncoded ( ctx ) &
  "&sig=" & sig
)
```

密钥只保存在这个 FileMaker 自定义函数和服务器环境变量中，不写入 Web 前端源码，也不通过普通 URL 参数传送。WebViewer 对象本身不再保存主机地址，只传页面与显示参数；客户和操作员身份以签名上下文为准。轮换密钥时应先同步服务器与 FileMaker，再验证签名会话审计记录。

```filemaker
StarRC_WebViewerURL (
  Let ( [
    // 必须传客户表主键 ID（例如 CU004），不要传 ID_DB、ID_DB_Customer 或客戶代號
    customerId = GetAsURLEncoded ( 客戶::ID ) ;
    customerName = GetAsURLEncoded ( 客戶::公司 ) ;
    currency = GetAsURLEncoded ( 客戶::currency ) ;
    operatorAccount = GetAsURLEncoded ( Get ( AccountName ) ) ;
    operatorName = GetAsURLEncoded ( Get ( AccountName ) )
  ] ;
    "?page=internalOrderMerge" &
    "&customerId=" & customerId &
    "&customerName=" & customerName &
    "&currency=" & currency &
    "&operatorAccount=" & operatorAccount &
    "&operatorName=" & operatorName
  )
)
```

如果目标布局使用不同的客户表 occurrence，只需替换上面的字段引用；URL 参数名不要改变。当前实际关联链为 `客戶::ID → 出貨單::ID_客戶 → 出貨單資料::ID_出貨單`，其中后一个关联使用 `出貨單::出貨單 ID`。`customerId` 必须与 `出貨單::ID_客戶` 的实际存储值一致，否则只读列表仍可按客户名称显示，但 Web 写入会被归属校验拒绝。`ID_DB`、`ID_DB_Customer` 和 `ID_SYNC` 均属于外部系统对接字段，本功能不读取也不写入。

## Data API 合并

`POST /api/orders/internal/merge/preview` 先执行只读预览：校验订单归属，从 `出貨單資料_List_業務` 读取源明细并按 `產品編號` 汇总 `數量`，再从 `@products` 批量补充 `product_name`。该接口不创建、修改或删除 FileMaker 记录；预览成功后才向用户显示最终出货明细和写入确认按钮。

`POST /api/orders/internal/merge/web` 不调用任何 FileMaker 脚本，而是在受控后端中复现原业务步骤：

1. 用当前签名 WebViewer 会话的客户 ID 校验每张源订单，拒绝跨客户合并。
2. 从 `出貨單資料_List_業務` 读取源明细，并按 `產品編號` 汇总 `數量`。
3. 在 `訂單 資料_業務_EDIT` 创建主记录，写入日期、`訂單型態 = 零件包` 和 `訂單分類 = 合併單`，让 FileMaker 自动生成订单 ID 和 `NB…` 内部订单编号；随后通过 `@出貨單` 写入 `ID_客戶`。`requestId` 的防重复状态保存在后端专用 `web_merge_request` 表，不占用 FileMaker 的任何对接字段。
4. 读取自动生成的 `出貨單 ID` 和 `內部訂單單據編號`，整理本次合并追溯文字并写入新订单的 `log` 字段。日志包含时间、操作人、客户、目标 `NB…`、来源 `NB…`、来源/汇总明细数、每个产品的编号、名称和汇总数量，以及 `requestId`。
5. 逐条创建汇总明细。业务 ID 只用于接口关联和 FileMaker 导航，面向用户的提示统一显示 `NB…` 编号。
6. 任一步失败时，按相反顺序补偿删除本次已经创建的明细和主记录；如果 `log` 或明细写入失败，也不会留下带有不完整日志的半成品订单。全过程同时写入后端审计日志。

通用 FileMaker 写接口继续由 `FILEMAKER_READ_ONLY=true` 锁定；只有这一个专用接口可由 `FILEMAKER_WEB_MERGE_ENABLED=true` 单独开放。启用前必须确认 Data API 布局包含以下字段：

- `訂單 資料_業務_EDIT`：`日期`、`訂單型態`、`訂單分類`
- `@出貨單`：`出貨單 ID`、`內部訂單單據編號`、`ID_客戶`、`log`
- `出貨單資料_List_業務`：`ID_出貨單`、`產品編號`、`數量`
- `@products`：`product_sku`、`product_name`

当前数据库的 `@出貨單` 不暴露 `日期` 和必填的 `訂單型態`，不能直接作为 Data API 新建布局；Web 合并因此使用 `訂單 資料_業務_EDIT` 新建、`@出貨單` 校验和补写身份字段。线上已设置 `FILEMAKER_WEB_MERGE_ENABLED=true`。

`log` 是 `出貨單` 表的普通文本字段，并已加入专用 `@出貨單` Data API 布局。Web 合并只写入本次新建订单的该字段，不读取或修改其他订单的历史日志。

确认弹窗只保留“确认并通过 Data API 合并”按钮；按钮上方必须已显示合并后的出货明细。成功后网页只显示 `NB…` 新内部订单编号、来源订单数和汇总明细数，不向用户显示内部使用的 `PI…` ID，并停留等待用户选择：

- “完成并关闭窗口”：调用 `StarRC_CloseWebViewer` 关闭浮动窗口。
- “完成并打开新订单”：调用 `StarRC_OpenMergedOrder`，把 Data API 返回的 `newOrderId` 作为 JSON 脚本参数传回 FileMaker；脚本进入固定的 `訂單 資料_業務` 布局并查找该订单。Data API 创建记录仍使用 `訂單 資料_業務_EDIT`，两者用途不同。

两个脚本都只负责 FileMaker 界面导航，不创建、修改或删除订单。关闭脚本为：

```filemaker
关闭窗口 [ 当前窗口 ]
```

打开新订单脚本为：

```filemaker
设置变量 [ $newOrderId ; 值: JSONGetElement ( Get ( 脚本参数 ) ; "newOrderId" ) ]
转到布局 [ “訂單 資料_業務” (出貨單) ; 动画: 无 ]
进入查找模式 [ 暂停: 关 ]
设置字段（按名称） [ "出貨單::出貨單 ID" ; $newOrderId ]
执行查找 [ ]
```

网页仍暴露 `StarRCInternalOrders.reload()`，FileMaker 可在外部数据变化后调用它刷新订单列表。

## 数据接口

- `GET /api/orders/internal?scope=internal|all`
- `POST /api/orders/internal/merge/preview`（只读：校验并返回合并后的出货明细）
- `POST /api/orders/internal/merge/web`（专用 Data API 写接口，默认关闭）
- 客户名称来自已签名或本地 mock WebViewer 会话，不接受任意客户查询参数
- 查询布局：`訂單 清單_業務`、`@出貨單`、`訂單 清單`
- `scope=internal`（默认）：增加过滤 `訂單分類 = 内部订单`
- `scope=all`：只限定当前客户，不增加订单分类条件
- WebViewer 首次固定请求 `scope=all`；“全部 / 内部订单”切换、搜索、排序和分页都在浏览器缓存中完成
- “全部”只展示具备 `內部訂單單據編號` 和业务订单 ID、可交给合并脚本处理的记录；缺少内部单号的历史记录会在页脚单独计数，不会静默混入可选择列表
- 确认弹窗只允许通过 Web Data API 写入；FileMaker 脚本只负责完成后的关闭或导航
- 搜索只匹配内部单号、业务订单 ID、PI 和客户 PO，不会因为概要或状态文字意外命中
- 排序与分页在浏览器内对当前已读取结果执行；翻页不会清空之前页面的勾选

## 验证

- 前端生产构建通过
- 后端内部订单接口与 WebViewer 会话测试通过
- 标签是独立列；状态列只显示包装、付款和已过天数
- 列表支持单号搜索、全部表头排序、每页 25 / 50 / 100 条、首页/上页/下页/末页导航
- 首次加载、刷新和切换“全部 / 内部订单”时显示全页加载遮罩
- 勾选后立即显示选择工具条；达到两条时启用“查看汇总并合并”按钮
- 确认弹窗显示客户、条数、金额、标签、完整已选订单清单，以及按产品编号汇总后的产品名称和数量
- 所有选择汇总和完成提示均使用 `NB…` 内部订单编号；`PI…` 仅保留在接口关联及导航参数中
- 新订单的 `log` 包含完整合并追溯文字；单元测试验证来源单号、操作人、客户、汇总数量和 `requestId` 均写入
- 使用真实 FileMaker Data API 验证：`SARL IMODEL` 返回 33 张内部订单；“全部”范围有 787 张源记录，其中 752 张具备可合并的业务订单 ID，35 张缺少内部单号并在页面底部明确提示
- 单次最多读取 5,000 张源订单；超过上限时接口返回 `truncated=true`，页面明确显示“当前结果不完整”，不得把截断结果当作客户全部订单
- FileMaker Pro 实机验证：按钮打开独立浮动窗口，WebViewer 铺满正文并随四边伸缩；“全部 / 内部订单”可双向切换
- 1280 × 720 嵌入尺寸验证：列表、滚动、搜索、勾选、金额合计、确认弹窗和桥接参数均正常
