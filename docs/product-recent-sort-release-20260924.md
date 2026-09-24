# 产品主数据「最近创建」排序 + 资产分区重构发布（2026-09-24，`1886287`）

## 范围

前端 + 后端。

- **后端**（`backend/app/api/business_products.py`、`backend/app/models/business_products.py`）：
  产品列表新增 `sort=recent` 参数（「最近创建」排序）。Postgres 路径用
  `RECENT_CREATED_ORDER`（优先 FileMaker 建立日期，兼容 MM/DD/YYYY 与 ISO 两种
  写法，按上海时间理解；Web 端新建产品兜底取第一版保存时间；无建立时间的排最后）；
  FileMaker 路径按 `created_at` 倒序，布局没有该字段时退回默认顺序不让列表失败。
- **前端**：
  - `ProductMasterPage` 重构：新增 `ProductAssetSections`（主图 / 规格图 / 包装
    分区组件，`packSlots` 位置贴紧逻辑）、`formatStamp` 时间戳工具、日期控件
    MM/DD/YYYY → YYYY-MM-DD 转换、拖拽上传拦截（防止浏览器直接打开文件丢失
    编辑内容）。
  - `BusinessProductsPage` / `App.tsx`：产品列表新增排序切换（默认 / 最近创建）。
  - `productMasterLayout.ts`：新增 `specFieldOrder`、`packagingFieldOrder`、
    `derivedValue` 等布局定义。
  - 样式：`ProductMasterPage.css` 精简，新增 `ProductAssetSections.css`。
- **测试**：`backend/tests/test_product_master.py` 补排序用例。
- **文档**：新增 `docs/product-quotation-field-audit-20260924.md`（报价字段审计）。

## 镜像

- `starrc-backend:20260924-1886287`（继承 `20260924-2b96da6`）
- `starrc-frontend:20260924-1886287`（继承 `20260924-2b96da6`）

## 容器 ID

| 容器 | 部署前 | 部署后 |
|---|---|---|
| starrc-backend | `d80703e643d6` | `a9aec721838c` |
| starrc-frontend | `8d598bb559a4` | `991dcc069f6d` |
| starrc-postgres | `f196c32c514b` | `f196c32c514b`（未重建） |

## 验证

- 后端测试：396 过 / 55 跳过（仓库根目录运行）。
- 前端：tsc + vite 构建通过。
- 健康检查：内网 `http://127.0.0.1:18001/healthz` 与公网
  `https://starrc.dataonfire.cn/healthz` 均 `ok: true`。
- SHA-256 一致性（本地 `frontend/dist` vs 线上）：
  - `index.html`：`131b8729ddf84c6547d78ece05b429e9dbf01fe5f1c2b73e4c7d7a9f1cbbc409`
  - `assets/index-Cd036zTd.js`：`394f76ffac51dfacb470070c0e9b8fe81f1f4123183657ff6b5b02a3bf83fb0e`
  - `assets/App-aPDDJpZS.js`：`78273662a9aad7235603c1b62eaca6661229ce12d944e1072d603142383661e3`

## 服务器审计目录

`/opt/starrc-filemaker/releases/20260924-1886287/`（`release.yml`、
`containers-before.txt`、`containers.txt`、`health.json`、
`backup/previous-release.yml`、`backup/.env.bak`、
`backup/previous-src-backend.tar.gz`、`backup/previous-src-frontend.tar.gz`）。

## 回滚

```bash
ssh root@101.35.198.171 bash -s <<'EOF'
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/20260924-1886287/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker \
  -f docker-compose.yml -f product-master.release.yml up -d --no-deps backend frontend
docker ps --format '{{.Names}} {{.ID}} {{.Image}}' | grep '^starrc-'
curl -fsS http://127.0.0.1:18001/healthz
curl -fsS https://starrc.dataonfire.cn/healthz
EOF
```

回滚目标镜像：`starrc-backend:20260924-2b96da6`、
`starrc-frontend:20260924-2b96da6`。
