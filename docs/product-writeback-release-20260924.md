# 产品回写开启 + 售价记录新建 发布记录（2026-09-24，`12aff38`）

## 范围

前端 + 后端都改，两个服务都重建。

- **回写开启**：`product_master_schema.json` 登记 `nativeEditingLocked=true`、
  `uuidCreateVerified=true`（描述 FileMaker 侧实际状态，按用户确认登记）；
  权限模型补上 `canEditProducts` / `canEditProductPrices` / `canManageProductSync`
  三个缺省 False 的字段（以前不在模型里，管理页读不到也存不了）；
  权限集配置补 `[Full Access]`（英文名）条目。
- **售价记录首次新建**：Web 新建的产品（`pm_revision` v1 origin=web）无需导入快照
  即可填售价；首次保存时 `create_price_record` 在 FileMaker「產品售價」新建记录，
  持久化意图 → 创建 → 回读核对 → 从原生布局验证关联后才算成功；
  编号重复 / 多条匹配 / 回读不一致均拒绝。
- **数字规范化修复**：`Decimal.normalize()` 会把 `500` 变成 `5E+2`，
  改为 `format(..., 'f')` 定点写法。
- **前端**：编辑页「报价信息」独立 tab（只读浏览页保持合并布局）；
  价格字段权限提示条（无查看价格 / 无编辑价格 / 可新建售价记录三种状态）；
  新组件 `ProductSelect`（长列表带搜索、键盘操作、portal 弹层）替换原生 select；
  系统编号复制按钮与输入框连体样式；顶栏用户菜单加展开箭头；
  `styles.css` 字重 600 → `var(--weight-medium)`。
- 操作清单见 `docs/product-writeback-enable-20260924.md`（服务器 env 开关、
  专用账号权限、小范围测试范围、回退方式）。

## 镜像

- `starrc-backend:20260924-12aff38`（继承 `20260924-4b66594`）
- `starrc-frontend:20260924-12aff38`（继承 `20260924-4b66594`）

## 容器 ID 变化

| 容器 | 部署前 | 部署后 |
|---|---|---|
| starrc-backend | `e9a5288cc73b` | `832cc121f108`（重建） |
| starrc-frontend | `8d04a2f896b9` | `02e3944a7267`（重建） |
| starrc-postgres | `f196c32c514b` | `f196c32c514b`（不变） |

## 验证

- 后端：`pytest backend/tests -q` → 401 passed, 60 skipped（仓库根目录运行）。
- 前端：`npm --prefix frontend run build`（tsc + vite）通过。
- 健康检查：内网 `http://127.0.0.1:18001/healthz` 与公网
  `https://starrc.dataonfire.cn/healthz` 均 `ok: true`。
- 前端一致性：`index.html` SHA-256 `f8b6ec3f…a16166`、入口
  `assets/index-CQyoQTL7.js` SHA-256 `2199546f…d50bcf7`，本地构建与线上逐字节一致。

## 服务器审计目录

`/opt/starrc-filemaker/releases/20260924-12aff38/`
（`backup/previous-release.yml`、`backup/.env.bak`、`backup/previous-src.tar.gz`、
`build/`、`release.yml`、`containers-before.txt`、`containers.txt`、`health.json`、
`build-backend.log`、`build-frontend.log`）

## 回滚

```bash
ssh root@101.35.198.171 bash -s <<'EOF'
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/20260924-12aff38/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker \
  -f docker-compose.yml -f product-master.release.yml up -d --no-deps backend frontend
docker ps --format '{{.Names}} {{.ID}} {{.Image}}' | grep '^starrc-'
curl -fsS http://127.0.0.1:18001/healthz
curl -fsS https://starrc.dataonfire.cn/healthz
EOF
```

回滚镜像 tag：`starrc-backend:20260924-4b66594` / `starrc-frontend:20260924-4b66594`。

## 注意

- 回写是否真正生效取决于服务器 `.env` 的 `PRODUCT_MASTER_WRITE_ENABLED` 等开关
  与专用账号配置（见 `docs/product-writeback-enable-20260924.md`），本次发布只部署
  代码，未改动服务器 env。
- 小范围测试：只给测试账号勾「编辑产品」「编辑产品价格」，其他账号保存会被拒绝。
