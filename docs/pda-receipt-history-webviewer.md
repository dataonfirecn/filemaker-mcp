# PDA 成品入库历史 WebViewer

## 使用位置

已安装到业务员日常使用的布局：

- 布局：`訂單 資料_業務`
- 页签：`出入库`
- 位置：`出貨單資料` 入口（Portal）的产品明细行
- 按钮：`入库历史`
- 脚本参数：`GetAsText ( 出貨單資料::ID )`

每条产品明细显示按钮：

```text
入库历史
```

按钮打开独立卡片窗口 `PDA｜成品入库历史`。该布局继续使用
`出貨單資料` table occurrence，并把当前明细的业务主键 `出貨單資料::ID`
传给 WebViewer。不要使用 PI、产品编号或 FileMaker recordId 代替这个主键。

## WebViewer

- 页面：`https://starrc.dataonfire.cn/?page=receiptHistory`
- 对象名：`wv_pda_receipt_history`
- 当前布局尺寸：`1024 × 768 pt`
- WebViewer 位置：左 `0`、上 `183`、宽 `1024`、高 `585`
- 布局正文只保留 WebViewer，四边锚点全部锁定
- 开启“允许 JavaScript 在 Web Viewer 中执行 FileMaker 脚本”
- 页面只读，不创建、修改或删除 FileMaker 数据

WebViewer URL 计算式：

```filemaker
StarRC_WebViewerURL (
  "?page=receiptHistory" &
  "&lineId=" & GetAsURLEncoded ( 出貨單資料::ID )
)
```

`StarRC_WebViewerURL` 负责追加签名的 `ctx` / `sig`，因此 FileMaker 用户不需要
再次登录。后端按 `canViewOrders` 权限检查访问。

如果统一签名函数后续支持将 `lineId` 写进签名载荷，建议增加：

```filemaker
[ "lineId" ; 出貨單資料::ID ; JSONString ]
```

后端已经支持会话级 `lineId` 绑定；签名载荷包含该值后，修改 URL 中的明细 ID
会直接返回 403。

## 打开脚本

脚本名：`PDA｜查看成品入库历史`

```filemaker
设置变量 [
    $lineId ;
    值: Let (
        p = GetAsText ( Get ( 脚本参数 ) ) ;
        If ( IsEmpty ( p ) ; GetAsText ( 出貨單資料::ID ) ; p )
    )
]
新建窗口 [
    风格: 卡片；
    名称: "PDA 成品入库历史"；
    使用布局: "PDA｜成品入库历史"
]
进入查找模式 [ 暂停: 关 ]
设置字段 [ 出貨單資料::ID ; "==" & $lineId ]
执行查找 [ ]
```

按钮始终传入当前 Portal 行的 ID；脚本中的后备取值仅用于开发者直接运行脚本时，
读取当前 `出貨單資料` 记录。

## 页面查询内容

页面以 `出貨單資料::ID` 为查询入口，实时读取：

1. `出貨單資料`
   - 出货单 ID、产品编号、订单参考数量、实际包装数量、包装状态和包装员。
2. `出貨單資料入庫`
   - 每次正式入库的 ID、数量、状态、创建/修改时间与人员。
3. `產品庫存`
   - 用 `ID_出貨單資料入庫` 连接入库记录，并显示流水主键、批号、数量和操作人。
4. `receipt_attachments` 与腾讯 COS
   - 显示本明细的收货图片，以及同一单据的出货照片；图片直接使用短期 COS 链接。
5. `@products` / `ProductAssets`
   - 显示产品名称、当前库存和 COS 产品主图，不读取 FileMaker 容器文件。

## 追溯规则

```text
出貨單資料::ID
  → 出貨單資料入庫::ID_出庫單資料
  → 產品庫存::ID_出貨單資料入庫
```

页面只有在每条“已入库”记录都存在同时匹配入库记录 ID 和明细 ID 的库存流水时，
才显示“ID 关联完整”。订单数量只作为业务参考，不会自动修改订单或阻止成品入库。

## 验收

1. 从一条已有入库的出货单资料打开，页面显示正式入库数量、操作人和库存流水。
2. 页面“追溯键”中的明细 ID 与当前 FileMaker `出貨單資料::ID` 完全相同。
3. 入库记录 ID 与库存流水的 `ID_出貨單資料入庫` 完全相同。
4. 从未入库明细打开，显示空状态，不报错、不生成任何记录。
5. 没有 `canViewOrders` 的账号返回 403。
6. WebViewer 页面刷新后直接读取最新 FileMaker 数据。

## 2026-07-31 实机验收记录

入口测试：

- 从 `訂單 資料_業務` → `出入库` → 产品明细行点击 `入库历史`。
- 传入明细 ID `3CCD5C2C-504E-42BA-88C1-5780C4D9A2E6`。
- 页面正确显示产品 `HT 422` 的空状态，未创建或修改任何数据。

完整追溯测试：

- 出货单资料 ID：`A8E29F9C-ACCD-4598-855B-9FB440AFA44A`
- 出货单 ID：`PI0019694`
- 产品：`PTK-4528`
- 正式入库：`10` 件，共 `1` 次
- 入库记录 ID：`F7AE08FD-7200-4357-8130-377D4345A58C`
- 库存流水：`85136`
- 批号：`NB261555`
- 操作人：`505`
- 当前库存：`10` 件
- 结果：入库记录与库存流水的 ID 关联完整。

自动化验证：后端 `382 passed`；前端 TypeScript 与 Vite 生产构建通过。
