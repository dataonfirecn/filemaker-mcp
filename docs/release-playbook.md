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
| 服务器项目目录 | `/opt/starrc-filemaker/current`（git 工作副本，同一个仓库/分支） |
| Compose 项目名 | `starrc-filemaker` |
| Compose 文件 | `deploy/starrc/docker-compose.yml`（如有覆盖文件如 `product-master.release.yml` 一并 `-f` 带上，不要漏掉导致静默回退） |
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

# 改了 backend/ 就跑：
cd backend && python -m pytest -q    # 必须全部通过
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

一次 SSH 会话内按顺序执行完，不要拆成多次来回：

```bash
ssh root@101.35.198.171 bash -s <<'EOF'
set -euo pipefail
cd /opt/starrc-filemaker/current

COMMIT="<上面记下的短 hash>"
TAG="$(date +%Y%m%d)-${COMMIT}"
RELDIR="/opt/starrc-filemaker/releases/${TAG}/backup"
mkdir -p "$RELDIR"

# 备份：当前 commit、当前 compose 覆盖文件、.env
git rev-parse HEAD > "$RELDIR/previous-commit.txt"
cp deploy/starrc/*.release.yml "$RELDIR/" 2>/dev/null || true
cp .env "$RELDIR/.env.bak"

# 记录部署前容器 ID，用于事后核对「没改的服务没被重建」
docker ps --format '{{.Names}} {{.ID}}' > "$RELDIR/containers-before.txt"

# 同步代码到目标提交
git fetch origin main
git checkout "$COMMIT"

# 只重建改动的服务（示例：frontend；backend 改了就把 frontend 换成 backend，
# 两个都改就都列上，不加 --no-deps 也行，多起一次 postgres 健康检查不影响）
docker compose --env-file .env -p starrc-filemaker \
  -f deploy/starrc/docker-compose.yml config --quiet
docker compose --env-file .env -p starrc-filemaker \
  -f deploy/starrc/docker-compose.yml up -d --build --no-deps frontend

docker ps --format '{{.Names}} {{.ID}} {{.Status}}'
curl -fsS http://127.0.0.1:18001/healthz
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

```bash
ssh root@101.35.198.171 bash -s <<'EOF'
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/<TAG>/backup/previous-release.yml ./*.release.yml 2>/dev/null || true
cd /opt/starrc-filemaker/current
git checkout "$(cat /opt/starrc-filemaker/releases/<TAG>/backup/previous-commit.txt)"
docker compose --env-file .env -p starrc-filemaker \
  -f deploy/starrc/docker-compose.yml up -d --no-deps --no-build frontend
curl -fsS http://127.0.0.1:18001/healthz
EOF
```

## 用户触发这套流程时应该说的话

一句话就够，例如：「推送并部署上线」「push 上线」「发布到生产」。收到这类话、
且没有指定要跳过某一步时，视为完整授权执行 1-6 步；只有第 1 步判断出涉及数据库
迁移/FileMaker 布局变更时才需要先问一句。
