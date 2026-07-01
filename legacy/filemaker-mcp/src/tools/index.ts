import { Tool } from '@modelcontextprotocol/sdk/types.js';
import { FileMakerClient } from '../filemaker/client.js';
import { findRecordsTool } from './findRecords.js';
import { getRecordTool } from './getRecord.js';
import { createRecordTool } from './createRecord.js';
import { updateRecordTool } from './updateRecord.js';
import { deleteRecordTool } from './deleteRecord.js';
import { runScriptTool } from './runScript.js';
import { listLayoutsTool } from './listLayouts.js';
import { getLayoutFieldsTool } from './getLayoutFields.js';

export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: Tool['inputSchema'];
  handler: (client: FileMakerClient, args: Record<string, unknown>) => Promise<{
    content: Array<{ type: string; text: string }>;
  }>;
}

export const tools: ToolDefinition[] = [
  findRecordsTool,
  getRecordTool,
  createRecordTool,
  updateRecordTool,
  deleteRecordTool,
  runScriptTool,
  listLayoutsTool,
  getLayoutFieldsTool,
];
