import { ToolDefinition } from './index.js';

export const createRecordTool: ToolDefinition = {
  name: 'fm_create_record',
  description: 'Create a new record in a FileMaker layout',
  inputSchema: {
    type: 'object',
    properties: {
      layout: {
        type: 'string',
        description: 'The FileMaker layout name',
      },
      data: {
        type: 'object',
        description: 'Field data as key-value pairs',
      },
    },
    required: ['layout', 'data'],
  },
  handler: async (client, args) => {
    const { layout, data } = args as {
      layout: string;
      data: Record<string, unknown>;
    };

    const result = await client.createRecord(layout, data);

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  },
};
