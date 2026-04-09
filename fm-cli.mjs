#!/usr/bin/env node
/**
 * FileMaker MCP CLI
 * 直接查询 FileMaker 数据库
 */

import { FileMakerClient } from './dist/filemaker/client.js';

const client = new FileMakerClient({
  host: 'https://apitest.dataonfire.cn/',
  database: 'MJStar',
  username: 'api',
  password: 'master',
});

// 获取命令行参数
const [, , command, ...args] = process.argv;

async function main() {
  try {
    switch (command) {
      case 'layouts':
        const layouts = await client.listLayouts();
        console.log('可用布局:');
        layouts.forEach(l => console.log(`  - ${l}`));
        break;

      case 'find':
        const [layout, ...queryParts] = args;
        const query = queryParts.length > 0 
          ? { [queryParts[0]]: queryParts[1] || '' }
          : {};
        const result = await client.findRecords(layout, query);
        console.log(JSON.stringify(result, null, 2));
        break;

      case 'get':
        const [l, recordId] = args;
        const record = await client.getRecord(l, recordId);
        console.log(JSON.stringify(record, null, 2));
        break;

      default:
        console.log(`
用法:
  node fm-cli.mjs layouts                    # 列出所有布局
  node fm-cli.mjs find <layout> [field] [value]   # 查询记录
  node fm-cli.mjs get <layout> <recordId>     # 获取单条记录

示例:
  node fm-cli.mjs layouts
  node fm-cli.mjs find 样品_list
  node fm-cli.mjs find 样品_list 样品名称 "*无人机*"
        `);
    }
  } catch (error) {
    console.error('错误:', error.message);
    process.exit(1);
  }
}

main();
