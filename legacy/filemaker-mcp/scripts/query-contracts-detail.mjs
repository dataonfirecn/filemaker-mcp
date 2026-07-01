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
    console.log('查询新疆瑞网科技有限公司相关合同信息...\n');
    
    // 获取所有合同记录
    const result = await client.findRecords('合同', {}, 1000, 1);
    
    // 查找客户名称包含新疆瑞网的合同
    const xinjiangContracts = result.data.filter(record => {
      const customerName = record.fieldData['客户名称'];
      return customerName && customerName.includes('新疆瑞网');
    });
    
    console.log(`找到 ${xinjiangContracts.length} 个相关合同\n`);
    
    if (xinjiangContracts.length === 0) {
      console.log('未找到客户名称包含"新疆瑞网"的合同，尝试通过项目名称查找...');
    }
    
    // 同时查找项目名可能相关的合同
    const contract2017052 = result.data.filter(r => r.fieldData['项目名称']?.includes('2017052') || r.recordId === '2017052');
    const contract2017079 = result.data.filter(r => r.fieldData['项目名称']?.includes('2017079') || r.recordId === '2017079');
    
    console.log('=== 新疆瑞网科技有限公司相关合同详情 ===\n');
    
    // 打印通过客户名找到的合同
    xinjiangContracts.forEach((record, idx) => {
      const f = record.fieldData;
      console.log(`--- 合同 ${idx + 1} ---`);
      console.log(`记录ID: ${record.recordId}`);
      console.log(`客户名称: ${f['客户名称']}`);
      console.log(`项目名称: ${f['项目名称']}`);
      console.log(`合同金额: ¥${parseFloat(f['合同金额'] || 0).toLocaleString('zh-CN', {minimumFractionDigits: 2})}`);
      console.log(`签订日期: ${f['签订日期'] || '(未填写)'}`);
      console.log(`签约人: ${f['签约人'] || '(未填写)'}`);
      console.log(`合同类型: ${f['合同类型'] || '(未填写)'}`);
      console.log(`状态: ${f['状态'] || '(未填写)'}`);
      console.log('');
    });
    
    // 查询所有合同记录中是否有ID为2017052或2017079的
    console.log('=== 查找特定合同编号 2017052 和 2017079 ===\n');
    
    for (const record of result.data) {
      if (record.recordId === '52' || record.recordId === '79' || 
          (record.fieldData['项目名称'] && (
            record.fieldData['项目名称'].includes('瑞网') || 
            record.fieldData['项目名称'].includes('2017052') ||
            record.fieldData['项目名称'].includes('2017079')
          ))) {
        const f = record.fieldData;
        console.log(`记录ID: ${record.recordId}`);
        console.log(`客户名称: ${f['客户名称']}`);
        console.log(`项目名称: ${f['项目名称']}`);
        console.log(`合同金额: ¥${parseFloat(f['合同金额'] || 0).toLocaleString('zh-CN', {minimumFractionDigits: 2})}`);
        console.log(`签订日期: ${f['签订日期'] || '(未填写)'}`);
        console.log('---');
      }
    }

  } catch (error) {
    console.error('错误:', error.message);
    console.error(error.stack);
    process.exit(1);
  }
}

main();
