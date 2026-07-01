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
    console.log('正在查询新疆瑞网科技有限公司的详细收款数据...\n');
    
    // 获取所有收款记录
    const result = await client.findRecords('收款记录', {}, 1000, 1);
    
    // 筛选出新疆瑞网的所有收款记录
    const xinjiangReceipts = result.data.filter(record => {
      const companyName = record.fieldData['公司名称'];
      return companyName && companyName.includes('新疆瑞网');
    });
    
    console.log(`共找到 ${xinjiangReceipts.length} 条收款记录\n`);
    
    // 整理明细数据
    const details = xinjiangReceipts.map(record => {
      const fieldData = record.fieldData;
      return {
        recordId: record.recordId,
        companyName: fieldData['公司名称'],
        amount: parseFloat(fieldData['金额']) || 0,
        date: fieldData['日期'],
        method: fieldData['付款方式'],
        contract: fieldData['对应合同'],
        invoice: fieldData['对应录入发票'],
        remark: fieldData['备注'],
        createTime: fieldData['zCreateTimestamp']
      };
    });
    
    // 按合同分组统计
    const contractSummary = {};
    let totalAmount = 0;
    
    details.forEach(item => {
      totalAmount += item.amount;
      
      const contractNo = item.contract || '(未指定合同)';
      if (!contractSummary[contractNo]) {
        contractSummary[contractNo] = {
          total: 0,
          count: 0,
          receipts: []
        };
      }
      contractSummary[contractNo].total += item.amount;
      contractSummary[contractNo].count += 1;
      contractSummary[contractNo].receipts.push(item);
    });
    
    // 打印汇总
    console.log('=== 新疆瑞网科技有限公司 - 收款汇总 ===\n');
    console.log(`总收款金额: ¥${totalAmount.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
    console.log(`收款笔数: ${details.length} 笔`);
    console.log(`涉及合同数: ${Object.keys(contractSummary).length} 个\n`);
    
    // 按合同显示汇总
    console.log('=== 按合同汇总 ===\n');
    Object.entries(contractSummary).forEach(([contract, data]) => {
      console.log(`合同编号: ${contract}`);
      console.log(`  收款金额小计: ¥${data.total.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
      console.log(`  收款笔数: ${data.count} 笔`);
      console.log('');
    });
    
    // 打印所有明细
    console.log('=== 收款明细清单 ===\n');
    
    details.forEach((item, index) => {
      console.log(`--- 第 ${index + 1} 笔 ---`);
      console.log(`记录ID: ${item.recordId}`);
      console.log(`公司名称: ${item.companyName}`);
      console.log(`收款金额: ¥${item.amount.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
      console.log(`收款日期: ${item.date || '(未填写)'}`);
      console.log(`付款方式: ${item.method || '(未填写)'}`);
      console.log(`对应合同: ${item.contract || '(未填写)'}`);
      console.log(`对应发票: ${item.invoice || '(未填写)'}`);
      console.log(`备注: ${item.remark || '(无)'}`);
      console.log(`创建时间: ${item.createTime || '(未填写)'}`);
      console.log('');
    });
    
    // 统计信息
    console.log('=== 统计信息 ===\n');
    console.log(`总收款金额: ¥${totalAmount.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
    console.log(`最大单笔: ¥${Math.max(...details.map(d => d.amount)).toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
    console.log(`最小单笔: ¥${Math.min(...details.map(d => d.amount)).toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
    console.log(`平均单笔: ¥${(totalAmount / details.length).toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);

  } catch (error) {
    console.error('错误:', error.message);
    console.error(error.stack);
    process.exit(1);
  }
}

main();
