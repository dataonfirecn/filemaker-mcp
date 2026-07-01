# FileMaker API_Test 测试表、布局和脚本

这份内容用于快速建立后端 MES callback 的 FileMaker 测试接收端。

后端默认会调用：

```text
Layout: MES_FILEMAKER_LAYOUT
Script: MES_FILEMAKER_SCRIPT_NAME
```

建议 `.env` 先这样配置：

```bash
MES_FILEMAKER_LAYOUT=API_Test
MES_FILEMAKER_SCRIPT_NAME=MES_UpdateWorkOrder_Test
```

后端传入 FileMaker Script 的参数格式：

```json
{
  "source": "mes",
  "eventId": "demo-001",
  "payload": {
    "eventId": "demo-001",
    "workOrderNo": "WO-001",
    "status": "finished",
    "message": "test callback"
  }
}
```

---

## 1. 数据表

FileMaker 新建表：

```text
表名: API_Test
```

字段清单：

```csv
字段名,类型,说明
id,文本,业务 UUID；自动输入计算 Get(UUID)
eventId,文本,MES callback 事件 ID；建议唯一
source,文本,callback 来源，例如 mes
workOrderNo,文本,工单号
mesStatus,文本,MES 状态
message,文本,MES 消息或备注
payloadJson,文本,后端传入 payload JSON
rawScriptParameter,文本,完整脚本参数 JSON
filemakerResultJson,文本,脚本返回 JSON，可用于调试
lastError,文本,错误信息
processedAt,时间戳,最后处理时间
createdAt,时间戳,创建时间；自动输入创建时间戳
updatedAt,时间戳,修改时间；自动输入修改时间戳
```

推荐字段设置：

```text
id
  类型: 文本
  自动输入计算: Get ( UUID )
  禁止替换现有值: 是

eventId
  类型: 文本
  验证: 唯一值
  验证: 非空值

createdAt
  类型: 时间戳
  自动输入: 创建时间戳

updatedAt
  类型: 时间戳
  自动输入: 修改时间戳
```

建议给 `eventId` 建索引，因为脚本会按这个字段查找重复 callback。

---

## 2. 布局

新建布局：

```text
布局名: API_Test
显示记录来自: API_Test
用途: 仅供 Data API / 后端脚本调用 / 调试
```

布局上放这些字段即可：

```text
API_Test::id
API_Test::eventId
API_Test::source
API_Test::workOrderNo
API_Test::mesStatus
API_Test::message
API_Test::payloadJson
API_Test::rawScriptParameter
API_Test::filemakerResultJson
API_Test::lastError
API_Test::processedAt
API_Test::createdAt
API_Test::updatedAt
```

Data API 使用的账号需要能访问这个布局、字段和下面的脚本。

---

## 3. 测试脚本

新建 FileMaker 脚本：

```text
MES_UpdateWorkOrder_Test
```

脚本步骤：

```text
Allow User Abort [ Off ]
Set Error Capture [ On ]
Freeze Window

Set Variable [ $param ; Value: Get ( ScriptParameter ) ]

If [ IsEmpty ( $param ) ]
    Set Variable [ $result ; Value:
        JSONSetElement ( "{}" ;
            [ "ok" ; False ; JSONBoolean ] ;
            [ "error" ; "Missing script parameter" ; JSONString ]
        )
    ]
    Exit Script [ Text Result: $result ]
End If

Set Variable [ $source ; Value: JSONGetElement ( $param ; "source" ) ]
Set Variable [ $eventId ; Value: JSONGetElement ( $param ; "eventId" ) ]
Set Variable [ $payload ; Value: JSONGetElement ( $param ; "payload" ) ]

If [ IsEmpty ( $eventId ) ]
    Set Variable [ $eventId ; Value: JSONGetElement ( $param ; "payload.eventId" ) ]
End If

If [ IsEmpty ( $eventId ) ]
    Set Variable [ $result ; Value:
        JSONSetElement ( "{}" ;
            [ "ok" ; False ; JSONBoolean ] ;
            [ "error" ; "Missing eventId" ; JSONString ] ;
            [ "rawScriptParameter" ; $param ; JSONString ]
        )
    ]
    Exit Script [ Text Result: $result ]
End If

Set Variable [ $workOrderNo ; Value: JSONGetElement ( $param ; "payload.workOrderNo" ) ]
Set Variable [ $mesStatus ; Value: JSONGetElement ( $param ; "payload.status" ) ]
Set Variable [ $message ; Value: JSONGetElement ( $param ; "payload.message" ) ]

Go to Layout [ “API_Test” (API_Test) ]
Enter Find Mode [ Pause: Off ]
Set Field [ API_Test::eventId ; $eventId ]
Perform Find [ ]

If [ Get ( LastError ) = 401 ]
    New Record/Request
    Set Field [ API_Test::id ; Get ( UUID ) ]
    Set Field [ API_Test::eventId ; $eventId ]
    Set Field [ API_Test::createdAt ; Get ( CurrentTimestamp ) ]
Else If [ Get ( LastError ) ≠ 0 ]
    Set Variable [ $error ; Value: "Find failed. FileMaker error: " & Get ( LastError ) ]
    Set Variable [ $result ; Value:
        JSONSetElement ( "{}" ;
            [ "ok" ; False ; JSONBoolean ] ;
            [ "eventId" ; $eventId ; JSONString ] ;
            [ "error" ; $error ; JSONString ]
        )
    ]
    Exit Script [ Text Result: $result ]
Else
    Go to Record/Request/Page [ First ]
End If

Set Field [ API_Test::source ; $source ]
Set Field [ API_Test::workOrderNo ; $workOrderNo ]
Set Field [ API_Test::mesStatus ; $mesStatus ]
Set Field [ API_Test::message ; $message ]
Set Field [ API_Test::payloadJson ; JSONFormatElements ( $payload ) ]
Set Field [ API_Test::rawScriptParameter ; JSONFormatElements ( $param ) ]
Set Field [ API_Test::lastError ; "" ]
Set Field [ API_Test::processedAt ; Get ( CurrentTimestamp ) ]
Set Field [ API_Test::updatedAt ; Get ( CurrentTimestamp ) ]

Commit Records/Requests [ With dialog: Off ]

If [ Get ( LastError ) ≠ 0 ]
    Set Field [ API_Test::lastError ; "Commit failed. FileMaker error: " & Get ( LastError ) ]
    Set Variable [ $result ; Value:
        JSONSetElement ( "{}" ;
            [ "ok" ; False ; JSONBoolean ] ;
            [ "eventId" ; $eventId ; JSONString ] ;
            [ "error" ; API_Test::lastError ; JSONString ]
        )
    ]
    Exit Script [ Text Result: $result ]
End If

Set Variable [ $result ; Value:
    JSONSetElement ( "{}" ;
        [ "ok" ; True ; JSONBoolean ] ;
        [ "eventId" ; API_Test::eventId ; JSONString ] ;
        [ "recordId" ; Get ( RecordID ) ; JSONString ] ;
        [ "source" ; API_Test::source ; JSONString ] ;
        [ "workOrderNo" ; API_Test::workOrderNo ; JSONString ] ;
        [ "mesStatus" ; API_Test::mesStatus ; JSONString ] ;
        [ "processedAt" ; Get ( CurrentTimestamp ) ; JSONString ]
    )
]

Set Field [ API_Test::filemakerResultJson ; JSONFormatElements ( $result ) ]
Commit Records/Requests [ With dialog: Off ]

Exit Script [ Text Result: $result ]
```

---

## 4. 测试 callback

如果 `.env` 没有设置 `MES_CALLBACK_API_KEY`，可以直接测试：

```bash
curl -X POST http://localhost:8000/api/mes/callback \
  -H "Content-Type: application/json" \
  -d '{
    "eventId": "demo-001",
    "workOrderNo": "WO-001",
    "status": "finished",
    "message": "FileMaker callback test"
  }'
```

如果设置了 `MES_CALLBACK_API_KEY`：

```bash
curl -X POST http://localhost:8000/api/mes/callback \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{
    "eventId": "demo-001",
    "workOrderNo": "WO-001",
    "status": "finished",
    "message": "FileMaker callback test"
  }'
```

查看后端处理状态：

```bash
curl http://localhost:8000/api/mes/events
```

成功后，FileMaker `API_Test` 表里应出现或更新一条 `eventId = demo-001` 的记录。

---

## 5. 直接 Data API 显式操作测试

如果不想走默认脚本，也可以让 callback payload 显式指定 FileMaker 操作：

```json
{
  "eventId": "demo-002",
  "filemaker": {
    "operation": "run_script",
    "layout": "API_Test",
    "scriptName": "MES_UpdateWorkOrder_Test",
    "scriptParam": {
      "source": "mes",
      "eventId": "demo-002",
      "payload": {
        "eventId": "demo-002",
        "workOrderNo": "WO-002",
        "status": "finished",
        "message": "explicit run_script test"
      }
    }
  }
}
```

注意：默认 callback 模式下，后端已经会包装 `{ source, eventId, payload }`；显式 `run_script` 模式下，你自己传入的 `scriptParam` 会原样给脚本。
