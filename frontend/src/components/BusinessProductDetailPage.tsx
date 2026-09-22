import { ArrowLeft } from "lucide-react";
import type { BusinessProductRow } from "../types";
import ProductMasterPage from "./ProductMasterPage";

export type BusinessProductDetailPageProps = {
  apiBase?: string;
  token: string;
  product: BusinessProductRow | null;
  loading?: boolean;
  formatQty: (value: number | string | null | undefined) => string;
  onBack: () => void;
};

export default function BusinessProductDetailPage({ apiBase = "", token, product, loading, onBack }: BusinessProductDetailPageProps) {
  return <>
    <div className="detail-nav-row">
      <button className="btn" type="button" onClick={onBack}><ArrowLeft size={16} />返回列表</button>
    </div>
    {loading ? <div className="empty-state" role="status">正在加载产品资料…</div>
      : product ? <ProductMasterPage key={product.recordId} apiBase={apiBase} token={token} initialRef={product.recordId} readOnly />
      : <div className="empty-state">未找到产品资料，请返回列表重新选择。</div>}
  </>;
}
