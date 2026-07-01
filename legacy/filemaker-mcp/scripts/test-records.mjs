import { FileMakerClient } from '../dist/filemaker/client.js';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));

// Load .env
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

// Pick a few layouts likely to have real business records
const layoutsToTry = ['客户列表', 'Products', '客户资料', '公司資訊', '厂商列表'];

for (const layout of layoutsToTry) {
  console.log(`\n=== 尝试查询布局: "${layout}" ===`);
  try {
    const fields = await client.getLayoutFields(layout);
    console.log(`字段数: ${fields.length}`);
    console.log('前5个字段:', fields.slice(0, 5).map(f => f.name).join(', '));

    const result = await client.findRecords(layout, {}, 5, 1);
    console.log(`找到记录数 (foundCount): ${result.foundCount}, 返回: ${result.returnedCount}`);
    if (result.data.length > 0) {
      console.log('第一条记录示例:');
      const fd = result.data[0].fieldData;
      const keys = Object.keys(fd).slice(0, 8);
      for (const k of keys) {
        const v = String(fd[k]).slice(0, 60);
        console.log(`  ${k}: ${v}`);
      }
    } else {
      console.log('(布局存在但没有记录)');
    }
  } catch (err) {
    console.log(`查询失败: ${err.message}`);
  }
}