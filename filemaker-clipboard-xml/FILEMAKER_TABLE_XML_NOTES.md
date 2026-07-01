# FileMaker 表剪贴板 XML 成功记录

记录日期：2026-07-01

本记录用于说明如何生成可以在 FileMaker 中直接粘贴并创建表和字段的 `fmxmlsnippet`。本次已验证成功的文件是：

- `00-api-test-table-with-fields.fmxmlsnippet.xml`

目标结果：

- 在 `File > Manage > Database... > Tables` 中粘贴后，直接创建 `API_Test` 表。
- 同时创建 `API_Test` 的 13 个字段。
- 不需要先手动创建表，也不需要再单独粘贴字段。

## 成功的关键结构

FileMaker 从真实表复制出来的 XML 结构是：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<fmxmlsnippet type="FMObjectList">
  <BaseTable comment="" name="API_Test">
    <Field id="1" dataType="Text" fieldType="Normal" name="id">
      <Comment>...</Comment>
      <AutoEnter ...>
        ...
      </AutoEnter>
      <Validation ...>
        ...
      </Validation>
      <Storage .../>
      <Annotation>
        <Text/>
      </Annotation>
      <DisplayNames enable="False"/>
    </Field>
  </BaseTable>
</fmxmlsnippet>
```

关键点：

- `Field` 必须直接放在 `BaseTable` 下面。
- 不要使用 `FieldCatalog` 包住字段。
- `BaseTable` 使用 `comment="" name="API_Test"`，不需要 `id`。
- 字段属性使用 `dataType` 和 `fieldType`，不是 `datatype` 和 `fieldtype`。
- 时间戳类型使用 `dataType="TimeStamp"`。
- 字段说明使用 `<Comment>...</Comment>` 子节点，不要只写 `comment="..."` 属性。
- `Storage` 使用 `maxRepetition="1"`，不是 `maxRepetitions="1"`。
- 每个字段都保留 `<Annotation><Text/></Annotation>` 和 `<DisplayNames enable="False"/>`。

## 之前失败的原因

早期版本能创建空表，但没有字段，原因是字段 XML 结构不像 FileMaker 原生复制出来的表对象：

- 字段被放进了 `<FieldCatalog>`。
- 使用了小写属性名 `fieldtype`、`datatype`。
- 使用了 `maxRepetitions`。
- `AutoEnter`、`Validation`、`Storage` 的结构和 FileMaker 原生表 XML 不一致。

FileMaker 粘贴时能识别 `BaseTable`，所以创建了表；但无法识别里面的字段结构，所以表是空的。

## 粘贴步骤

1. 打开 FileMaker。
2. 进入 `File > Manage > Database...`。
3. 切到 `Tables` 标签页。
4. 如果之前已经粘贴出了空的 `API_Test` 表，先删除它。
5. 用支持 FileMaker 剪贴板格式的工具，把 `00-api-test-table-with-fields.fmxmlsnippet.xml` 写入 FileMaker 剪贴板。
6. 在 `Tables` 标签页直接粘贴。
7. 粘贴后检查 `API_Test` 表下是否出现 13 个字段。

## 当前字段清单

`API_Test` 当前包含以下字段：

- `id`
- `eventId`
- `source`
- `workOrderNo`
- `mesStatus`
- `message`
- `payloadJson`
- `rawScriptParameter`
- `filemakerResultJson`
- `lastError`
- `processedAt`
- `createdAt`
- `updatedAt`

这些字段名需要和脚本、布局中的 `API_Test::字段名` 保持一致。

## 本地检查命令

在仓库根目录运行：

```bash
xmllint --noout filemaker-clipboard-xml/00-api-test-table-with-fields.fmxmlsnippet.xml
```

检查字段是否直接挂在 `BaseTable` 下：

```bash
xmllint --xpath 'concat("BaseTable=", /fmxmlsnippet/BaseTable/@name, " fields=", count(/fmxmlsnippet/BaseTable/Field), " fieldCatalog=", count(/fmxmlsnippet/BaseTable/FieldCatalog), " firstChild=", name(/fmxmlsnippet/BaseTable/*[1]))' filemaker-clipboard-xml/00-api-test-table-with-fields.fmxmlsnippet.xml
```

成功时应类似：

```text
BaseTable=API_Test fields=13 fieldCatalog=0 firstChild=Field
```

检查字段名：

```bash
xmllint --xpath '/fmxmlsnippet/BaseTable/Field/@name' filemaker-clipboard-xml/00-api-test-table-with-fields.fmxmlsnippet.xml
```

检查文件是否能作为 FileMaker 表剪贴板类型读取：

```bash
osascript -e 'set p to POSIX file "/Users/gabriel/Documents/Vibe/StarRC-FileMaker/filemaker-clipboard-xml/00-api-test-table-with-fields.fmxmlsnippet.xml"' \
  -e 'set x to read p as «class XMTB»' \
  -e 'return (class of x as text)'
```

成功时返回：

```text
«class XMTB»
```

## 维护原则

- 只维护 `00-api-test-table-with-fields.fmxmlsnippet.xml` 这一个表定义版本。
- 如果以后要新增字段，直接在 `BaseTable` 下新增同样结构的 `Field` 节点。
- 新增字段后同步检查脚本和布局里的 `API_Test::字段名` 引用。
- 每次修改后至少运行 XML 有效性检查和字段数量检查。
