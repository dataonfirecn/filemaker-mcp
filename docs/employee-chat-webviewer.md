# StarRC 员工对话 WebViewer

## 目标

- 员工从 FileMaker 直接进入对话窗口，不再次输入账号或密码。
- 后端只信任 FileMaker 生成的 HMAC-SHA256 签名上下文。
- 每一问都记录 FileMaker 登录账号、显示名称、会话、原问题、解释后的问题、查询计划、答案、命中数量、耗时、告警和错误。
- 后台自动归一化有效问题，过滤“你好、测试”等无业务意义输入，生成高频问题统计。
- 普通浏览器访问 StarRC 时仍保留内部员工账号密码登录，不能伪装 FileMaker 用户。

## FileMaker 布局

新建一个独立布局：

- 布局名：`StarRC｜员工对话`
- WebViewer 对象名：`wv_starrc_employee_chat`
- 建议尺寸：以 `640 × 658 pt` 作为最小设计尺寸铺满布局正文，四边锚点全部锁定
- 建议启用：允许 JavaScript 在 Web Viewer 中执行 FileMaker 脚本

员工对话页的最外层 Grid 必须显式使用单列全宽布局，并重置旧首页样式遗留的
`justify-content: flex-start`；否则 WebViewer 已经变宽时，网页对话区仍会按内容宽度停在左侧。

WebViewer URL 计算式：

```filemaker
StarRC_WebViewerURL ( "?page=chat" )
```

`StarRC_WebViewerURL` 是 StarRC 现有的统一签名函数。它必须在签名载荷中写入：

```filemaker
[ "operator.account" ; Get ( AccountName ) ; JSONString ] ;
[ "operator.name" ; Get ( UserName ) ; JSONString ] ;
[ "operator.privilege" ; Get ( AccountPrivilegeSetName ) ; JSONString ] ;
[ "operator.persistentId" ; Get ( PersistentID ) ; JSONString ]
```

服务器 `WEBVIEWER_CONTEXT_SECRET` 必须与该函数中的签名密钥一致。密钥只能保存在
FileMaker 自定义函数和服务器环境变量中，不能写在普通 URL 参数或前端源码中。

## 打开脚本

可在 FileMaker 导航按钮绑定：

```filemaker
新建窗口 [
  风格: 浮动文档 ;
  名称: "StarRC 员工对话" ;
  使用布局: "StarRC｜员工对话"
]
```

如果希望直接在现有主界面页签中显示，也可以把同一 WebViewer 对象放进页签；URL
仍保持 `StarRC_WebViewerURL ( "?page=chat" )`。

FileMaker 已经完成账号认证，因此网页不会再要求员工输入密码。后端验证 `ctx` / `sig`
后签发短期 WebViewer 会话，并把 `operator.account` 和 `operator.name` 写入每条问答记录。

## 对话与后台分析

对话接口：

```text
POST /api/natural-query
```

原始问答记录保存在持久化 `app.db` 的：

```text
natural_query_conversations
```

关键字段包括：

- `session_id`
- `operator_account`
- `operator_name`
- `operator_privilege`
- `prompt`
- `interpreted_prompt`
- `layout` / `domain` / `intent`
- `query_json` / `filters_json`
- `answer`
- `found_count` / `returned_count`
- `duration_ms`
- `status` / `error_message`
- `created_at`

后台分析结果保存在：

```text
natural_query_question_analytics
```

StarRC 生产部署启用 `NATURAL_QUERY_ANALYTICS_WORKER_ENABLED=true`。新问答写入后会唤醒
后台 worker，不阻塞员工当前查询。聚合结果可通过现有接口查看：

```text
GET /api/natural-query/analytics/top-questions
```

## 验收

1. 用两个不同 FileMaker 账号分别打开 `StarRC｜员工对话`，均不出现网页登录表单。
2. 页头显示当前 FileMaker 用户。
3. 连续提出两到三个问题，页面保留完整的本次多轮对话。
4. 在 `natural_query_conversations` 中确认每条记录的 `operator_account` 与提问员工一致。
5. 等待后台 worker 处理后，在 `natural_query_question_analytics` 或高频问题接口中确认归一化记录。
6. 直接复制一个没有有效 `ctx` / `sig` 的 URL 到普通浏览器，页面必须要求内部员工登录。
