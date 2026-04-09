export const deleteRecordTool = {
    name: 'fm_delete_record',
    description: 'Delete a record from a FileMaker layout',
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
        await client.deleteRecord(layout, recordId);
        return {
            content: [
                {
                    type: 'text',
                    text: `Record ${recordId} deleted successfully from layout ${layout}`,
                },
            ],
        };
    },
};
//# sourceMappingURL=deleteRecord.js.map