import { ToolDefinition } from './index.js';

export const runScriptTool: ToolDefinition = {
  name: 'fm_run_script',
  description: 'Run a FileMaker script on a specified layout',
  inputSchema: {
    type: 'object',
    properties: {
      layout: {
        type: 'string',
        description: 'The FileMaker layout name',
      },
      scriptName: {
        type: 'string',
        description: 'The name of the script to run',
      },
      scriptParam: {
        type: 'string',
        description: 'Optional parameter to pass to the script',
      },
    },
    required: ['layout', 'scriptName'],
  },
  handler: async (client, args) => {
    const { layout, scriptName, scriptParam } = args as {
      layout: string;
      scriptName: string;
      scriptParam?: string;
    };

    const result = await client.runScript(layout, scriptName, scriptParam);

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
