import { FileMakerClient } from '../dist/filemaker/client.js';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));

const envPath = join(__dirname, '..', '.env');
const envContent = readFileSync(envPath, 'utf-8');
const envVars = {};
for (const line of envContent.split('\n')) {
  const trimmed = line.trim();
  if (trimmed && !trimmed.startsWith('#')) {
    const [key, ...valueParts] = trimmed.split('=');
    if (key && valueParts.length > 0) {
      envVars[key.trim()] = valueParts.join('=').trim();
    }
  }
}

const client = new FileMakerClient({
  host: envVars.FILEMAKER_HOST,
  database: envVars.FILEMAKER_DATABASE,
  username: envVars.FILEMAKER_USERNAME,
  password: envVars.FILEMAKER_PASSWORD,
});

async function main() {
  try {
    console.log('正在查询客户数据，按累计合同收款排序...\n');
    
    // 获取所有客户记录，按累计合同收款降序排序
    const result = await client.findRecords('客户', {}, 1000, 1, [
      { fieldName: '累计合同收款', sortOrder: 'descend' }
    ]);
    
    console.log(`共获取 ${result.data.length} 个客户\n`);
    
    // 提取客户数据
    const customers = result.data.map(record => {
      const f = record.fieldData;
      return {
        recordId: record.recordId,
        name: f['客户名称'] || '(未命名)',
        type: f['公司类型'] || '(未分类)',
        totalReceipt: parseFloat(f['累计合同收款']) || 0,
        remark: f['备注'] || ''
      };
    });
    
    // 过滤掉收款为0的客户并取前10
    const topCustomers = customers
      .filter(c => c.totalReceipt > 0)
      .slice(0, 10);
    
    console.log('=== 💰 累计合同收款最多的客户 TOP 10 ===\n');
    
    console.log('排名 | 客户名称 | 公司类型 | 累计合同收款');
    console.log('--- | --- | --- | ---');
    
    topCustomers.forEach((c, idx) => {
      const rank = idx + 1;
      const medal = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : '  ';
      console.log(`${medal} ${rank} | ${c.name} | ${c.type} | ¥${c.totalReceipt.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
    });
    
    console.log('\n=== 详细信息 ===\n');
    
    topCustomers.forEach((c, idx) => {
      console.log(`--- 第 ${idx + 1} 名 ---`);
      console.log(`客户名称: ${c.name}`);
      console.log(`公司类型: ${c.type}`);
      console.log(`累计合同收款: ¥${c.totalReceipt.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
      if (c.remark) {
        console.log(`备注: ${c.remark}`);
      }
      console.log('');
    });
    
    // 统计
    const totalTop10 = topCustomers.reduce((sum, c) => sum + c.totalReceipt, 0);
    console.log('=== 统计 ===');
    console.log(`TOP 10 客户累计收款合计: ¥${totalTop10.toLocaleString('zh-CN', {minimumFractionDigits: 2})}`);
    console.log(`平均每家: ¥${(totalTop10 / topCustomers.length).toLocaleString('zh-CN', {minimumFractionDigits: 2})}`);
    
  } catch (error) {
    console.error('错误:', error.message);
    console.error(error.stack);
    process.exit(1);
  }
}

main();
