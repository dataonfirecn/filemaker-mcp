export interface FileMakerConfig {
    host: string;
    database: string;
    username: string;
    password: string;
}
export interface QueryResult {
    data: Record<string, unknown>[];
    foundCount: number;
    returnedCount: number;
}
export interface CreateResult {
    recordId: string;
    modId: string;
}
export interface UpdateResult {
    recordId: string;
    modId: string;
}
export interface DeleteResult {
    recordId: string;
}
export interface ScriptResult {
    result: string;
    error?: string;
}
export declare class FileMakerClient {
    private config;
    private token;
    private tokenExpiresAt;
    private readonly TOKEN_TTL;
    constructor(config: FileMakerConfig);
    /**
     * Safely encode a URL component, preserving already-encoded characters
     */
    private encodeParam;
    /**
     * Check if the current token is expired
     */
    private isTokenExpired;
    private getToken;
    private request;
    findRecords(layout: string, query?: Record<string, unknown>, limit?: number, offset?: number, sort?: Array<{
        fieldName: string;
        sortOrder: 'ascend' | 'descend';
    }>): Promise<QueryResult>;
    getRecord(layout: string, recordId: string): Promise<Record<string, unknown>>;
    createRecord(layout: string, data: Record<string, unknown>): Promise<CreateResult>;
    updateRecord(layout: string, recordId: string, data: Record<string, unknown>): Promise<UpdateResult>;
    deleteRecord(layout: string, recordId: string): Promise<DeleteResult>;
    runScript(layout: string, scriptName: string, scriptParam?: string): Promise<ScriptResult>;
    listLayouts(): Promise<string[]>;
    getLayoutFields(layout: string): Promise<Array<{
        name: string;
        type: string;
        result: string;
    }>>;
}
//# sourceMappingURL=client.d.ts.map