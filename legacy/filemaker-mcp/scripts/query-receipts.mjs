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
    console.log('查看收款相关布局的字段信息...\n');
    
    // 查看收款记录布局
    console.log('=== 收款记录布局字段 ===');
    try {
      const fields = await client.getLayoutFields('收款记录');
      console.log(`字段数: ${fields.length}`);
      fields.forEach((field, idx) => {
        console.log(`  ${idx + 1}. ${field.name} (${field.type}, ${field.result})`);
      });
    } catch (e) {
      console.log('无法获取:', e.message);
    }
    
    console.log('\n=== @收款 布局字段 ===');
    try {
      const fields = await client.getLayoutFields('@收款');
      console.log(`字段数: ${fields.length}`);
      fields.forEach((field, idx) => {
        console.log(`  ${idx + 1}. ${field.name} (${field.type}, ${field.result})`);
      });
    } catch (e) {
      console.log('无法获取:', e.message);
    }
    
    console.log('\n=== 合同收款 布局字段 ===');
    try {
      const fields = await client.getLayoutFields('合同收款');
      console.log(`字段数: ${fields.length}`);
      fields.forEach((field, idx) => {
        console.log(`  ${idx + 1}. ${field.name} (${field.type}, ${field.result})`);
      });
    } catch (e) {
      console.log('无法获取:', e.message);
    }

    console.log('\n=== 合同跟踪表 布局字段 ===');
    try {
      const fields = await client.getLayoutFields('合同跟踪表');
      console.log(`字段数: ${fields.length}`);
      fields.forEach((field, idx) => {
        console.log(`  ${idx + 1}. ${field.name} (${field.type}, ${field.result})`);
      });
    } catch (e) {
      console.log('无法获取:', e.message);
    }

  } catch (error) {
    console.error('错误:', error.message);
    process.exit(1);
  }
}

main();
