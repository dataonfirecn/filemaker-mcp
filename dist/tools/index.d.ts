import { Tool } from '@modelcontextprotocol/sdk/types.js';
import { FileMakerClient } from '../filemaker/client.js';
export interface ToolDefinition {
    name: string;
    description: string;
    inputSchema: Tool['inputSchema'];
    handler: (client: FileMakerClient, args: Record<string, unknown>) => Promise<{
        content: Array<{
            type: string;
            text: string;
        }>;
    }>;
}
export declare const tools: ToolDefinition[];
//# sourceMappingURL=index.d.ts.map