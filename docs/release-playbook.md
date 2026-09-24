# 标准发布流程：GitHub 推送 + 服务器上线

给本仓库的 AI 编程助手（Claude、Codex、Cursor、本地 Qwen 等）用。用户说「推送」「部署」
「上线」「发布到生产」一类的话，且没有额外说明时，按本文件一次性执行完 1-6 步，
不要逐步向用户确认；遇到与本文件假设不符的情况（容器名不对、健康检查失败、
涉及数据库结构变更等）才停下来问。

## 0. 固定事实（无需每次核实）

| 项 | 值 |
|---|---|
| GitHub 仓库 | `https://github.com/dataonfirecn/filemaker-mcp.git`，分支 `main` |
| 服务器 | `root@101.35.198.171`（SSH 密钥免密登录，见 `SERVER_CREDENTIALS.md`） |
| 服务器项目目录 | `/opt/starrc-filemaker/current` 是指向 `releases/<...>/` 快照的**符号链接，不是 git 工作副本（无 `.git`）**；代码不走 git 同步，每次发布新建 `releases/<日期>-<短hash>/` 目录并 scp 上传源码与构建产物 |
| Compose 项目名 | `starrc-filemaker` |
| Compose 文件 | 在 `/opt/starrc-filemaker/current/deploy/starrc/` 目录下运行：`docker compose --env-file ../../.env -p starrc-filemaker -f docker-compose.yml -f product-master.release.yml ...`。`product-master.release.yml` 覆盖文件就放在同目录，固定运行中的镜像 tag 与 product-master 环境变量，**不能漏** |
| 镜像构建方式 | 增量镜像：`FROM` 当前运行中的镜像，只 `COPY` 改动路径（backend → `/app/app`、`/app/config`、`/app/scripts`；frontend → `/usr/share/nginx/html`）；tag 为 `starrc-backend:<日期>-<短hash>` / `starrc-frontend:<日期>-<短hash>`。只 `COPY` 覆盖，删除文件不会从镜像里消失，删文件的功能改动要整层重建或手动清理 |
| 内部健康检查 | backend `http://127.0.0.1:18001/healthz`；frontend 容器监听 `127.0.0.1:18000` |
| 公网健康检查 | `https://starrc.dataonfire.cn/healthz` |
| 容器 | `starrc-backend`、`starrc-frontend`、`starrc-postgres` |
| 密钥/第三方凭证 | 只在 `SERVER_CREDENTIALS.md` 和服务器 `.env` 里，不要写进 commit、发布记录或对话 |

不确定的地方（每次发布用一条命令核实，别硬编）：`docker images` 里 frontend/backend
构建出来的镜像实际名字，以 `docker images | grep starrc` 的真实结果为准，不要假设。

## 1. 判断改动范围

- 只改了 `frontend/` → 只重建 `frontend` 服务，`backend`/`postgres` 容器 ID 部署前后必须不变。
- 只改了 `backend/` → 只重建 `backend`。
- 两者都改 → 都重建，分别验证。
- 涉及 `backend/scripts/` 里的迁移脚本、FileMaker 布局变更、或数据库结构变化 →
  先停下来跟用户确认迁移范围和是否需要生产数据备份，不要自动执行迁移。

## 2. 本地预检（Mac，`~/Documents/Vibe/StarRC-FileMaker`）

```bash
# 改了 frontend/ 就跑：
npm --prefix frontend run build      # tsc + vite，必须无错通过

# 改了 backend/ 就跑（在**仓库根目录**运行，测试用相对路径读 backend/config/…）：
# 首次需要建环境（requirements.txt 已含 pytest）：
cd backend && uv venv .venv --python 3.12 && uv pip install -r requirements.txt --python .venv/bin/python
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests -q   # 必须全部通过
```

改了 `frontend/` 时，对照 `docs/ui-design-rules.md`（token、字号 ≥12px、字重
400/500/600、无 `!important`）自检一遍，不合规先改完再进下一步。

## 3. 提交并推送 GitHub

```bash
git add -A
git commit -m "<type>: <一句话摘要>"
git push origin main
```

记下这次提交的短 hash（如 `c4245f6`），后面的服务器目录名、镜像 tag、发布记录都用它，
保持可追溯。

## 4. 部署到服务器

先在本地（工作树干净、提交已推送）打好包并上传：

```bash
cd <仓库根目录>
tar czf /tmp/backend-src.tar.gz backend/app backend/config backend/scripts
tar czf /tmp/frontend-dist.tar.gz -C frontend dist
tar czf /tmp/pm-src-<短hash>.tar.gz backend/app backend/config backend/scripts frontend/src
scp /tmp/backend-src.tar.gz /tmp/frontend-dist.tar.gz /tmp/pm-src-<短hash>.tar.gz root@101.35.198.171:/tmp/
```

再一次 SSH 会话内按顺序执行完。注意：单条命令超过 ~30 秒（docker build / up）容易被客户端
超时掐断，脚本设计成幂等、可安全重跑；被掐断后先 `docker ps` 看状态再补跑，不要假设完成：

```bash
ssh root@101.35.198.171 bash -s <<'EOF'
set -euo pipefail
TAG="<日期>-<短hash>"
RELDIR=/opt/starrc-filemaker/releases/${TAG}
PREV_BACKEND="<docker ps 里当前 backend 镜像 tag>"
PREV_FRONTEND="<docker ps 里当前 frontend 镜像 tag>"
mkdir -p "$RELDIR/backup" "$RELDIR/build"

# 备份：当前覆盖文件、.env、当前运行中的源码（取自上一个发布目录 build/）
cp /opt/starrc-filemaker/current/deploy/starrc/product-master.release.yml "$RELDIR/backup/previous-release.yml"
cp /opt/starrc-filemaker/.env "$RELDIR/backup/.env.bak"
tar czf "$RELDIR/backup/previous-src.tar.gz" -C <上一个发布目录>/build .

# 新构建目录
tar xzf /tmp/backend-src.tar.gz -C "$RELDIR/build"
tar xzf /tmp/frontend-dist.tar.gz -C "$RELDIR/build"
cp /tmp/pm-src-<短hash>.tar.gz "$RELDIR/build/"
printf 'FROM starrc-backend:%s\nCOPY backend/app /app/app\nCOPY backend/config /app/config\nCOPY backend/scripts /app/scripts\n' "$PREV_BACKEND" > "$RELDIR/build/Dockerfile.backend"
printf 'FROM starrc-frontend:%s\nCOPY dist /usr/share/nginx/html\n' "$PREV_FRONTEND" > "$RELDIR/build/Dockerfile.frontend"

# release.yml：沿用当前 env 块，只替换改动侧的镜像 tag（只改一边就只 sed 一边）
sed -e "s|image: starrc-backend:[0-9A-Za-z.-]*|image: starrc-backend:${TAG}|" \
    -e "s|image: starrc-frontend:[0-9A-Za-z.-]*|image: starrc-frontend:${TAG}|" \
    /opt/starrc-filemaker/current/deploy/starrc/product-master.release.yml > "$RELDIR/release.yml"

# 部署前容器 ID，用于事后核对「没改的服务没被重建」
docker ps --format '{{.Names}} {{.ID}} {{.Image}}' | grep '^starrc-' > "$RELDIR/containers-before.txt"

# 只构建改动的服务（两个都改就都构建）
cd "$RELDIR/build"
docker build -t "starrc-backend:${TAG}" -f Dockerfile.backend .
docker build -t "starrc-frontend:${TAG}" -f Dockerfile.frontend .

# 部署：覆盖文件换上新 release.yml，只起改动的服务
cd /opt/starrc-filemaker/current/deploy/starrc
cp "$RELDIR/release.yml" product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker -f docker-compose.yml -f product-master.release.yml up -d --no-deps backend frontend

docker ps --format '{{.Names}} {{.ID}} {{.Image}} {{.Status}}' | grep '^starrc-' | tee "$RELDIR/containers.txt"
curl -fsS http://127.0.0.1:18001/healthz | tee "$RELDIR/health.json"
curl -fsS https://starrc.dataonfire.cn/healthz
EOF
```

部署后核对：没有主动重建的服务，容器 ID 必须和 `containers-before.txt` 里一致；
两个 `healthz` 都要返回正常。任何一项不符，先停下来排查，不要接着写发布记录。

## 5. 前端一致性核验（前端改动必做，后端改动可跳过）

本地构建产物和线上逐字节比对，确认部署的就是刚推送的代码：

```bash
sha256sum frontend/dist/index.html
ssh root@101.35.198.171 "curl -s https://starrc.dataonfire.cn/ | sha256sum"
```

两边 hash 不一致就说明部署的不是预期版本，回到第 4 步排查，不要直接写发布记录。

## 6. 记录发布

参照 `docs/` 下已有的发布记录（如 `docs/product-browser-20260922.md` 末尾「标准镜像发布」
一节的格式）在对应文档追加一节，或新建 `docs/<主题>-release-<日期>.md`，写清楚：

- 这次发布范围（只前端/只后端/两者），继承自哪个旧镜像
- 容器 ID 变化（没重建的服务应保持不变，写出来做证据）
- 验证结果（构建通过、健康检查、SHA-256 一致）
- 回滚镜像 tag 或回滚命令

写完 `git add -A && git commit -m "docs: record ..." && git push origin main`。

## 7. 回滚

旧镜像都留在镜像仓库里，`backup/previous-release.yml` 指向它们；回滚就是把覆盖文件换回去
再 `up` 一次（列出本次发布重建过的服务）：

```bash
ssh root@101.35.198.171 bash -s <<'EOF'
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/<TAG>/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker \
  -f docker-compose.yml -f product-master.release.yml up -d --no-deps backend frontend
docker ps --format '{{.Names}} {{.ID}} {{.Image}}' | grep '^starrc-'
curl -fsS http://127.0.0.1:18001/healthz
curl -fsS https://starrc.dataonfire.cn/healthz
EOF
```

回滚后在对应发布文档补一行「已于 <时间> 回滚到 <旧 tag>」，并推送。

## 用户触发这套流程时应该说的话

一句话就够，例如：「推送并部署上线」「push 上线」「发布到生产」。收到这类话、
且没有指定要跳过某一步时，视为完整授权执行 1-6 步；只有第 1 步判断出涉及数据库
迁移/FileMaker 布局变更时才需要先问一句。

## 上线记录（2026-09-24，`6b1ea5d`，仅文档）

- 范围：仅 `AGENTS.md`（路由到本 playbook）+ 本文件新增，无 `frontend/` / `backend/`
  改动 → 按第 1 步不重建任何服务。提交 `6b1ea5d` 已推送 `origin/main`。
- 容器 ID 部署前后不变（未执行 `up`）：frontend `bf07a84053cf`
  （`starrc-frontend:20260924-0eaa74d`）、backend `5dc3b3d24e16`
  （`starrc-backend:20260923-f8e6fc1`）、postgres `f196c32c514b`。
- 验证：内网 `http://127.0.0.1:18001/healthz` 与公网 `https://starrc.dataonfire.cn/healthz`
  均 `ok: true`。
- 服务器审计目录：`/opt/starrc-filemaker/releases/20260924-6b1ea5d/`
  （`containers.txt`、`health.json`、`health.txt`、`note.txt`、`backup/previous-release.yml`）。
- 回滚：不适用（无镜像、无容器变化）。
- 与本 playbook 假设不符：第 0 节假设 `/opt/starrc-filemaker/current` 是 git 工作副本，
  实际服务器为 `releases/` 快照目录（`current -> releases/20260913-pda-physical-auth-r2`，
  无 `.git`），第 4 步的 `git fetch/checkout` 无法照做。本次仅文档改动故跳过；
  后续含代码的发布仍按既有发布模式（`releases/<date>-<hash>/` 目录 + 增量镜像 +
  `product-master.release.yml` 覆盖文件）执行，并同步修正本文件第 0/4 节。
  —— 第 0/2/4/7 节已于 `062cb01` 发布时按实际模式修正完毕（2026-09-24）。

## 上线记录（2026-09-24，`062cb01`，前端 + 后端）

- 范围：订单列表（`GET /api/orders` + `OrderListPage`，共享 `DataGrid`、ui 组件库
  新增 `IconButton`）。提交 `062cb01` 已推送 `origin/main`。细节见
  `docs/orders-list.md`「标准镜像发布」一节。
- 镜像：`starrc-backend:20260924-062cb01`（继承 `20260923-f8e6fc1`）、
  `starrc-frontend:20260924-062cb01`（继承 `20260924-0eaa74d`）。
- 容器 ID：backend `5dc3b3d24e16` → `e72b9a0c09e8`；frontend `bf07a84053cf` →
  `51334793a0c2`；postgres `f196c32c514b` 保持不变。
- 验证：后端 389 过 / 54 跳过（仓库根目录运行）；前端 tsc + vite 通过；内网 + 公网
  `healthz` 均 `ok: true`；`index.html` 与两个入口 JS 的 SHA-256 与本地构建逐字节一致。
- 服务器审计目录：`/opt/starrc-filemaker/releases/20260924-062cb01/`
  （`backup/`、`build/`、`release.yml`、`containers-before.txt`、`containers.txt`、`health.json`）。
- 回滚：恢复 `backup/previous-release.yml` 后 `up -d --no-deps backend frontend`
  （见该文档「回退」一节）。
- 过程注记：首次部署 SSH 会话在 `compose up` 中途超时，frontend 停在「Created」；
  重跑同一条幂等 `up -d` 恢复。第 4 步已补充超时/重跑注意事项。

## 上线记录（2026-09-24，`cf8034c`，仅前端）

- 范围：导航首页「最近运行」趋势图（recharts 堆叠柱状图 `ReportTrendChart`）+ 移除首页
  「浏览器登录工作台」导航块 + 顶栏用户菜单 / 侧栏设计 token 清理。提交 `cf8034c` 已推送
  `origin/main`。细节见 `docs/dashboard-report-trend-release-20260924.md`。
- 镜像：`starrc-frontend:20260924-cf8034c`（继承 `20260924-fc12b6f`）；backend 继续
  `20260924-dms-web-catalog-v2`（未改动）。
- 容器 ID：frontend `1cd629fc5a3c` → `93efe14a387a`；backend `8fb64e9e6055`、
  postgres `f196c32c514b` 保持不变。
- 验证：前端 tsc + vite 通过；内网 + 公网 `healthz` 均 `ok: true`；`index.html`
  SHA-256 与本地构建一致（`cc8a0eec…`）。
- 服务器审计目录：`/opt/starrc-filemaker/releases/20260924-cf8034c/`。
- 回滚：恢复 `backup/previous-release.yml` 后 `up -d --no-deps frontend`。

## 上线记录（2026-09-25，`412cfa4`，仅前端）

- 范围：产品编辑页 Debug 下拉（`ProductDebug` 新组件 + `ProductMasterPage` 接入
  `operator` 会话信息）。提交 `412cfa4` 已推送 `origin/main`。细节见
  `docs/product-master-filemaker-entry.md`「产品编辑 Debug 下拉」一节。
- 镜像：`starrc-frontend:20260925-412cfa4`（继承 `20260924-4ad9fdd`）；backend 继续
  `20260924-98afc25`（未改动）。
- 容器 ID：frontend `7f9c518d9bb9` → `05b871dad599`；backend `a4fd3392dca5`、
  postgres `f196c32c514b` 保持不变。
- 验证：前端 tsc + vite 通过；内网 + 公网 `healthz` 均 `ok: true`；`index.html`
  SHA-256 与本地构建一致（`cc8a0eec…`）。
- 服务器审计目录：`/opt/starrc-filemaker/releases/20260925-412cfa4/`。
- 回滚：恢复 `backup/previous-release.yml` 后 `up -d --no-deps frontend`。
