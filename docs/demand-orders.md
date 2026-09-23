# Web 需求单

入口：浏览器工作台 → 订单管理 → 需求单。列表 `/?page=demandOrders`，详情 `/?page=demandOrderDetail&recordId=<FileMaker recordId>`。浏览器返回、刷新和详情直达均可使用。

## 数据与权限

- `GET /api/demand-orders`：FileMaker Data API 布局 `@需求單`，按 `日期`、`id` 倒序，默认每页 25 条，上限 100 条。支持 `q`（单号、内部订单、概要、需求公司、公司）、`completion=all|open|completed`、`page`、`page_size`。
- `GET /api/demand-orders/{recordId}`：同一布局读取单头，以业务字段 `id` 关联 FileMaker OData `需求單BOM.ID_需求單`，明细独立分页。OData 使用 `ROWID` 稳定排序；小写 `id` 在此服务器的 `$select` / `$orderby` 中会产生解析错误，因此明细标识从 OData `@id` 取记录主键。
- 使用现有服务器 FileMaker 配置及 `FILEMAKER_ODATA_ENABLED`，凭证留在后端；接口只有 GET。沿用登录会话和 `canViewOrders` 权限。
- 响应显式映射公开字段，不返回原始记录或价格、税率、金额。
- 完成筛选依据 `完成日期` 是否填写，不推断数字 `status` 的业务含义；审核、采购和需求状态保留来源文字。
- 数量来自 `數量`、`額外數量`、`入庫數量`；空值保持为空，零值显示 0。日期统一转为 `YYYY-MM-DD`。源字段没有单位，不添加猜测单位。

## 界面与验证

依据根目录 `CLAUDE.md` → `AGENTS.md` → `docs/ui-design-rules.md` 与视觉参照实现。此次补齐 `components/ui/` 中所用的基础组件；颜色、字号、字重、间距、圆角均复用已有 token。需求单页面 CSS 独立，不向 `styles.css` 追加。

2026-09-23 实际 FileMaker 只读联调：22,020 张需求单，最新 `DM263774`，4 条明细，每条需求数量 1,200，单号搜索结果 1 条。

验证命令：

```sh
PYTHONPATH=backend python -m pytest backend/tests/test_demand_orders.py backend/tests/test_filemaker_client_token.py backend/tests/test_filemaker_odata_client.py -q
cd frontend
npm run build
```

截图自检：`artifacts/demand-orders-ui/`，列表与详情覆盖 1440、1068、390px × 亮暗主题。浏览器界面检查重放实际 API 返回数据；空状态和错误状态用受控响应验证，不向应用代码添加模拟数据。

## 2026-09-23 上线

已随 git `2d13b34` 发布：镜像 `starrc-backend:20260923-2d13b34`、`starrc-frontend:20260923-2d13b34`（同批含侧边栏折叠芯片与 logo/favicon 配色修正 `71fb534`）。发布目录 `/opt/starrc-filemaker/releases/20260923-2d13b34`，前版覆盖配置与源码快照在 `backup/`。发布前 22 项后端测试（需求单、Data API 凭证、OData 客户端）、前端生产构建与 5 组回归检查全部通过。上线后公网 index.html 与 `App-DeycFbzM.js` 和本地构建逐字节一致，内外网 healthz 正常，匿名访问 `/api/demand-orders` 返回 401。
