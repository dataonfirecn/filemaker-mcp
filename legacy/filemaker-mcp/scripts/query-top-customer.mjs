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
    console.log('正在查询客户和合同布局的字段信息...\n');
    
    // 查看客户布局的字段
    console.log('=== 客户布局字段 ===');
    try {
      const customerFields = await client.getLayoutFields('客户');
      console.log(`字段数: ${customerFields.length}`);
      customerFields.forEach((field, idx) => {
        console.log(`  ${idx + 1}. ${field.name} (${field.type}, ${field.result})`);
      });
    } catch (e) {
      console.log('无法获取客户布局字段:', e.message);
    }
    
    console.log('\n=== 合同布局字段 ===');
    try {
      const contractFields = await client.getLayoutFields('合同');
      console.log(`字段数: ${contractFields.length}`);
      contractFields.forEach((field, idx) => {
        console.log(`  ${idx + 1}. ${field.name} (${field.type}, ${field.result})`);
      });
    } catch (e) {
      console.log('无法获取合同布局字段:', e.message);
    }
    
    console.log('\n=== 合同内容布局字段 ===');
    try {
      const contractContentFields = await client.getLayoutFields('合同内容');
      console.log(`字段数: ${contractContentFields.length}`);
      contractContentFields.forEach((field, idx) => {
        console.log(`  ${idx + 1}. ${field.name} (${field.type}, ${field.result})`);
      });
    } catch (e) {
      console.log('无法获取合同内容布局字段:', e.message);
    }

    console.log('\n=== 合同跟踪表布局字段 ===');
    try {
      const trackFields = await client.getLayoutFields('合同跟踪表');
      console.log(`字段数: ${trackFields.length}`);
      trackFields.forEach((field, idx) => {
        console.log(`  ${idx + 1}. ${field.name} (${field.type}, ${field.result})`);
      });
    } catch (e) {
      console.log('无法获取合同跟踪表布局字段:', e.message);
    }

  } catch (error) {
    console.error('错误:', error.message);
    process.exit(1);
  }
}

main();
