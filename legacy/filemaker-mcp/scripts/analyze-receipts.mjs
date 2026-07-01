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
    console.log('=== 新疆瑞网科技有限公司 收款数据详细分析 ===\n');
    
    // 获取所有收款记录
    const result = await client.findRecords('收款记录', {}, 1000, 1);
    
    // 筛选出新疆瑞网的所有收款记录
    const xinjiangReceipts = result.data.filter(record => {
      const companyName = record.fieldData['公司名称'];
      return companyName && companyName.includes('新疆瑞网');
    });
    
    // 新疆瑞网的实际合同金额
    const contractsResult = await client.findRecords('合同', {}, 1000, 1);
    const xinjiangContracts = contractsResult.data.filter(record => {
      const customerName = record.fieldData['客户名称'];
      return customerName && customerName.includes('新疆瑞网');
    });
    
    console.log('【一、实际签署的合同情况】\n');
    let totalContractAmount = 0;
    xinjiangContracts.forEach((record, idx) => {
      const f = record.fieldData;
      const amount = parseFloat(f['合同金额'] || 0);
      totalContractAmount += amount;
      console.log(`合同 ${idx + 1}:`);
      console.log(`  项目名称: ${f['项目名称']}`);
      console.log(`  合同金额: ¥${amount.toLocaleString('zh-CN', {minimumFractionDigits: 2})}`);
      console.log(`  签订日期: ${f['签订日期'] || '(未填写)'}`);
      console.log(`  合同类型: ${f['合同类型'] || '(未填写)'}`);
      console.log('');
    });
    console.log(`实际合同总额: ¥${totalContractAmount.toLocaleString('zh-CN', {minimumFractionDigits: 2})}\n`);
    
    console.log('【二、收款记录详情】\n');
    console.log(`系统中收款记录数: ${xinjiangReceipts.length} 条\n`);
    
    // 显示原始收款记录
    console.log('原始收款记录:');
    xinjiangReceipts.forEach((record, idx) => {
      const f = record.fieldData;
      console.log(`  ${idx + 1}. 记录ID:${record.recordId} | 金额:¥${parseFloat(f['金额']||0).toLocaleString()} | 合同:${f['对应合同']||'(无)'} | 日期:${f['日期']||'(无)'} | 创建:${f['zCreateTimestamp']||'(无)'}`);
    });
    
    // 分析可能的重复
    console.log('\n【三、数据重复分析】\n');
    
    // 按金额+日期+合同分组
    const groups = {};
    xinjiangReceipts.forEach(record => {
      const f = record.fieldData;
      const key = `${f['金额']}_${f['日期']}_${f['对应合同']}`;
      if (!groups[key]) {
        groups[key] = [];
      }
      groups[key].push(record);
    });
    
    console.log('按金额+日期+合同分组:');
    Object.entries(groups).forEach(([key, records]) => {
      const [amount, date, contract] = key.split('_');
      console.log(`\n组合: 金额¥${amount}, 日期${date}, 合同${contract}`);
      console.log(`  出现次数: ${records.length} 次 (记录ID: ${records.map(r => r.recordId).join(', ')})`);
      if (records.length > 1) {
        console.log(`  ⚠️ 注意: 这笔收款被重复记录了 ${records.length} 次！`);
      }
    });
    
    // 计算去重后的收款
    let uniqueReceiptTotal = 0;
    Object.entries(groups).forEach(([key, records]) => {
      const [amount] = key.split('_');
      uniqueReceiptTotal += parseFloat(amount || 0);
    });
    
    console.log('\n【四、汇总对比】\n');
    console.log(`系统中记录的总收款: ¥3,177,000.00`);
    console.log(`去重后的实际收款:   ¥${uniqueReceiptTotal.toLocaleString('zh-CN', {minimumFractionDigits: 2})}`);
    console.log(`差异: ¥${(3177000 - uniqueReceiptTotal).toLocaleString('zh-CN', {minimumFractionDigits: 2})}`);
    console.log(`实际签署合同总额:   ¥${totalContractAmount.toLocaleString('zh-CN', {minimumFractionDigits: 2})}`);
    
    if (uniqueReceiptTotal > totalContractAmount) {
      console.log(`\n⚠️ 注意: 收款金额(${uniqueReceiptTotal.toLocaleString()})超过了合同总额(${totalContractAmount.toLocaleString()})`);
      console.log('可能原因:');
      console.log('  1. 收款记录中的"对应合同"是手动填写的编号，与实际合同记录不匹配');
      console.log('  2. 有预付款或押金类收款');
      console.log('  3. 收款记录数据有误');
    }
    
  } catch (error) {
    console.error('错误:', error.message);
    process.exit(1);
  }
}

main();
