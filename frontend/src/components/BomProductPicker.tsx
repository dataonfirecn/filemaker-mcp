import { Search } from "lucide-react";

export type BomProductPickerProps = {
  sku: string;
  defaultSku?: string;
  loading?: boolean;
  onSkuChange: (value: string) => void;
  onLoad: () => void;
};

/**
 * BOM 计算单页工作台的第 1 阶段：手动输入产品 SKU 并加载 BOM。
 * 不依赖后端产品列表；会话中的默认 SKU 仅用作 placeholder 提示。
 */
export default function BomProductPicker({
  sku,
  defaultSku,
  loading,
  onSkuChange,
  onLoad
}: BomProductPickerProps) {
  return (
    <section className="card bom-stage bom-stage-select">
      <div className="card-head">
        <div className="card-head-left">
          <h3>第 1 步 · 选择产品</h3>
          <span className="record-count">输入产品编号读取 BOM</span>
        </div>
      </div>
      <div className="card-toolbar bom-picker-row">
        <label className="grid-search bom-sku-input" htmlFor="bomSkuInput">
          <Search size={15} />
          <input
            id="bomSkuInput"
            value={sku}
            onChange={(event) => onSkuChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !loading) onLoad();
            }}
            placeholder={defaultSku ? `例如 ${defaultSku}` : "输入产品编号"}
            autoComplete="off"
            autoFocus
          />
        </label>
        <button className="btn primary" type="button" onClick={onLoad} disabled={loading || !sku.trim()}>
          {loading ? "加载中…" : "加载 BOM"}
        </button>
      </div>
    </section>
  );
}
