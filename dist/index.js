#!/usr/bin/env node
import { FileMakerMCPServer } from './server.js';
async function main() {
    const server = new FileMakerMCPServer();
    await server.run();
}
main().catch((error) => {
    console.error('Server error:', error);
    process.exit(1);
});
//# sourceMappingURL=index.js.map