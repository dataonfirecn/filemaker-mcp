export const getLayoutFieldsTool = {
    name: 'fm_get_layout_fields',
    description: 'Get field metadata for a specific FileMaker layout',
    inputSchema: {
        type: 'object',
        properties: {
            layout: {
                type: 'string',
                description: 'The FileMaker layout name',
            },
        },
        required: ['layout'],
    },
    handler: async (client, args) => {
        const { layout } = args;
        const fields = await client.getLayoutFields(layout);
        return {
            content: [
                {
                    type: 'text',
                    text: JSON.stringify(fields, null, 2),
                },
            ],
        };
    },
};
//# sourceMappingURL=getLayoutFields.js.map