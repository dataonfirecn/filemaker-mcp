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
    console.log('正在查询收款记录，统计客户累积收款金额...\n');
    
    // 获取所有收款记录
    const result = await client.findRecords('收款记录', {}, 1000, 1);
    console.log(`共获取 ${result.data.length} 条收款记录\n`);
    
    // 按公司名称累加收款金额
    const customerReceipts = {};
    
    for (const record of result.data) {
      const fieldData = record.fieldData;
      const companyName = fieldData['公司名称'];
      const amount = parseFloat(fieldData['金额']) || 0;
      
      if (companyName && amount > 0) {
        if (!customerReceipts[companyName]) {
          customerReceipts[companyName] = {
            totalReceipt: 0,
            receiptCount: 0,
            receipts: []
          };
        }
        customerReceipts[companyName].totalReceipt += amount;
        customerReceipts[companyName].receiptCount += 1;
        customerReceipts[companyName].receipts.push({
          contract: fieldData['对应合同'],
          amount: amount,
          date: fieldData['日期'],
          method: fieldData['付款方式']
        });
      }
    }
    
    // 转换为数组并排序（按累积收款降序）
    const sortedCustomers = Object.entries(customerReceipts)
      .map(([name, data]) => ({
        name,
        totalReceipt: data.totalReceipt,
        receiptCount: data.receiptCount,
        receipts: data.receipts
      }))
      .sort((a, b) => b.totalReceipt - a.totalReceipt);
    
    console.log('=== 💰 累积合同收款金额最多的客户 TOP 5 ===\n');
    
    sortedCustomers.slice(0, 5).forEach((customer, index) => {
      console.log(`${index + 1}. ${customer.name}`);
      console.log(`   累积收款金额: ¥${customer.totalReceipt.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
      console.log(`   收款笔数: ${customer.receiptCount} 笔`);
      console.log('');
    });
    
    // 显示前5名详情
    console.log('\n=== TOP 5 客户收款详情 ===\n');
    
    sortedCustomers.slice(0, 5).forEach((customer, index) => {
      console.log(`\n--- 第 ${index + 1} 名: ${customer.name} ---`);
      console.log(`累积收款金额: ¥${customer.totalReceipt.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
      console.log(`收款笔数: ${customer.receiptCount} 笔`);
      console.log('收款明细:');
      customer.receipts.slice(0, 5).forEach((receipt, idx) => {
        console.log(`  ${idx + 1}. 金额: ¥${receipt.amount.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
        console.log(`     日期: ${receipt.date || '(未填写)'}`);
        console.log(`     付款方式: ${receipt.method || '(未填写)'}`);
        console.log(`     对应合同: ${receipt.contract || '(未填写)'}`);
      });
      if (customer.receipts.length > 5) {
        console.log(`  ... 还有 ${customer.receipts.length - 5} 笔收款`);
      }
    });

    console.log(`\n\n共统计 ${sortedCustomers.length} 个有收款记录的客户`);

  } catch (error) {
    console.error('错误:', error.message);
    console.error(error.stack);
    process.exit(1);
  }
}

main();
