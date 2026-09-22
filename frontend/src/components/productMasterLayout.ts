/** Product editor sections and original FileMaker field bindings. */
export const nativeTabs = ['產品照片', '产品规格书', '生產注意事項'] as const;
export const removedTabs = ['报价参考', '开发进度', '產品BOM', '產品BOM排序', '產品庫存', '銷售紀錄', '紀錄檔案', '產能計算'] as const;
export const identityFields = ['product_sku', '系統產品編號', '產品名稱_中文', 'product_name', '審核', 'MOQ'];
export const priceFields = ['opencost', '組裝成本USD', '建議報價', '報價積數', '成本加成', 'Retail_Price_USD', '組裝成本', '其他成本估價', '匯率', '提成', '提成B', '時薪', '包裝總工錢', '總人工成本', '準備包裝工錢', '包裝工錢'];
export const fieldLabels: Record<string, string> = { 類別: '类别', 車子比例: '车子比例', 車款: '车型', 產品分類: '产品分类', Brand_ID: '品牌编号', Category: '目录分类', category1: '一级分类编号', category2: '二级分类编号', category3: '三级分类编号', ShowStock: '显示库存', 產品位置: '产品位置', 位置: '位置', 有現貨: '库存状态', 追加訂購的等級: '追加订购等级', lastOrderElapsedDays: '距上次下单天数', Upload_Date: '上架日期', 重量: '重量', 尺寸: '尺寸', 'N.W淨重': '净重', 'G.W毛重': '毛重', 產品平均CBM: '平均体积 · CBM', product_sku: 'SKU', product_name: '英文名称', 產品名稱_中文: '中文名称', 系統產品編號: '系统编号', 審核: '审核状态', MOQ: '最小起订量 · MOQ', opencost: 'opencost', Retail_Price_USD: '零售价格 · USD', 組裝成本USD: '组装成本 · USD', 提成: 'A 积分', 提成B: 'B 积分', Client: '客户', id_client: '客户编号', created_at: '建立日期', created_by: '建档人', updated_at: '修改日期', updated_by: '修改人', Product_intro_english: '英文产品介绍', G_W: '毛重', stock: '产品库存', Stock_USD: '库存金额 · USD', PrePaid_stock_USD: '预付库存 · USD', 新產品: '新产品', 加入目錄: '加入目录', 條形碼: '条形码', 客戶SKU: '客户 SKU', 法文名稱: '法文名称', 描述: '描述', Remarks: '备注', 附註: '附注', 應課稅: '应课税', 報價紀錄: '报价纪录', 關聯編號_Price: '关联编号 · 报价', 建議報價: '建议报价', 報價積數: '报价积数', 成本加成: '成本加成', 匯率: '汇率', 組裝成本: '组装成本', 其他成本估價: '其他成本估价', '彩盒尺寸 長': '彩盒长', '彩盒尺寸 寬': '彩盒宽', '彩盒尺寸 高': '彩盒高', 彩盒尺寸CBM: '彩盒 CBM', '外箱尺寸 長': '外箱长', '外箱尺寸 寬': '外箱宽', '外箱尺寸 高': '外箱高', 外箱尺寸CBM: '外箱 CBM', '車款 車型 A': '适配车型 A', '車款 車型 B': '适配车型 B', '車款 車型 C': '适配车型 C', '車款 車型 D': '适配车型 D' };
export const sectionFields: Record<string, string[]> = {
  '开发进度': ['status', 'status_记录', '新產品', 'Newitem', 'ID_項目單', 'Upload_Date', 'Client', 'id_client', '客戶SKU', 'Category', 'category1', 'category2', 'category3', '產品分類', '類別', 'Brand_ID', '車子比例', '車款', '車款 車型 A', '車款 車型 B', '車款 車型 C', '車款 車型 D', '尺寸', '重量', '條形碼', '法文名稱', 'Product_intro_english', '描述', 'Remarks', '附註'],
  '报价参考': [...priceFields, '報價紀錄', '關聯編號_Price', '應課稅', '下單數量', '訂單數量', '彩盒尺寸 長', '彩盒尺寸 寬', '彩盒尺寸 高', '彩盒尺寸CBM', '外箱尺寸 長', '外箱尺寸 寬', '外箱尺寸 高', '外箱尺寸CBM', 'N.W淨重', 'G.W毛重', '產品平均CBM'],
  '產品BOM': ['BOM計數', '關聯編號'],
  '產品BOM排序': ['排序選取'],
  '產品庫存': ['stock', 'Stock_USD', 'PrePaid_stock_USD', 'ShowStock', '有現貨', '產品位置', '位置', 'lastOrderElapsedDays', '追加訂購的等級'],
  '產品照片': ['有圖沒圖', '注意事項', 'img_url'],
  '銷售紀錄': ['銷售紀錄'],
  '紀錄檔案': ['產品紀錄', '修改記錄', 'created_by', 'created_at', 'updated_by', 'updated_at'],
  '生產注意事項': ['生產注意事項', '生產日期', '包裝檢查', '標籤規格', '標籤規格後'],
  '產能計算': ['準備工時數量', '準備工時分', '準備工時秒', '準備工時單包', '準備工時單包驗證', '包裝工時分', '包裝工時秒', '包裝工時單包', '包裝工時單包驗證', '包裝總工時'],
  '產品附件': ['選取的文件'],
};
export const productPhotoFields = ['image_main', ...Array.from({ length: 17 }, (_, i) => `檔案 ${i + 2} | 容器`)];
export function assetGroup(name: string): string {
  if (productPhotoFields.includes(name)) return '產品照片';
  if (['產品規格書', '產品規格書2'].includes(name)) return '产品规格书';
  if (/^銷售紀錄照片/.test(name)) return '銷售紀錄';
  if (['彩盒', '外紙箱', '貼紙', '標籤檔案', '標籤檔案後', '發料標籤檔案'].includes(name)) return '包装与标签';
  return '產品附件';
}

// Sizes are stable while typing, based on field semantics and the migrated catalog profile.
export const recordMetaFields = ['created_by', 'created_at', 'updated_by', 'updated_at'];
export const draftFlags: Record<string, string> = { 加入目錄: '1' };
export function fieldPresentation(field: { name: string; result: string }, isCheckbox = false) {
  if (recordMetaFields.includes(field.name)) return 'meta';
  if (field.name === 'ID') return 'identifier';
  if (isCheckbox || field.name in draftFlags) return 'flag';
  if (/描述|事項|紀錄|記錄|记录|Remarks|附註|intro|img_url/i.test(field.name)) return 'notes';
  if (/名稱|^product_name$/i.test(field.name)) return 'name';
  if (field.name === 'Client') return 'customer';
  if (field.result === 'number' || ['id_client', '審核', '有圖沒圖', '有現貨'].includes(field.name)) return 'compact';
  return 'standard';
}

// Product-owned business fields are grouped independently of removed portal tabs.
// Review status follows the identifiers and is aligned to the right of the first row.
export const basicSections: Record<string, string[]> = {
  '产品信息': ['product_sku', '系統產品編號', '審核', '客戶SKU', '條形碼', '產品名稱_中文', 'product_name', '法文名稱', 'Client', 'id_client'],
  '分类与适配': ['類別', '車子比例', '車款', '車款 車型 A', '車款 車型 B', '車款 車型 C', '車款 車型 D', '產品分類', 'Brand_ID', 'Category', 'category1', 'category2', 'category3', '加入目錄', 'Upload_Date'],
  '尺寸与重量': ['尺寸', '重量', 'N.W淨重', 'G.W毛重', '彩盒尺寸 長', '彩盒尺寸 寬', '彩盒尺寸 高', '彩盒尺寸CBM', '外箱尺寸 長', '外箱尺寸 寬', '外箱尺寸 高', '外箱尺寸CBM', '產品平均CBM'],
  '库存信息': ['stock', '有現貨', 'ShowStock', '產品位置', '位置', '追加訂購的等級', 'lastOrderElapsedDays', 'Stock_USD', 'PrePaid_stock_USD'],
  '报价信息': ['MOQ', 'Retail_Price_USD', '建議報價', 'opencost', '組裝成本USD', '組裝成本', '其他成本估價', '匯率', '成本加成', '報價積數', '應課稅', '提成', '提成B', '報價紀錄', '關聯編號_Price'],
  '描述与备注': ['Product_intro_english', '描述', 'Remarks', '附註'],
};

/** Fields that belong to one measurement and must stay on one row, with the value the base derives. */
export type MeasureGroup = { title: string; unit?: string; fields: string[]; separators?: string[]; derived?: string; derivedLabel?: string; note?: string };
export const measureGroups: Record<string, MeasureGroup[]> = {
  '尺寸与重量': [
    { title: '彩盒尺寸', unit: 'cm', fields: ['彩盒尺寸 長', '彩盒尺寸 寬', '彩盒尺寸 高'], separators: ['×', '×'], derived: '彩盒尺寸CBM', derivedLabel: 'CBM', note: '长 · 宽 · 高' },
    { title: '外箱尺寸', unit: 'cm', fields: ['外箱尺寸 長', '外箱尺寸 寬', '外箱尺寸 高'], separators: ['×', '×'], derived: '外箱尺寸CBM', derivedLabel: 'CBM', note: '长 · 宽 · 高' },
    { title: '重量', fields: ['重量', 'N.W淨重', 'G.W毛重'], separators: ['g', '净 kg'], note: '单件 g · 净重 kg · 毛重 kg' },
  ],
};

/** 报价信息 reads as three bands instead of one wall of numbers. */
export const priceBands: Array<{ title: string; fields: string[] }> = [
  { title: '售价', fields: ['Retail_Price_USD', 'MOQ', '建議報價', '報價積數'] },
  { title: '成本', fields: ['opencost', '其他成本估價', '組裝成本USD', '組裝成本'] },
  { title: '换算与提成', fields: ['匯率', '成本加成', '提成', '提成B'] },
];

/** Repeating or reference-only positions start folded so empty slots stop eating a row each. */
export const foldedGroups: Record<string, Array<{ title: string; fields: string[]; hint: string }>> = {
  '分类与适配': [{ title: '适配车型 A–D', fields: ['車款 車型 A', '車款 車型 B', '車款 車型 C', '車款 車型 D'], hint: '四个重复位置，展开编辑' }],
  '报价信息': [{ title: '报价纪录 · 应课税 · 关联编号', fields: ['報價紀錄', '應課稅', '關聯編號_Price'], hint: '只读参考，展开查看' }],
};

const basicSharedFields = new Set([...Object.values(basicSections).flat(), ...recordMetaFields]);
const removedEditorFields = new Set(removedTabs.flatMap(tab => sectionFields[tab]).filter(name => !basicSharedFields.has(name)));
export function isEditorField(name: string): boolean {
  return !['有圖沒圖', 'img_url', 'qrcode', '選取的文件', '文件1', '文件2', '說明書', '選取的文件 | 容器'].includes(name) && !/^檔案 (?:19|20) \| 容器$/.test(name) && !removedEditorFields.has(name) && !/^銷售紀錄照片/.test(name);
}
