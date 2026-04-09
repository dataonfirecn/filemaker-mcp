/** FileMaker API 错误消息 */
export interface FileMakerMessage {
    message: string;
    code: string;
}
/** Token 响应 */
export interface FMTokenResponse {
    response: {
        token: string;
    };
    messages: FileMakerMessage[];
}
/** 字段元数据 */
export interface FMFieldMetaData {
    name: string;
    type: string;
    displayType: string;
    result: string;
    valueList?: string;
    global: boolean;
    autoEnter?: boolean;
    fourDigitYear?: boolean;
    maxRecursion?: number;
    repetitionStart?: number;
    repetitionEnd?: number;
    numeric?: {
        decimal?: number;
        thousandsSeparator?: string;
        currency?: boolean;
        negativeStyle?: number;
        currencySymbol?: string;
        currencyLeading?: boolean;
    };
}
/** 值列表项 */
export interface FMValueListItem {
    displayValue: string;
    value: string;
}
/** 值列表 */
export interface FMValueList {
    name: string;
    type: string;
    values: FMValueListItem[];
}
/** 布局元数据响应 */
export interface FMLayoutMetadataResponse {
    response: {
        fieldMetaData: FMFieldMetaData[];
        portalMetaData: Record<string, FMFieldMetaData[]>;
        valueLists: FMValueList[];
    };
    messages: FileMakerMessage[];
}
/** 布局概要信息 */
export interface FMLayoutSummary {
    name: string;
    isFolder?: boolean;
    folder?: string;
    folderId?: number;
    id?: number;
}
/** 布局列表响应 */
export interface FMLayoutListResponse {
    response: {
        layouts: FMLayoutSummary[];
    };
    messages: FileMakerMessage[];
}
/** 记录字段数据 */
export interface FMRecordField {
    value: string | number | boolean | null;
    displayValue?: string;
}
/** 记录数据 */
export interface FMRecord {
    recordId: string;
    modId: string;
    fieldData: Record<string, unknown>;
    portalData?: Record<string, unknown[]>;
    portalDataInfo?: Record<string, {
        foundCount: number;
    }>;
}
/** 记录列表响应 */
export interface FMRecordListResponse {
    response: {
        data: FMRecord[];
        dataInfo: {
            database: string;
            layout: string;
            table: string;
            totalRecordCount: number;
            foundCount: number;
            returnedCount: number;
        };
    };
    messages: FileMakerMessage[];
}
/** 单条记录响应 */
export interface FMRecordResponse {
    response: {
        data: FMRecord;
    };
    messages: FileMakerMessage[];
}
/** 创建记录请求 */
export interface FMCreateRecordRequest {
    fieldData: Record<string, unknown>;
    portalData?: Record<string, Record<string, unknown>[]>;
    script?: string;
    scriptPrerequest?: string;
    scriptPresort?: string;
}
/** 创建记录响应 */
export interface FMCreateRecordResponse {
    response: {
        recordId: string;
        modId: string;
    };
    messages: FileMakerMessage[];
}
/** 更新记录请求 */
export interface FMUpdateRecordRequest {
    fieldData: Record<string, unknown>;
    portalData?: Record<string, Record<string, unknown>[]>;
    script?: string;
    scriptPrerequest?: string;
    scriptPresort?: string;
    merge?: boolean;
}
/** 通用删除响应 */
export interface FMDeleteResponse {
    response: Record<string, unknown>;
    messages: FileMakerMessage[];
}
/** 搜索排序 */
export interface FMFindSort {
    fieldName: string;
    sortOrder: "ascend" | "descend";
}
/** 搜索请求 */
export interface FMFindRequest {
    query: Record<string, unknown>[];
    sort?: FMFindSort[];
    limit?: number;
    offset?: number;
    portal?: string[];
    dateformats?: string;
    "layout.response"?: string;
}
/** 搜索响应 */
export interface FMFindResponse {
    response: {
        data: FMRecord[];
        dataInfo: {
            database: string;
            layout: string;
            table: string;
            totalRecordCount: number;
            foundCount: number;
            returnedCount: number;
        };
    };
    messages: FileMakerMessage[];
}
/** 脚本列表响应 */
export interface FMScriptListResponse {
    response: {
        scripts: Array<{
            name: string;
            isFolder: boolean;
            folder?: string;
            id?: number;
        }>;
    };
    messages: FileMakerMessage[];
}
/** 脚本执行响应 */
export interface FMRunScriptResponse {
    response: {
        scriptResult: string | null;
        scriptError: string | null;
    };
    messages: FileMakerMessage[];
}
/** 通用 API 响应 */
export type FMApiResponse = FMTokenResponse | FMLayoutMetadataResponse | FMLayoutListResponse | FMRecordListResponse | FMRecordResponse | FMCreateRecordResponse | FMDeleteResponse | FMFindResponse | FMScriptListResponse | FMRunScriptResponse;
/** 配置接口 */
export interface FMConfig {
    server: string;
    database: string;
    username: string;
    password: string;
}
//# sourceMappingURL=types.d.ts.map