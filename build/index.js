#!/usr/bin/env node
// ============================================================
// FileMaker MCP Server - 主入口
// ============================================================
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { FileMakerClient } from "./filemaker/client.js";
// ============================================================
// 配置加载
// ============================================================
function loadConfig() {
    const server = process.env.FILEMAKER_SERVER;
    const database = process.env.FILEMAKER_DATABASE;
    const username = process.env.FILEMAKER_USERNAME;
    const password = process.env.FILEMAKER_PASSWORD;
    if (!server || !database || !username || !password) {
        console.error("❌ 缺少必要的环境变量。请设置以下环境变量：\n" +
            "  FILEMAKER_SERVER   - FileMaker 服务器地址 (例: https://fm.example.com)\n" +
            "  FILEMAKER_DATABASE - 数据库名称\n" +
            "  FILEMAKER_USERNAME - 用户名\n" +
            "  FILEMAKER_PASSWORD - 密码");
        process.exit(1);
    }
    return { server, database, username, password };
}
const config = loadConfig();
const fmClient = new FileMakerClient(config);
// ============================================================
// 创建 MCP Server
// ============================================================
const server = new McpServer({
    name: "filemaker-mcp",
    version: "1.0.0",
});
// ============================================================
// 工具函数
// ============================================================
function formatRecord(record) {
    const lines = [];
    lines.push(`📋 记录 ID: ${record.recordId} | 修改 ID: ${record.modId}`);
    lines.push("---");
    if (record.fieldData) {
        for (const [key, value] of Object.entries(record.fieldData)) {
            if (value !== null && value !== undefined && value !== "") {
                lines.push(`  ${key}: ${JSON.stringify(value)}`);
            }
        }
    }
    return lines.join("\n");
}
function formatRecords(records, dataInfo) {
    const lines = [];
    if (dataInfo) {
        lines.push(`📊 数据库: ${dataInfo.database} | 布局: ${dataInfo.layout} | 表: ${dataInfo.table}`);
        lines.push(`   总记录数: ${dataInfo.totalRecordCount} | 匹配: ${dataInfo.foundCount} | 返回: ${dataInfo.returnedCount}`);
        lines.push("===");
    }
    for (const record of records) {
        lines.push(formatRecord(record));
        lines.push("");
    }
    return lines.join("\n");
}
// ============================================================
// 布局管理工具
// ============================================================
server.tool("fm_list_layouts", "列出 FileMaker 数据库中所有可用的布局", {}, async () => {
    const result = await fmClient.listLayouts();
    const layouts = result.response.layouts;
    const lines = [];
    lines.push(`📂 数据库 "${config.database}" 中的布局列表 (共 ${layouts.length} 个):`);
    lines.push("---");
    for (const layout of layouts) {
        if (layout.isFolder) {
            lines.push(`📁 [文件夹] ${layout.name}`);
        }
        else {
            lines.push(`📄 ${layout.name}${layout.folder ? ` (位于: ${layout.folder})` : ""}`);
        }
    }
    return {
        content: [{ type: "text", text: lines.join("\n") }],
    };
});
server.tool("fm_get_layout_metadata", "获取指定布局的元数据，包括字段名称、类型、值列表等信息", {
    layout: z.string().describe("布局名称"),
}, async ({ layout }) => {
    const result = await fmClient.getLayoutMetadata(layout);
    const meta = result.response;
    const lines = [];
    lines.push(`📋 布局 "${layout}" 的元数据:`);
    lines.push("===");
    // 字段信息
    lines.push("\n📝 字段列表:");
    for (const field of meta.fieldMetaData) {
        const flags = [];
        if (field.global)
            flags.push("全局");
        if (field.autoEnter)
            flags.push("自动输入");
        if (field.valueList)
            flags.push(`值列表: ${field.valueList}`);
        lines.push(`  • ${field.name} (${field.result}/${field.type})${flags.length ? ` [${flags.join(", ")}]` : ""}`);
    }
    // 值列表
    if (meta.valueLists && meta.valueLists.length > 0) {
        lines.push("\n📋 值列表:");
        for (const vl of meta.valueLists) {
            lines.push(`  ${vl.name} (${vl.type}):`);
            for (const v of vl.values) {
                lines.push(`    - ${v.displayValue}${v.displayValue !== v.value ? ` (实际值: ${v.value})` : ""}`);
            }
        }
    }
    // Portal 信息
    if (meta.portalMetaData && Object.keys(meta.portalMetaData).length > 0) {
        lines.push("\n🔗 Portal:");
        for (const [portalName, fields] of Object.entries(meta.portalMetaData)) {
            lines.push(`  ${portalName}: ${fields.map((f) => f.name).join(", ")}`);
        }
    }
    return {
        content: [{ type: "text", text: lines.join("\n") }],
    };
});
// ============================================================
// 记录读取工具
// ============================================================
server.tool("fm_get_records", "从指定布局获取记录列表，支持分页和排序", {
    layout: z.string().describe("布局名称"),
    offset: z.number().optional().describe("起始位置 (从 1 开始，默认 1)"),
    limit: z.number().optional().describe("返回记录数量 (默认 100)"),
    sort: z.string().optional().describe("排序规则 JSON，如: [{\"fieldName\":\"名称\",\"sortOrder\":\"ascend\"}]"),
}, async ({ layout, offset, limit, sort }) => {
    const result = await fmClient.getRecords(layout, {
        offset,
        limit,
        sort,
    });
    return {
        content: [
            {
                type: "text",
                text: formatRecords(result.response.data, result.response.dataInfo),
            },
        ],
    };
});
server.tool("fm_get_record", "根据记录 ID 获取单条记录的详细信息", {
    layout: z.string().describe("布局名称"),
    recordId: z.string().describe("记录 ID"),
}, async ({ layout, recordId }) => {
    const result = await fmClient.getRecord(layout, recordId);
    return {
        content: [{ type: "text", text: formatRecord(result.response.data) }],
    };
});
// ============================================================
// 记录搜索工具
// ============================================================
server.tool("fm_find_records", "按条件搜索记录。支持 FileMaker 查询语法，如: \"==\"精确匹配, \"...\"范围, \"@\"单个字符等", {
    layout: z.string().describe("布局名称"),
    queries: z.array(z.record(z.string(), z.unknown())).describe("搜索条件数组，每个对象是一个查询条件。如: [{\"名称\": \"张三\"}, {\"城市\": \"北京\"}]"),
    sort: z.string().optional().describe("排序规则 JSON 字符串"),
    limit: z.number().optional().describe("返回记录数量限制"),
    offset: z.number().optional().describe("起始位置"),
}, async ({ layout, queries, sort, limit, offset }) => {
    const findRequest = {
        query: queries,
    };
    if (sort) {
        try {
            findRequest.sort = JSON.parse(sort);
        }
        catch {
            // sort 可能不是 JSON
        }
    }
    if (limit)
        findRequest.limit = limit;
    if (offset)
        findRequest.offset = offset;
    const result = await fmClient.findRecords(layout, findRequest);
    if (result.response.data.length === 0) {
        return {
            content: [{ type: "text", text: "🔍 没有找到匹配的记录。" }],
        };
    }
    return {
        content: [
            {
                type: "text",
                text: `🔍 搜索结果:\n${formatRecords(result.response.data, result.response.dataInfo)}`,
            },
        ],
    };
});
// ============================================================
// 记录创建工具
// ============================================================
server.tool("fm_create_record", "在指定布局创建一条新记录", {
    layout: z.string().describe("布局名称"),
    fieldData: z.record(z.string(), z.unknown()).describe("字段数据，键为字段名，值为字段值。如: {\"名称\": \"张三\", \"年龄\": 25}"),
}, async ({ layout, fieldData }) => {
    const result = await fmClient.createRecord(layout, { fieldData });
    return {
        content: [
            {
                type: "text",
                text: `✅ 记录创建成功！\n📋 记录 ID: ${result.response.recordId}\n修改 ID: ${result.response.modId}`,
            },
        ],
    };
});
// ============================================================
// 记录更新工具
// ============================================================
server.tool("fm_update_record", "更新指定记录的字段值", {
    layout: z.string().describe("布局名称"),
    recordId: z.string().describe("要更新的记录 ID"),
    fieldData: z.record(z.string(), z.unknown()).describe("要更新的字段数据，键为字段名，值为新值。如: {\"名称\": \"李四\", \"年龄\": 30}"),
}, async ({ layout, recordId, fieldData }) => {
    const result = await fmClient.updateRecord(layout, recordId, {
        fieldData,
    });
    return {
        content: [
            {
                type: "text",
                text: `✅ 记录更新成功！\n📋 记录 ID: ${recordId}`,
            },
        ],
    };
});
// ============================================================
// 记录删除工具
// ============================================================
server.tool("fm_delete_record", "删除指定的记录", {
    layout: z.string().describe("布局名称"),
    recordId: z.string().describe("要删除的记录 ID"),
}, async ({ layout, recordId }) => {
    await fmClient.deleteRecord(layout, recordId);
    return {
        content: [
            {
                type: "text",
                text: `✅ 记录已删除！\n📋 记录 ID: ${recordId}`,
            },
        ],
    };
});
// ============================================================
// 脚本工具
// ============================================================
server.tool("fm_list_scripts", "列出数据库中所有可用的 FileMaker 脚本", {}, async () => {
    const result = await fmClient.listScripts();
    const scripts = result.response.scripts;
    const lines = [];
    lines.push(`📜 数据库 "${config.database}" 中的脚本列表 (共 ${scripts.length} 个):`);
    lines.push("---");
    for (const script of scripts) {
        if (script.isFolder) {
            lines.push(`📁 [文件夹] ${script.name}`);
        }
        else {
            lines.push(`📜 ${script.name}${script.folder ? ` (位于: ${script.folder})` : ""}`);
        }
    }
    return {
        content: [{ type: "text", text: lines.join("\n") }],
    };
});
server.tool("fm_run_script", "执行指定的 FileMaker 脚本，可选择传入参数和关联记录", {
    layout: z.string().describe("要在哪个布局上执行脚本"),
    script: z.string().describe("脚本名称"),
    param: z.string().optional().describe("传递给脚本的参数（可选）"),
    recordId: z.string().optional().describe("关联的记录 ID（可选，脚本将在此记录上下文中运行）"),
}, async ({ layout, script, param, recordId }) => {
    const result = await fmClient.runScript(layout, script, param, recordId);
    const lines = [];
    lines.push(`📜 脚本 "${script}" 执行完成！`);
    lines.push("---");
    if (result.response.scriptResult !== null && result.response.scriptResult !== undefined) {
        lines.push(`返回值: ${result.response.scriptResult}`);
    }
    if (result.response.scriptError) {
        lines.push(`⚠️ 脚本错误: ${result.response.scriptError}`);
    }
    else {
        lines.push("✅ 执行成功，无错误。");
    }
    return {
        content: [{ type: "text", text: lines.join("\n") }],
    };
});
// ============================================================
// 全局字段工具
// ============================================================
server.tool("fm_set_global_fields", "设置全局字段的值（需要在指定布局上下文中）", {
    globalFields: z.record(z.string(), z.unknown()).describe("全局字段数据，键为 全局字段名 (格式: 表名::字段名)，值为要设置的值"),
}, async ({ globalFields }) => {
    await fmClient.setGlobalFields("", globalFields);
    return {
        content: [
            {
                type: "text",
                text: `✅ 全局字段已设置！\n${Object.entries(globalFields)
                    .map(([k, v]) => `  ${k} = ${JSON.stringify(v)}`)
                    .join("\n")}`,
            },
        ],
    };
});
// ============================================================
// 数据库信息工具
// ============================================================
server.tool("fm_get_database_info", "获取当前连接的 FileMaker 数据库基本信息，包括所有布局和脚本的概览", {}, async () => {
    const [layoutsResult, scriptsResult] = await Promise.all([
        fmClient.listLayouts(),
        fmClient.listScripts(),
    ]);
    const layouts = layoutsResult.response.layouts.filter((l) => !l.isFolder);
    const scripts = scriptsResult.response.scripts.filter((s) => !s.isFolder);
    const lines = [];
    lines.push(`🗄️ FileMaker 数据库概览`);
    lines.push("===");
    lines.push(`服务器: ${config.server}`);
    lines.push(`数据库: ${config.database}`);
    lines.push(`用户: ${config.username}`);
    lines.push(`布局数量: ${layouts.length}`);
    lines.push(`脚本数量: ${scripts.length}`);
    lines.push("");
    lines.push("📄 可用布局:");
    for (const l of layouts.slice(0, 20)) {
        lines.push(`  • ${l.name}`);
    }
    if (layouts.length > 20) {
        lines.push(`  ... 还有 ${layouts.length - 20} 个布局`);
    }
    lines.push("");
    lines.push("📜 可用脚本:");
    for (const s of scripts.slice(0, 20)) {
        lines.push(`  • ${s.name}`);
    }
    if (scripts.length > 20) {
        lines.push(`  ... 还有 ${scripts.length - 20} 个脚本`);
    }
    return {
        content: [{ type: "text", text: lines.join("\n") }],
    };
});
// ============================================================
// 启动服务器
// ============================================================
async function main() {
    const transport = new StdioServerTransport();
    await server.connect(transport);
    console.error("✅ FileMaker MCP Server 已启动");
    console.error(`   服务器: ${config.server}`);
    console.error(`   数据库: ${config.database}`);
}
main().catch((error) => {
    console.error("❌ FileMaker MCP Server 启动失败:", error);
    process.exit(1);
});
//# sourceMappingURL=index.js.map