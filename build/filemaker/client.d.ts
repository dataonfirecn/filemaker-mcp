import type { FMConfig, FMLayoutListResponse, FMLayoutMetadataResponse, FMRecordListResponse, FMRecordResponse, FMCreateRecordRequest, FMCreateRecordResponse, FMUpdateRecordRequest, FMDeleteResponse, FMFindRequest, FMFindResponse, FMScriptListResponse, FMRunScriptResponse } from "./types.js";
/**
 * FileMaker Data API 客户端
 * 封装所有与 FileMaker Server 的通信
 */
export declare class FileMakerClient {
    private config;
    private token;
    private tokenExpiry;
    private readonly TOKEN_LIFETIME_MS;
    constructor(config: FMConfig);
    /** 获取基础 API URL */
    private get baseUrl();
    /** 获取认证头部 */
    private get authHeader();
    /**
     * 获取有效的 Token（自动刷新）
     */
    private getValidToken;
    /**
     * 发起 API 请求
     */
    private request;
    /**
     * 获取错误码对应的消息
     */
    private getErrorMessage;
    /** 列出所有布局 */
    listLayouts(): Promise<FMLayoutListResponse>;
    /** 获取布局元数据 */
    getLayoutMetadata(layout: string): Promise<FMLayoutMetadataResponse>;
    /** 获取记录列表 */
    getRecords(layout: string, options?: {
        offset?: number;
        limit?: number;
        sort?: string;
        portal?: string[];
        "layout.response"?: string;
    }): Promise<FMRecordListResponse>;
    /** 获取单条记录 */
    getRecord(layout: string, recordId: string, options?: {
        portal?: string[];
        "layout.response"?: string;
    }): Promise<FMRecordResponse>;
    /** 创建记录 */
    createRecord(layout: string, data: FMCreateRecordRequest): Promise<FMCreateRecordResponse>;
    /** 更新记录 */
    updateRecord(layout: string, recordId: string, data: FMUpdateRecordRequest): Promise<FMDeleteResponse>;
    /** 删除记录 */
    deleteRecord(layout: string, recordId: string): Promise<FMDeleteResponse>;
    /** 搜索记录 */
    findRecords(layout: string, request: FMFindRequest): Promise<FMFindResponse>;
    /** 列出脚本 */
    listScripts(): Promise<FMScriptListResponse>;
    /** 执行脚本 */
    runScript(layout: string, script: string, param?: string, recordId?: string): Promise<FMRunScriptResponse>;
    /** 设置全局字段 */
    setGlobalFields(layout: string, globalFields: Record<string, unknown>): Promise<FMDeleteResponse>;
    /** 释放 Token */
    disconnect(): Promise<void>;
}
//# sourceMappingURL=client.d.ts.map