export const listLayoutsTool = {
    name: 'fm_list_layouts',
    description: 'List all available layouts in the FileMaker database',
    inputSchema: {
        type: 'object',
        properties: {},
    },
    handler: async (client) => {
        const layouts = await client.listLayouts();
        return {
            content: [
                {
                    type: 'text',
                    text: JSON.stringify(layouts, null, 2),
                },
            ],
        };
    },
};
//# sourceMappingURL=listLayouts.js.map