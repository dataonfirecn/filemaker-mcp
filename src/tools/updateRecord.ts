import { ToolDefinition } from './index.js';

export const updateRecordTool: ToolDefinition = {
  name: 'fm_update_record',
  description: 'Update an existing record in a FileMaker layout',
  inputSchema: {
    type: 'object',
    properties: {
      layout: {
        type: 'string',
        description: 'The FileMaker layout name',
      },
      recordId: {
        type: 'string',
        description: 'The internal FileMaker record ID',
      },
      data: {
        type: 'object',
        description: 'Field data to update as key-value pairs',
      },
    },
    required: ['layout', 'recordId', 'data'],
  },
  handler: async (client, args) => {
    const { layout, recordId, data } = args as {
      layout: string;
      recordId: string;
      data: Record<string, unknown>;
    };

    const result = await client.updateRecord(layout, recordId, data);

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
