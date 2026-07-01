# API_Test 表结构

首选做法：直接在 FileMaker 的 `Manage Database > Tables` 标签页粘贴：

```text
00-api-test-table-with-fields.fmxmlsnippet.xml
```

这个片段会创建表和字段。
如果它只创建了空表，删除空表后试：

```text
00-api-test-table-with-fields-direct-fallback.fmxmlsnippet.xml
```

粘贴后核对：

```text
Table: API_Test
Table occurrence: API_Test
Layout: API_Test
Script: MES_UpdateWorkOrder_Test
```

字段清单：

```csv
field,type,notes
id,Text,UUID primary key; auto-enter Get ( UUID ); unique
eventId,Text,MES callback event id; unique and required
source,Text,callback source, usually mes
workOrderNo,Text,work order number
mesStatus,Text,MES status
message,Text,MES message or note
payloadJson,Text,formatted payload JSON
rawScriptParameter,Text,full script parameter JSON
filemakerResultJson,Text,script result JSON
lastError,Text,last script error text
processedAt,Timestamp,last processing timestamp
createdAt,Timestamp,creation timestamp
updatedAt,Timestamp,modification timestamp
```

脚本参数示例：

```json
{
  "source": "mes",
  "eventId": "demo-001",
  "payload": {
    "eventId": "demo-001",
    "workOrderNo": "WO-001",
    "status": "finished",
    "message": "FileMaker callback test"
  }
}
```

脚本行为：

- 如果 `eventId` 已存在，则更新该记录。
- 如果找不到 `eventId`，则新建记录。
- 脚本返回 JSON，后端可以从 FileMaker Data API 的 script result 中读取。
