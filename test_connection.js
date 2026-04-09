#!/usr/bin/env node

import { FileMakerClient } from './dist/filemaker/client.js';

const client = new FileMakerClient({
  host: 'http://star-rc.net',
  database: 'DMS',
  username: 'master',
  password: 'Dataon4jd82Master785410'
});

console.log('Testing FileMaker connection...');

try {
  // Try to list layouts (this will trigger authentication)
  console.log('1. Listing layouts...');
  const layouts = await client.listLayouts();
  console.log('   ✓ Authentication successful!');
  console.log('   ✓ Found layouts:', layouts.length);
  layouts.slice(0, 5).forEach(l => console.log(`     - ${l}`));
  if (layouts.length > 5) {
    console.log(`     ... and ${layouts.length - 5} more`);
  }

  // Try to get layout metadata for the first layout
  if (layouts && layouts.length > 0) {
    const layoutName = layouts[0];
    console.log(`\n2. Getting fields for layout: "${layoutName}"...`);
    const fields = await client.getLayoutFields(layoutName);
    console.log('   ✓ Found fields:', fields.length);
    fields.slice(0, 5).forEach(f => console.log(`     - ${f.name} (${f.type})`));
    if (fields.length > 5) {
      console.log(`     ... and ${fields.length - 5} more`);
    }
  }

  console.log('\n✅ Connection test PASSED!');
  process.exit(0);

} catch (error) {
  console.error('\n❌ Connection test FAILED:');
  console.error('   Error:', error.message);
  if (error.cause) {
    console.error('   Cause:', error.cause);
  }
  process.exit(1);
}
