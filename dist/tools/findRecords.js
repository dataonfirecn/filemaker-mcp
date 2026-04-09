export const findRecordsTool = {
    name: 'fm_find_records',
    description: 'Find records in a FileMaker layout using query criteria. Supports sorting, pagination (limit/offset), and field-based queries.',
    inputSchema: {
        type: 'object',
        properties: {
            layout: {
                type: 'string',
                description: 'The FileMaker layout name to query',
            },
            query: {
                type: 'object',
                description: 'Query criteria as key-value pairs (e.g., {"Status": "Active"})',
                default: {},
            },
            limit: {
                type: 'number',
                description: 'Maximum number of records to return',
                default: 100,
            },
            offset: {
                type: 'number',
                description: 'Starting record number for pagination (1-based)',
                default: 1,
            },
            sort: {
                type: 'array',
                description: 'Sort criteria. Each item has fieldName and sortOrder ("ascend" or "descend"). Example: [{"fieldName": "Amount", "sortOrder": "descend"}]',
                items: {
                    type: 'object',
                    properties: {
                        fieldName: {
                            type: 'string',
                            description: 'The field name to sort by',
                        },
                        sortOrder: {
                            type: 'string',
                            enum: ['ascend', 'descend'],
                            description: 'Sort direction: "ascend" for ascending, "descend" for descending',
                        },
                    },
                    required: ['fieldName', 'sortOrder'],
                },
            },
        },
        required: ['layout'],
    },
    handler: async (client, args) => {
        const { layout, query = {}, limit, offset, sort } = args;
        const result = await client.findRecords(layout, query, limit, offset, sort);
        return {
            content: [
                {
                    type: 'text',
                    text: JSON.stringify({
                        layout,
                        foundCount: result.foundCount,
                        returnedCount: result.returnedCount,
                        records: result.data,
                    }, null, 2),
                },
            ],
        };
    },
};
//# sourceMappingURL=findRecords.js.map