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
    console.log('正在连接 FileMaker 数据库...');
    console.log(`服务器: ${envVars.FILEMAKER_HOST}`);
    console.log(`数据库: ${envVars.FILEMAKER_DATABASE}`);
    console.log('');

    // 获取所有布局
    console.log('=== 数据库中的所有布局 (Layouts) ===');
    const layouts = await client.listLayouts();
    console.log(`共找到 ${layouts.length} 个布局:\n`);
    
    layouts.forEach((layout, index) => {
      console.log(`${index + 1}. ${layout}`);
    });

    console.log('\n=== 各布局的字段信息 ===\n');
    
    // 获取前5个布局的字段信息
    const layoutsToCheck = layouts.slice(0, 5);
    
    for (const layout of layoutsToCheck) {
      try {
        console.log(`\n--- 布局: "${layout}" ---`);
        const fields = await client.getLayoutFields(layout);
        
        if (fields && fields.length > 0) {
          console.log(`字段数: ${fields.length}`);
          console.log('字段列表:');
          fields.slice(0, 10).forEach((field, idx) => {
            console.log(`  ${idx + 1}. ${field.name} (${field.type || 'unknown'}, ${field.result || 'unknown'})`);
          });
          if (fields.length > 10) {
            console.log(`  ... 还有 ${fields.length - 10} 个字段`);
          }
        } else {
          console.log('  (无字段信息或无法访问此布局)');
        }
      } catch (err) {
        console.log(`  无法获取此布局的字段信息: ${err.message}`);
      }
    }

    console.log('\n=== 查询完成 ===');
  } catch (error) {
    console.error('错误:', error.message);
    process.exit(1);
  }
}

main();
