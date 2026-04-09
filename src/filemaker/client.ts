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

export class FileMakerClient {
  private config: FileMakerConfig;
  private token: string | null = null;
  private tokenExpiresAt: number | null = null;
  private readonly TOKEN_TTL = 14 * 60 * 1000; // 14 minutes (less than 15 min server timeout)

  constructor(config: FileMakerConfig) {
    this.config = config;
  }

  /**
   * Safely encode a URL component, preserving already-encoded characters
   */
  private encodeParam(param: string): string {
    try {
      return encodeURIComponent(param).replace(/%20/g, '+');
    } catch {
      return param;
    }
  }

  /**
   * Check if the current token is expired
   */
  private isTokenExpired(): boolean {
    if (!this.token || !this.tokenExpiresAt) {
      return true;
    }
    return Date.now() >= this.tokenExpiresAt;
  }

  private async getToken(): Promise<string> {
    // Return existing token if it's still valid
    if (this.token && !this.isTokenExpired()) {
      return this.token;
    }

    // Token is expired or doesn't exist, get a new one
    const url = `${this.config.host}/fmi/data/v2/databases/${this.config.database}/sessions`;
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

    const data = await response.json() as { response: { token: string } };
    this.token = data.response.token ?? null;
    if (!this.token) {
      throw new Error('No token received from FileMaker API');
    }
    // Set expiration time
    this.tokenExpiresAt = Date.now() + this.TOKEN_TTL;
    return this.token;
  }

  private async request(
    endpoint: string,
    options?: RequestInit
  ): Promise<unknown> {
    const token = await this.getToken();
    const url = `${this.config.host}/fmi/data/v2/databases/${this.config.database}${endpoint}`;

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

  async findRecords(
    layout: string,
    query: Record<string, unknown> = {}
  ): Promise<QueryResult> {
    const encodedLayout = this.encodeParam(layout);
    // If query is empty, use GET /records endpoint to get all records
    if (Object.keys(query).length === 0) {
      const result = (await this.request(`/layouts/${encodedLayout}/records?_limit=100`, {
        method: 'GET',
      })) as any;

      return {
        data: result.response.data,
        foundCount: result.response.dataInfo.foundCount || result.response.dataInfo.totalRecordCount,
        returnedCount: result.response.dataInfo.returnedCount,
      };
    }

    // Otherwise use _find with query
    const result = (await this.request(`/layouts/${encodedLayout}/_find`, {
      method: 'POST',
      body: JSON.stringify({
        query: [query],
        limit: 100,
      }),
    })) as any;

    return {
      data: result.response.data,
      foundCount: result.response.dataInfo.foundCount,
      returnedCount: result.response.dataInfo.returnedCount,
    };
  }

  async getRecord(
    layout: string,
    recordId: string
  ): Promise<Record<string, unknown>> {
    const encodedLayout = this.encodeParam(layout);
    const result = (await this.request(
      `/layouts/${encodedLayout}/records/${recordId}`
    )) as any;
    return result.response.data;
  }

  async createRecord(
    layout: string,
    data: Record<string, unknown>
  ): Promise<CreateResult> {
    const encodedLayout = this.encodeParam(layout);
    const result = (await this.request(`/layouts/${encodedLayout}/records`, {
      method: 'POST',
      body: JSON.stringify({
        fieldData: data,
      }),
    })) as any;

    return {
      recordId: result.response.recordId,
      modId: result.response.modId,
    };
  }

  async updateRecord(
    layout: string,
    recordId: string,
    data: Record<string, unknown>
  ): Promise<UpdateResult> {
    const encodedLayout = this.encodeParam(layout);
    const result = (await this.request(
      `/layouts/${encodedLayout}/records/${recordId}`,
      {
        method: 'PATCH',
        body: JSON.stringify({
          fieldData: data,
        }),
      }
    )) as any;

    return {
      recordId: result.response.recordId,
      modId: result.response.modId,
    };
  }

  async deleteRecord(
    layout: string,
    recordId: string
  ): Promise<DeleteResult> {
    const encodedLayout = this.encodeParam(layout);
    await this.request(`/layouts/${encodedLayout}/records/${recordId}`, {
      method: 'DELETE',
    });
    return { recordId };
  }

  async runScript(
    layout: string,
    scriptName: string,
    scriptParam?: string
  ): Promise<ScriptResult> {
    const encodedLayout = this.encodeParam(layout);
    const result = (await this.request(
      `/layouts/${encodedLayout}/script/${this.encodeParam(scriptName)}`,
      {
        method: 'GET',
        ...(scriptParam && {
          body: JSON.stringify({ scriptParam }),
        }),
      }
    )) as any;

    return {
      result: result.response.scriptResult,
      error: result.response.scriptError,
    };
  }

  async listLayouts(): Promise<string[]> {
    const result = (await this.request(`/layouts`, {
      method: 'GET',
    })) as any;

    const layouts: string[] = [];
    for (const item of result.response.layouts) {
      // If it's a folder, add its child layouts
      if (item.isFolder && item.folderLayoutNames) {
        for (const child of item.folderLayoutNames) {
          layouts.push(child.name);
        }
      } else if (!item.isFolder) {
        // It's a regular layout
        layouts.push(item.name);
      }
    }
    return layouts;
  }

  async getLayoutFields(layout: string): Promise<
    Array<{ name: string; type: string; result: string }>
  > {
    const encodedLayout = this.encodeParam(layout);
    const result = (await this.request(`/layouts/${encodedLayout}`, {
      method: 'GET',
    })) as any;
    return result.response.fieldMetaData;
  }
}
