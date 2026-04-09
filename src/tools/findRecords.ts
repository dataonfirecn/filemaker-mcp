import { ToolDefinition } from './index.js';

export const findRecordsTool: ToolDefinition = {
  name: 'fm_find_records',
  description: 'Find records in a FileMaker layout using query criteria',
  inputSchema: {
    type: 'object',
    properties: {
      layout: {
        type: 'string',
        description: 'The FileMaker layout name to query',
      },
      query: {
        type: 'object',
        description: 'Query criteria as key-value pairs (e.g., {"Status": "Active"})',
        default: {},
      },
      limit: {
        type: 'number',
        description: 'Maximum number of records to return',
        default: 100,
      },
    },
    required: ['layout'],
  },
  handler: async (client, args) => {
    const { layout, query = {}, limit } = args as {
      layout: string;
      query?: Record<string, unknown>;
      limit?: number;
    };

    const result = await client.findRecords(layout, query);

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(
            {
              layout,
              foundCount: result.foundCount,
              returnedCount: result.returnedCount,
              records: result.data,
            },
            null,
            2
          ),
        },
      ],
    };
  },
};
