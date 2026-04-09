export class FileMakerClient {
    config;
    token = null;
    tokenExpiresAt = null;
    TOKEN_TTL = 14 * 60 * 1000; // 14 minutes (less than 15 min server timeout)
    constructor(config) {
        this.config = config;
    }
    /**
     * Safely encode a URL component, preserving already-encoded characters
     */
    encodeParam(param) {
        try {
            return encodeURIComponent(param).replace(/%20/g, '+');
        }
        catch {
            return param;
        }
    }
    /**
     * Check if the current token is expired
     */
    isTokenExpired() {
        if (!this.token || !this.tokenExpiresAt) {
            return true;
        }
        return Date.now() >= this.tokenExpiresAt;
    }
    async getToken() {
        // Return existing token if it's still valid
        if (this.token && !this.isTokenExpired()) {
            return this.token;
        }
        // Token is expired or doesn't exist, get a new one
        const encodedDb = this.encodeParam(this.config.database);
        const url = `${this.config.host}/fmi/data/v2/databases/${encodedDb}/sessions`;
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Basic ${btoa(`${this.config.username}:${this.config.password}`)}`,
            },
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(`Failed to authenticate: ${JSON.stringify(error)}`);
        }
        const data = await response.json();
        this.token = data.response.token ?? null;
        if (!this.token) {
            throw new Error('No token received from FileMaker API');
        }
        // Set expiration time
        this.tokenExpiresAt = Date.now() + this.TOKEN_TTL;
        return this.token;
    }
    async request(endpoint, options) {
        const token = await this.getToken();
        const encodedDb = this.encodeParam(this.config.database);
        const url = `${this.config.host}/fmi/data/v2/databases/${encodedDb}${endpoint}`;
        const response = await fetch(url, {
            ...options,
            headers: {
                ...options?.headers,
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
            },
        });
        if (!response.ok) {
            if (response.status === 401) {
                // Token expired, retry once
                this.token = null;
                return this.request(endpoint, options);
            }
            const error = await response.json();
            throw new Error(`API error: ${JSON.stringify(error)}`);
        }
        return response.json();
    }
    async findRecords(layout, query = {}, limit = 100, offset = 1, sort) {
        const encodedLayout = this.encodeParam(layout);
        // Use _find POST endpoint when sort is specified (required for sorting)
        if (sort && sort.length > 0) {
            // FileMaker requires at least one query criterion for _find
            // Use a wildcard on a common field to match all records
            const effectiveQuery = Object.keys(query).length > 0 ? query : { 'ID': '*' };
            const requestBody = {
                query: [effectiveQuery],
                limit,
                offset,
                sort,
            };
            const result = (await this.request(`/layouts/${encodedLayout}/_find`, {
                method: 'POST',
                body: JSON.stringify(requestBody),
            }));
            return {
                data: result.response.data,
                foundCount: result.response.dataInfo.foundCount,
                returnedCount: result.response.dataInfo.returnedCount,
            };
        }
        // Use _find for queries, GET /records for simple listing
        if (Object.keys(query).length > 0) {
            const requestBody = {
                query: [query],
                limit,
                offset,
            };
            const result = (await this.request(`/layouts/${encodedLayout}/_find`, {
                method: 'POST',
                body: JSON.stringify(requestBody),
            }));
            return {
                data: result.response.data,
                foundCount: result.response.dataInfo.foundCount,
                returnedCount: result.response.dataInfo.returnedCount,
            };
        }
        // No query and no sort - use simple GET /records endpoint
        const result = (await this.request(`/layouts/${encodedLayout}/records?_limit=${limit}&_offset=${offset}`, {
            method: 'GET',
        }));
        return {
            data: result.response.data,
            foundCount: result.response.dataInfo.foundCount || result.response.dataInfo.totalRecordCount,
            returnedCount: result.response.dataInfo.returnedCount,
        };
    }
    async getRecord(layout, recordId) {
        const encodedLayout = this.encodeParam(layout);
        const result = (await this.request(`/layouts/${encodedLayout}/records/${recordId}`));
        return result.response.data;
    }
    async createRecord(layout, data) {
        const encodedLayout = this.encodeParam(layout);
        const result = (await this.request(`/layouts/${encodedLayout}/records`, {
            method: 'POST',
            body: JSON.stringify({
                fieldData: data,
            }),
        }));
        return {
            recordId: result.response.recordId,
            modId: result.response.modId,
        };
    }
    async updateRecord(layout, recordId, data) {
        const encodedLayout = this.encodeParam(layout);
        const result = (await this.request(`/layouts/${encodedLayout}/records/${recordId}`, {
            method: 'PATCH',
            body: JSON.stringify({
                fieldData: data,
            }),
        }));
        return {
            recordId: result.response.recordId,
            modId: result.response.modId,
        };
    }
    async deleteRecord(layout, recordId) {
        const encodedLayout = this.encodeParam(layout);
        await this.request(`/layouts/${encodedLayout}/records/${recordId}`, {
            method: 'DELETE',
        });
        return { recordId };
    }
    async runScript(layout, scriptName, scriptParam) {
        const encodedLayout = this.encodeParam(layout);
        const result = (await this.request(`/layouts/${encodedLayout}/script/${this.encodeParam(scriptName)}`, {
            method: 'GET',
            ...(scriptParam && {
                body: JSON.stringify({ scriptParam }),
            }),
        }));
        return {
            result: result.response.scriptResult,
            error: result.response.scriptError,
        };
    }
    async listLayouts() {
        const result = (await this.request(`/layouts`, {
            method: 'GET',
        }));
        const layouts = [];
        for (const item of result.response.layouts) {
            // If it's a folder, add its child layouts
            if (item.isFolder && item.folderLayoutNames) {
                for (const child of item.folderLayoutNames) {
                    layouts.push(child.name);
                }
            }
            else if (!item.isFolder) {
                // It's a regular layout
                layouts.push(item.name);
            }
        }
        return layouts;
    }
    async getLayoutFields(layout) {
        const encodedLayout = this.encodeParam(layout);
        const result = (await this.request(`/layouts/${encodedLayout}`, {
            method: 'GET',
        }));
        return result.response.fieldMetaData;
    }
}
//# sourceMappingURL=client.js.map