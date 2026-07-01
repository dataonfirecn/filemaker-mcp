import { FileMakerClient } from '../dist/filemaker/client.js';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));

// Load environment variables from .env file
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
    console.log('正在查询合同数据，统计客户累积合同金额...\n');
    
    // 获取所有合同记录
    const result = await client.findRecords('合同', {}, 1000, 1);
    console.log(`共获取 ${result.data.length} 条合同记录\n`);
    
    // 按客户名称累加合同金额
    const customerAmounts = {};
    
    for (const record of result.data) {
      const fieldData = record.fieldData;
      const customerName = fieldData['客户名称'];
      const contractAmount = parseFloat(fieldData['合同金额']) || 0;
      
      if (customerName) {
        if (!customerAmounts[customerName]) {
          customerAmounts[customerName] = {
            totalAmount: 0,
            contractCount: 0,
            contracts: []
          };
        }
        customerAmounts[customerName].totalAmount += contractAmount;
        customerAmounts[customerName].contractCount += 1;
        customerAmounts[customerName].contracts.push({
          project: fieldData['项目名称'],
          amount: contractAmount,
          date: fieldData['签订日期'],
          type: fieldData['合同类型']
        });
      }
    }
    
    // 转换为数组并排序（按累积金额降序）
    const sortedCustomers = Object.entries(customerAmounts)
      .map(([name, data]) => ({
        name,
        totalAmount: data.totalAmount,
        contractCount: data.contractCount,
        contracts: data.contracts
      }))
      .sort((a, b) => b.totalAmount - a.totalAmount);
    
    console.log('=== 累积签合同金额最多的客户 TOP 10 ===\n');
    
    sortedCustomers.slice(0, 10).forEach((customer, index) => {
      console.log(`${index + 1}. ${customer.name}`);
      console.log(`   累积合同金额: ¥${customer.totalAmount.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
      console.log(`   合同数量: ${customer.contractCount} 个`);
      console.log('');
    });
    
    // 显示第一名详情
    if (sortedCustomers.length > 0) {
      const top1 = sortedCustomers[0];
      console.log('\n=== 🏆 第一名客户详情 ===');
      console.log(`客户名称: ${top1.name}`);
      console.log(`累积合同金额: ¥${top1.totalAmount.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
      console.log(`合同数量: ${top1.contractCount} 个`);
      console.log('\n合同明细:');
      top1.contracts.forEach((contract, idx) => {
        console.log(`  ${idx + 1}. ${contract.project || '(无项目名称)'}`);
        console.log(`     金额: ¥${contract.amount.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
        console.log(`     日期: ${contract.date || '(未填写)'}`);
        console.log(`     类型: ${contract.type || '(未填写)'}`);
      });
    }

    console.log(`\n共统计 ${sortedCustomers.length} 个客户`);

  } catch (error) {
    console.error('错误:', error.message);
    console.error(error.stack);
    process.exit(1);
  }
}

main();
