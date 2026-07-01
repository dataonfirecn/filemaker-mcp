# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FileMakerMCP is a Model Context Protocol (MCP) server that enables Claude to interact with FileMaker databases. It bridges FileMaker's Data API with AI assistants, allowing natural language querying and manipulation of FileMaker data.

## Development Commands

```bash
# Install dependencies
npm install

# Run development server with hot reload
npm run dev

# Type checking
npm run check

# Build for production
npm run build

# Run tests
npm test

# Run a single test file
npm test -- path/to/test.test.ts
```

## Architecture

The server follows the standard MCP SDK structure:

- **`src/index.ts`** - Main entry point, initializes the MCP server
- **`src/server.ts`** - MCP server setup with tool definitions
- **`src/tools/`** - Individual FileMaker tool implementations (queries, scripts, layouts, etc.)
- **`src/filemaker/`** - FileMaker Data API client wrapper

### Key Concepts

1. **MCP Tools** - Each FileMaker operation (find records, create record, run script) is exposed as an MCP tool
2. **Connection Pooling** - FileMaker API connections are reused across requests via a client pool
3. **Layout Mapping** - FileMaker layouts define the schema; tools introspect layouts to understand available fields
4. **Authentication** - Uses FileMaker Data API tokens with configurable refresh logic

## FileMaker API Integration

The server connects to FileMaker via the Data API (requires FileMaker Server 18+). Key configuration:

- `FILEMAKER_HOST` - FileMaker Server URL
- `FILEMAKER_DATABASE` - Target database name
- `FILEMAKER_USERNAME` / `FILEMAKER_PASSWORD` - API credentials
- `FILEMAKER_LAYOUT` - Default layout for queries

## Important Notes

- Always validate layout names before querying — FileMaker returns cryptic errors for invalid layouts
- The FileMaker Data API has rate limits; implement backoff for bulk operations
- Portal data requires special handling via `portal` query parameters
- Script results are returned as JSON strings; parse before exposing to users
