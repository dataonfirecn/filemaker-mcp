import { ToolDefinition } from './index.js';

export const getLayoutFieldsTool: ToolDefinition = {
  name: 'fm_get_layout_fields',
  description: 'Get field metadata for a specific FileMaker layout',
  inputSchema: {
    type: 'object',
    properties: {
      layout: {
        type: 'string',
        description: 'The FileMaker layout name',
      },
    },
    required: ['layout'],
  },
  handler: async (client, args) => {
    const { layout } = args as { layout: string };

    const fields = await client.getLayoutFields(layout);

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(fields, null, 2),
        },
      ],
    };
  },
};
