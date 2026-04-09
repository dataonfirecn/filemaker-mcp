# FileMaker MCP Server

A Model Context Protocol (MCP) server that enables AI assistants to interact with FileMaker Pro databases via the FileMaker Data API.

## Features

- **Query Records**: Search and retrieve records from any layout
- **Create Records**: Add new records with field data
- **Update Records**: Modify existing records
- **Delete Records**: Remove records from the database
- **Run Scripts**: Execute FileMaker scripts with optional parameters
- **Schema Discovery**: List layouts and inspect field metadata

## Requirements

- FileMaker Server 18 or later
- FileMaker Data API enabled
- Node.js 18+ and npm

## Installation

```bash
npm install
npm run build
```

## Configuration

Create a `.env` file with your FileMaker credentials:

```bash
cp .env.example .env
```

Edit `.env` with your server details:

```
FILEMAKER_HOST=https://your-filemaker-server.com
FILEMAKER_DATABASE=YourDatabaseName
FILEMAKER_USERNAME=api_user
FILEMAKER_PASSWORD=your_password
```

## Usage

### Running the Server

```bash
npm start
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `fm_find_records` | Find records with query criteria |
| `fm_get_record` | Get a single record by ID |
| `fm_create_record` | Create a new record |
| `fm_update_record` | Update an existing record |
| `fm_delete_record` | Delete a record |
| `fm_run_script` | Execute a FileMaker script |
| `fm_list_layouts` | List all available layouts |
| `fm_get_layout_fields` | Get field metadata for a layout |

## Development

```bash
# Watch mode for development
npm run dev

# Type checking
npm run check

# Run tests
npm test
```

## License

MIT

## Deployment

For detailed installation and configuration instructions, see [DEPLOYMENT.md](DEPLOYMENT.md).
