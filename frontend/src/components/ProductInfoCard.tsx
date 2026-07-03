import type { ProductInfo } from "../types";

export type ProductInfoCardProps = {
  product: ProductInfo | null;
  fallbackSku: string;
  generateQty: number | null;
  formatQty: (value: number | string | null | undefined) => string;
};

export default function ProductInfoCard({
  product,
  fallbackSku,
  generateQty,
  formatQty
}: ProductInfoCardProps) {
  return (
    <section className="card product-info-card">
      <div className="product-info-grid">
        <div>
          <span className="meta-label">产品编号</span>
          <strong className="meta-value">{product?.productSku ?? fallbackSku}</strong>
        </div>
        <div>
          <span className="meta-label">中文名称</span>
          <strong className="meta-value">{product?.productNameCn || "-"}</strong>
        </div>
        <div className="wide">
          <span className="meta-label">英文名称</span>
          <strong className="meta-value">{product?.productName || "-"}</strong>
        </div>
        <div className="number-cell">
          <span className="meta-label">生成数量</span>
          <strong className="meta-value qty">{generateQty ? formatQty(generateQty) : "-"}</strong>
        </div>
      </div>
    </section>
  );
}
