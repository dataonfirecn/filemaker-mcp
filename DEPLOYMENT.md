# FileMaker MCP Server - 部署指南

本文档介绍如何在目标机器上安装和配置 FileMaker MCP Server。

## 目录

- [系统要求](#系统要求)
- [安装步骤](#安装步骤)
- [配置 AI 客户端](#配置-ai-客户端)
- [验证安装](#验证安装)
- [常见问题](#常见问题)

---

## 系统要求

### 服务端要求
- **Node.js**: 18.0 或更高版本
- **npm**: 8.0 或更高版本
- **操作系统**: Windows / macOS / Linux

### FileMaker 要求
- **FileMaker Server**: 18.0 或更高版本
- **FileMaker Data API**: 已启用
- **网络连接**: 客户端机器能访问 FileMaker Server

---

## 安装步骤

### 方式一：从 GitHub 克隆（推荐）

#### 1. 获取代码

```bash
# 克隆仓库
git clone https://github.com/dataonfirecn/filemaker-mcp.git
cd filemaker-mcp
```

或从 GitHub Releases 页面下载预编译的 ZIP 包。

#### 2. 安装依赖

```bash
npm install
```

#### 3. 编译项目

```bash
npm run build
```

编译完成后，`dist/` 目录会包含可执行文件。

#### 4. 验证安装

```bash
# 测试服务器启动
node dist/index.js
# 看到 "FileMaker MCP server running on stdio" 表示成功
# 按 Ctrl+C 退出
```

### 方式二：使用 npm 全局安装（开发中）

```bash
npm install -g filemaker-mcp-server
```

---

## 配置 AI 客户端

### Claude Desktop 配置

#### 1. 打开配置文件

**macOS**:
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

**Windows**:
```
%APPDATA%\Claude\claude_desktop_config.json
```

#### 2. 添加 MCP 服务器配置

```json
{
  "mcpServers": {
    "filemaker": {
      "command": "node",
      "args": [
        "/path/to/filemaker-mcp/dist/index.js"
      ],
      "env": {
        "FILEMAKER_HOST": "https://your-filemaker-server.com",
        "FILEMAKER_DATABASE": "YourDatabaseName",
        "FILEMAKER_USERNAME": "your_username",
        "FILEMAKER_PASSWORD": "your_password"
      }
    }
  }
}
```

#### 3. 重启 Claude Desktop

完全退出 Claude Desktop 并重新启动。

### Cline (VSCode 扩展) 配置

#### 1. 打开配置文件

**macOS**:
```
~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json
```

**Windows**:
```
%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json
```

#### 2. 添加配置

```json
{
  "mcpServers": {
    "filemaker": {
      "command": "node",
      "args": [
        "C:\\path\\to\\filemaker-mcp\\dist\\index.js"
      ],
      "env": {
        "FILEMAKER_HOST": "https://your-filemaker-server.com",
        "FILEMAKER_DATABASE": "YourDatabaseName",
        "FILEMAKER_USERNAME": "your_username",
        "FILEMAKER_PASSWORD": "your_password"
      }
    }
  }
}
```

#### 3. 重启 VSCode

### Cursor 配置

在 Cursor Settings 中搜索 "MCP"，添加：

```json
{
  "mcpServers": {
    "filemaker": {
      "command": "node",
      "args": ["/path/to/filemaker-mcp/dist/index.js"],
      "env": {
        "FILEMAKER_HOST": "https://your-filemaker-server.com",
        "FILEMAKER_DATABASE": "YourDatabaseName",
        "FILEMAKER_USERNAME": "your_username",
        "FILEMAKER_PASSWORD": "your_password"
      }
    }
  }
}
```

---

## 验证安装

### 1. 检查 MCP 服务器是否启动

在 AI 客户端中查看 MCP 服务器列表，应该能看到 "filemaker"。

### 2. 测试连接

在 AI 助手中输入：

```
请列出 FileMaker 数据库中所有可用的布局
```

如果返回布局列表，说明连接成功。

---

## 常见问题

### Q1: MCP 服务器无法启动

**检查**:
```bash
# 确认 Node.js 版本
node --version  # 应该 >= 18

# 确认项目已编译
ls dist/index.js

# 手动运行测试
node dist/index.js
```

### Q2: 认证失败

**可能原因**:
- FileMaker Data API 未启用
- 用户名/密码错误
- 数据库名称错误
- 网络连接问题

**解决**: 在 FileMaker Server Admin Console 中确认：
1. Data API 已启用
2. 用户有 Data API 访问权限
3. 使用正确的数据库文件名（不是显示名称）

### Q3: 连接超时

**检查**:
```bash
# 测试网络连接
curl https://your-filemaker-server.com/fmi/data/v2/databases/YourDB/layouts \
  -u username:password
```

**可能原因**:
- 防火墙阻止
- 需要使用 VPN
- 服务器地址或端口不正确

### Q4: 找不到配置文件

**手动创建**: 如果配置文件不存在，手动创建并添加内容。

### Q5: Windows 路径问题

Windows 路径需要使用双反斜杠或正斜杠：
```json
"args": ["C:\\Users\\YourName\\filemaker-mcp\\dist\\index.js"]
// 或
"args": ["C:/Users/YourName/filemaker-mcp/dist/index.js"]
```

---

## 环境变量说明

| 变量 | 说明 | 示例 |
|------|------|------|
| `FILEMAKER_HOST` | FileMaker Server 地址 | `https://fm.example.com` |
| `FILEMAKER_DATABASE` | 数据库名称 | `MyDatabase` |
| `FILEMAKER_USERNAME` | API 用户名 | `api_user` |
| `FILEMAKER_PASSWORD` | API 密码 | `secure_password` |

**注意**:
- `FILEMAKER_HOST` 需要包含协议 (`http://` 或 `https://`)
- 不要包含末尾斜杠
- 端口号如果非标准，需要包含在地址中

---

## 安全建议

1. **使用专用 API 账户**: 创建只拥有必要权限的 FileMaker 用户
2. **启用 HTTPS**: 生产环境务必使用 HTTPS
3. **定期更新密码**: 定期更换 API 密码
4. **限制访问**: 在 FileMaker Server 中限制 API 访问的 IP 地址
5. **保护配置文件**: 配置文件包含明文密码，注意文件权限

---

## 支持的 MCP 工具

| 工具名 | 功能 |
|--------|------|
| `fm_find_records` | 查询记录 |
| `fm_get_record` | 获取单条记录 |
| `fm_create_record` | 创建新记录 |
| `fm_update_record` | 更新记录 |
| `fm_delete_record` | 删除记录 |
| `fm_run_script` | 执行 FileMaker 脚本 |
| `fm_list_layouts` | 列出所有布局 |
| `fm_get_layout_fields` | 获取布局字段信息 |
