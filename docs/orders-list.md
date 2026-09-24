# Web 订单列表与订单详情

入口：浏览器工作台 → 订单管理 → 订单。列表 `/?page=orders`，详情 `/?page=orderDetail&orderId=<出貨單 id>`。交互与需求单一致：列表（搜索 + AG Grid + 分页）→ 点订单号或双击行进入明细 → 左上角返回列表。浏览器返回、刷新、详情直达均可使用。

## 为什么改

原来导航「订单详情」直接进单个订单页，而该页只认地址里的 `orderId`（或 FileMaker 签名上下文里的订单 ID）。从导航进入时两者都没有，页面只能报「URL 缺少出貨單 ID」；列表里的 `internal_id`（`NB…`）也不是详情用的 `出貨單.id`（`PI…`），两边没有配对。现在列表每行都带出貨單 `id`，点进去直接用它读取。

## 接口

- `GET /api/orders?q=&page=&page_size=`（`canViewOrders`；`page_size` 默认 25，上限 100）。
- 列表主体读 `訂單 清單_業務`（客户、概要、包装状态、金额），按订单日期倒序（该布局没有「日期」字段时自动退回内部单号倒序）；再用内部单号从 `@出貨單` 补 `id`、PI、客户 PO，从 `訂單 清單` 补日期与付款状态。
- 搜索：内部单号、概要、客户名称，以及 `@出貨單` 的 `id` / `出貨單 PI` / `訂單 PO`（命中的订单按内部单号补进结果）。用户输入整体加引号，FileMaker 查找运算符不改变语义。
- 带客户名称的会话（客户专属 WebViewer）只返回该客户订单；金额仅 `canViewPrice` 可见。
- 找不到对应出貨單的记录仍会列出，但 `orderId` 为空，前端不提供进入明细的入口。

## 前端

- 新增 `OrderListPage`；`DataGrid` 从需求单页抽成共享组件（列宽、顺序、显示列各表独立记忆）。
- 默认只显示常用列，PI 编号、客户订单号、分类、已过天数在「调整字段」里打开。
- 详情页从列表进入时显示侧栏和「返回订单列表」；FileMaker 带签名上下文直达时仍是无侧栏独立页。没有 `orderId` 的旧链接（`/?page=orderDetail`）自动回到订单列表。

## 验证

```sh
PYTHONPATH=backend python -m pytest backend/tests/test_orders_list_api.py backend/tests/test_internal_orders_api.py -q
cd frontend && npx tsc --noEmit && npm run build
```

浏览器行为（列表 → 明细 → 返回 → 前进后退 → 刷新、搜索空结果与错误、旧链接回退，1440 / 1068 / 390 × 亮暗）已用回放接口数据验证；未连接真实 FileMaker，上线后需用真实数据确认「日期」排序与搜索命中。
