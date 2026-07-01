import { readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

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

const host = envVars.FILEMAKER_HOST;
const database = envVars.FILEMAKER_DATABASE;
const username = envVars.FILEMAKER_USERNAME;
const password = envVars.FILEMAKER_PASSWORD;

console.log('=== 配置信息 ===');
console.log('Host:', host);
console.log('Database:', database);
console.log('Username:', username);
console.log('Node version:', process.version);
console.log('');

async function testPing() {
  console.log('=== 1. 测试基础连通性 (GET host) ===');
  try {
    const res = await fetch(host, { method: 'GET' });
    console.log(`状态码: ${res.status}`);
    console.log(`响应头 content-type: ${res.headers.get('content-type')}`);
    const text = await res.text();
    console.log(`响应前200字符: ${text.slice(0, 200)}`);
  } catch (err) {
    console.log('基础连通性测试失败:');
    console.log('错误名:', err.name);
    console.log('错误信息:', err.message);
    if (err.cause) {
      console.log('cause:', err.cause.code || err.cause.message || err.cause);
    }
  }
  console.log('');
}

async function testAuth() {
  console.log('=== 2. 测试 FileMaker 认证 (获取 token) ===');
  const url = `${host}/fmi/data/v2/databases/${encodeURIComponent(database)}/sessions`;
  console.log('请求 URL:', url);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Basic ${btoa(`${username}:${password}`)}`,
      },
    });
    console.log(`状态码: ${res.status}`);
    const text = await res.text();
    console.log(`响应: ${text.slice(0, 500)}`);
  } catch (err) {
    console.log('认证请求失败:');
    console.log('错误名:', err.name);
    console.log('错误信息:', err.message);
    if (err.cause) {
      console.log('cause:', err.cause.code || err.cause.message || err.cause);
    }
  }
}

await testPing();
await testAuth();