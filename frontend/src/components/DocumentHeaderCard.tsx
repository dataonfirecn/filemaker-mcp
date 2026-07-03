import { Check, Copy } from "lucide-react";
import { useState } from "react";
import type { CalcStatus, ProductInfo } from "../types";

export type DocumentHeaderCardProps = {
  calculationPrimaryId: string;
  calculationDate: string | null;
  calcStatus: CalcStatus;
  product: ProductInfo | null;
  generateQty: number | null;
  formatDateTime: (value: string | null | undefined) => string;
  formatQty: (value: number | string | null | undefined) => string;
};

export default function DocumentHeaderCard({
  calculationPrimaryId,
  calculationDate,
  calcStatus,
  product,
  generateQty,
  formatDateTime,
  formatQty
}: DocumentHeaderCardProps) {
  const [copied, setCopied] = useState(false);
  const sourceProductName = product?.productNameCn || product?.productName || "-";

  function copyId() {
    if (!calculationPrimaryId || calculationPrimaryId === "-") return;

    // Show immediate visual feedback
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);

    // Best-effort clipboard write
    if (navigator.clipboard && window.isSecureContext) {
      void navigator.clipboard.writeText(calculationPrimaryId);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = calculationPrimaryId;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      try {
        document.execCommand("copy");
      } catch {
        // Ignore
      }
      document.body.removeChild(textarea);
    }
  }

  return (
    <>
      <section className="document-card document-title-card">
        <div className="document-title-line">
          <h2>BOM 计算单</h2>
        </div>

        <div className="document-meta-line">
          <div className="document-id-block">
            <span className="meta-label">ID</span>
            <button
              className="doc-id copyable"
              title={copied ? "已复制" : "点击复制"}
              onClick={copyId}
              disabled={!calculationPrimaryId || calculationPrimaryId === "-"}
              aria-label="复制 ID"
            >
              <span>{calculationPrimaryId}</span>
              {copied ? <Check size={16} /> : <Copy size={16} />}
            </button>
          </div>
          <div>
            <span className="meta-label">日期</span>
            <strong className="meta-value">{formatDateTime(calculationDate)}</strong>
          </div>
          <div className="document-status-cell">
            <span className="meta-label">状态</span>
            <strong className="meta-value">{calcStatus}</strong>
          </div>
        </div>
      </section>

      <section className="document-source-card">
        <div className="source-card-head">
          <h3>计算来源</h3>
        </div>
        <div className="source-equation">
          <div className="equation-product">
            <div className="equation-product-code">
              <span>产品编号</span>
              <strong>{product?.productSku ?? "-"}</strong>
            </div>
            <div className="equation-product-name">
              <b>{sourceProductName}</b>
              <em>{product?.productName || "-"}</em>
            </div>
          </div>
          <div className="equation-symbol" aria-label="乘以">
            ×
          </div>
          <div className="equation-qty">
            <span>数量</span>
            <strong>{generateQty ? formatQty(generateQty) : "-"}</strong>
          </div>
        </div>
      </section>
    </>
  );
}
