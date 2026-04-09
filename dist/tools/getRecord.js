export const getRecordTool = {
    name: 'fm_get_record',
    description: 'Get a single record by its ID from a FileMaker layout',
    inputSchema: {
        type: 'object',
        properties: {
            layout: {
                type: 'string',
                description: 'The FileMaker layout name',
            },
            recordId: {
                type: 'string',
                description: 'The internal FileMaker record ID',
            },
        },
        required: ['layout', 'recordId'],
    },
    handler: async (client, args) => {
        const { layout, recordId } = args;
        const record = await client.getRecord(layout, recordId);
        return {
            content: [
                {
                    type: 'text',
                    text: JSON.stringify(record, null, 2),
                },
            ],
        };
    },
};
//# sourceMappingURL=getRecord.js.map