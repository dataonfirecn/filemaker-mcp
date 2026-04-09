import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import { FileMakerClient } from './filemaker/client.js';
import { tools } from './tools/index.js';

export class FileMakerMCPServer {
  private server: Server;
  private fmClient: FileMakerClient;

  constructor() {
    this.server = new Server(
      {
        name: 'filemaker-mcp-server',
        version: '0.1.0',
      },
      {
        capabilities: {
          tools: {},
        },
      }
    );

    this.fmClient = new FileMakerClient({
      host: process.env.FILEMAKER_HOST || '',
      database: process.env.FILEMAKER_DATABASE || '',
      username: process.env.FILEMAKER_USERNAME || '',
      password: process.env.FILEMAKER_PASSWORD || '',
    });

    this.setupHandlers();
  }

  private setupHandlers(): void {
    // List available tools
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: tools.map((tool) => ({
        name: tool.name,
        description: tool.description,
        inputSchema: tool.inputSchema,
      })),
    }));

    // Handle tool calls
    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;

      const tool = tools.find((t) => t.name === name);
      if (!tool) {
        throw new Error(`Unknown tool: ${name}`);
      }

      try {
        return await tool.handler(this.fmClient, args || {});
      } catch (error) {
        return {
          content: [
            {
              type: 'text',
              text: `Error: ${error instanceof Error ? error.message : String(error)}`,
            },
          ],
        };
      }
    });
  }

  async run(): Promise<void> {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error('FileMaker MCP server running on stdio');
  }
}
