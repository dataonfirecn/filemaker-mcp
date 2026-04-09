// ============================================================
// FileMaker Data API Client
// ============================================================
/** FileMaker 错误码映射（常见错误码） */
const FM_ERROR_CODES = {
    "0": "成功",
    "-1": "未知错误",
    "100": "记录缺失",
    "101": "记录不可访问",
    "102": "字段缺失",
    "103": "关系缺失",
    "104": "脚本缺失",
    "105": "布局缺失",
    "106": "查询缺失",
    "200": "记录访问被拒绝",
    "201": "字段不可修改",
    "202": "字段访问被拒绝",
    "203": "没有可用字段",
    "204": "布局中没有可访问的字段",
    "205": "没有权限创建记录",
    "206": "没有权限删除记录",
    "207": "没有权限修改记录",
    "300": "文件被锁定或正在使用",
    "301": "记录正在被其他用户修改",
    "302": "表正在被其他用户修改",
    "400": "查找条件为空",
    "401": "没有找到匹配的记录",
    "402": "查询结果过多",
    "500": "日期值不符合验证选项",
    "501": "时间值不符合验证选项",
    "502": "数值不符合验证选项",
    "503": "数字中的字符太多",
    "504": "值不在值列表中",
    "505": "验证计算失败",
    "506": "字段值计算失败",
    "507": "字段值为空，不允许为空",
    "508": "字段值的字符数超出限制",
    "509": "字段值超出范围",
    "510": "字段值不唯一",
    "511": "字段值已存在",
    "600": "打印错误",
    "700": "文件缺失",
    "701": "文件无法打开",
    "702": "文件为只读",
    "711": "导入失败",
    "714": "密码过期",
    "715": "密码不正确",
    "716": "账户已禁用",
    "717": "账户已过期",
    "718": "需要更改密码",
    "800": "无法在主机上创建文件",
    "801": "无法创建临时文件",
    "802": "无法打开文件",
    "803": "文件是单用户版",
    "804": "文件不是 FileMaker 文件",
    "805": "文件版本太旧",
    "806": "文件已损坏",
    "807": "无法自动打开文件",
    "808": "无法保存文件",
    "810": "文件正在被其他用户使用",
    "811": "主机不可用",
    "812": "文件权限冲突",
    "813": "网络协议错误",
    "814": "文件已打开",
    "815": "文件无法打开",
    "900": "通用错误",
    "911": "连接超时",
    "912": "SSL 错误",
    "913": "认证失败",
    "951": "意外断开连接",
    "952": "API 调用次数超出限制",
    "953": "请求超出允许的数据量",
    "955": "Data API 请求无效",
    "956": "Data API 不可用",
    "1200": "通用通信错误",
    "1202": "无法连接到服务器",
    "1203": "数据库不可用",
    "1204": "用户名或密码错误",
    "1206": "文件未启用 Data API",
    "1210": "连接被拒绝",
    "1211": "连接已重置",
    "1212": "服务器不可达",
    "1213": "DNS 解析失败",
    "1214": "URL 格式错误",
};
/**
 * FileMaker Data API 客户端
 * 封装所有与 FileMaker Server 的通信
 */
export class FileMakerClient {
    config;
    token = null;
    tokenExpiry = 0;
    TOKEN_LIFETIME_MS = 15 * 60 * 1000; // 15 分钟
    constructor(config) {
        // 移除末尾斜杠
        this.config = {
            ...config,
            server: config.server.replace(/\/+$/, ""),
        };
    }
    /** 获取基础 API URL */
    get baseUrl() {
        return `${this.config.server}/fmi/data/v1/databases/${encodeURIComponent(this.config.database)}`;
    }
    /** 获取认证头部 */
    get authHeader() {
        return `Basic ${Buffer.from(`${this.config.username}:${this.config.password}`).toString("base64")}`;
    }
    /**
     * 获取有效的 Token（自动刷新）
     */
    async getValidToken() {
        if (this.token && Date.now() < this.tokenExpiry) {
            return this.token;
        }
        const url = `${this.config.server}/fmi/data/v1/databases/${encodeURIComponent(this.config.database)}/sessions`;
        const response = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Authorization: this.authHeader,
            },
        });
        if (!response.ok) {
            throw new Error(`FileMaker 认证失败 (HTTP ${response.status}): ${response.statusText}\n` +
                `请检查服务器地址、用户名和密码是否正确。`);
        }
        const data = (await response.json());
        if (data.messages?.[0]?.code !== "0") {
            const errorCode = data.messages?.[0]?.code || "未知";
            throw new Error(`FileMaker 认证失败 (错误码 ${errorCode}): ${this.getErrorMessage(errorCode)}`);
        }
        this.token = data.response.token;
        // 提前 1 分钟过期，避免边界情况
        this.tokenExpiry = Date.now() + this.TOKEN_LIFETIME_MS - 60_000;
        return this.token;
    }
    /**
     * 发起 API 请求
     */
    async request(method, path, body, params) {
        const token = await this.getValidToken();
        let url = `${this.baseUrl}${path}`;
        if (params) {
            const query = new URLSearchParams(params).toString();
            if (query)
                url += `?${query}`;
        }
        const headers = {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
        };
        const response = await fetch(url, {
            method,
            headers,
            body: body ? JSON.stringify(body) : undefined,
        });
        if (response.status === 401) {
            // Token 过期，清除并重试一次
            this.token = null;
            this.tokenExpiry = 0;
            return this.request(method, path, body, params);
        }
        if (!response.ok) {
            const text = await response.text().catch(() => "");
            throw new Error(`FileMaker API 请求失败 (HTTP ${response.status}): ${response.statusText}\n${text}`);
        }
        const data = (await response.json());
        // 检查 FileMaker 错误码
        const fmCode = data?.messages?.[0]?.code;
        if (fmCode && fmCode !== "0") {
            const fmMessage = data?.messages?.[0]?.message || "";
            throw new Error(`FileMaker 错误 (错误码 ${fmCode}): ${this.getErrorMessage(fmCode)}${fmMessage ? ` - ${fmMessage}` : ""}`);
        }
        return data;
    }
    /**
     * 获取错误码对应的消息
     */
    getErrorMessage(code) {
        return FM_ERROR_CODES[code] || `未知错误 (${code})`;
    }
    // ============================================================
    // 布局操作
    // ============================================================
    /** 列出所有布局 */
    async listLayouts() {
        return this.request("GET", "/layouts");
    }
    /** 获取布局元数据 */
    async getLayoutMetadata(layout) {
        return this.request("GET", `/layouts/${encodeURIComponent(layout)}`);
    }
    // ============================================================
    // 记录操作
    // ============================================================
    /** 获取记录列表 */
    async getRecords(layout, options) {
        const params = {};
        if (options?.offset)
            params._offset = String(options.offset);
        if (options?.limit)
            params._limit = String(options.limit);
        if (options?.sort)
            params._sort = options.sort;
        // 处理 portal 参数
        if (options?.portal && options.portal.length > 0) {
            options.portal.forEach((p, i) => {
                params[`portal.${i}`] = p;
            });
        }
        return this.request("GET", `/layouts/${encodeURIComponent(layout)}/records`, undefined, params);
    }
    /** 获取单条记录 */
    async getRecord(layout, recordId, options) {
        const params = {};
        if (options?.portal && options.portal.length > 0) {
            options.portal.forEach((p, i) => {
                params[`portal.${i}`] = p;
            });
        }
        return this.request("GET", `/layouts/${encodeURIComponent(layout)}/records/${encodeURIComponent(recordId)}`, undefined, Object.keys(params).length > 0 ? params : undefined);
    }
    /** 创建记录 */
    async createRecord(layout, data) {
        return this.request("POST", `/layouts/${encodeURIComponent(layout)}/records`, data);
    }
    /** 更新记录 */
    async updateRecord(layout, recordId, data) {
        return this.request("PATCH", `/layouts/${encodeURIComponent(layout)}/records/${encodeURIComponent(recordId)}`, data);
    }
    /** 删除记录 */
    async deleteRecord(layout, recordId) {
        return this.request("DELETE", `/layouts/${encodeURIComponent(layout)}/records/${encodeURIComponent(recordId)}`);
    }
    // ============================================================
    // 搜索操作
    // ============================================================
    /** 搜索记录 */
    async findRecords(layout, request) {
        return this.request("POST", `/layouts/${encodeURIComponent(layout)}/_find`, request);
    }
    // ============================================================
    // 脚本操作
    // ============================================================
    /** 列出脚本 */
    async listScripts() {
        return this.request("GET", "/scripts");
    }
    /** 执行脚本 */
    async runScript(layout, script, param, recordId) {
        const path = recordId
            ? `/layouts/${encodeURIComponent(layout)}/records/${encodeURIComponent(recordId)}`
            : `/layouts/${encodeURIComponent(layout)}/records`;
        const body = { script };
        if (param)
            body["script.param"] = param;
        return this.request("PATCH", path, body);
    }
    // ============================================================
    // 全局字段
    // ============================================================
    /** 设置全局字段 */
    async setGlobalFields(layout, globalFields) {
        return this.request("PATCH", `/globals`, { globalFields }, undefined);
    }
    // ============================================================
    // 生命周期
    // ============================================================
    /** 释放 Token */
    async disconnect() {
        if (this.token) {
            try {
                await fetch(`${this.baseUrl}/sessions/${this.token}`, {
                    method: "DELETE",
                    headers: {
                        "Content-Type": "application/json",
                    },
                });
            }
            catch {
                // 忽略释放 Token 时的错误
            }
            this.token = null;
            this.tokenExpiry = 0;
        }
    }
}
//# sourceMappingURL=client.js.map