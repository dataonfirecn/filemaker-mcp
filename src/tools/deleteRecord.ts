import { ToolDefinition } from './index.js';

export const deleteRecordTool: ToolDefinition = {
  name: 'fm_delete_record',
  description: 'Delete a record from a FileMaker layout',
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
    },
    required: ['layout', 'recordId'],
  },
  handler: async (client, args) => {
    const { layout, recordId } = args as {
      layout: string;
      recordId: string;
    };

    await client.deleteRecord(layout, recordId);

    return {
      content: [
        {
          type: 'text',
          text: `Record ${recordId} deleted successfully from layout ${layout}`,
        },
      ],
    };
  },
};
