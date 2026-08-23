import { ArrowLeft, ExternalLink, ImageIcon, Info, Link2, QrCode, Table2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { BusinessProductFieldGroup, BusinessProductPortalGroup, BusinessProductRow } from "../types";

export type BusinessProductDetailPageProps = {
  apiBase?: string;
  token: string;
  product: BusinessProductRow | null;
  loading?: boolean;
  formatQty: (value: number | string | null | undefined) => string;
  onBack: () => void;
};

type DetailItem = {
  label: string;
  value: number | string | null | undefined;
};

type DetailTab = "basic" | "related" | "portals";

function textValue(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function isVisibleRawValue(value: unknown): boolean {
  if (value === null || value === undefined || value === "") return false;
  if (Array.isArray(value) && value.length === 0) return false;
  return true;
}

function isUrl(value: unknown): value is string {
  return typeof value === "string" && /^https?:\/\//i.test(value);
}

function isInternalIdField(key: string): boolean {
  const parts = key.split("::");
  const leafKey = parts[parts.length - 1] || key;
  const normalized = leafKey.toLowerCase().replace(/[\s_-]/g, "");
  return normalized === "recordid" || normalized === "modid";
}

function fieldLabel(key: string): string {
  return key.includes("::") ? key.split("::").slice(1).join("::") : key;
}

function rawText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function RawFieldList({ fields }: { fields: Record<string, unknown> }) {
  const entries = Object.entries(fields).filter(([key, value]) => !isInternalIdField(key) && isVisibleRawValue(value));
  if (entries.length === 0) {
    return <div className="empty-state">暂无字段</div>;
  }

  return (
    <div className="raw-field-list">
      {entries.map(([key, value]) => (
        <div key={key} className="raw-field-row">
          <span>{fieldLabel(key)}</span>
          {isUrl(value) ? (
            <a href={value} target="_blank" rel="noreferrer">
              {value}
            </a>
          ) : (
            <strong>{rawText(value)}</strong>
          )}
        </div>
      ))}
    </div>
  );
}

function RelatedFieldGroups({ groups }: { groups: BusinessProductFieldGroup[] }) {
  if (groups.length === 0) {
    return (
      <div className="card product-detail-card">
        <div className="empty-state">暂无相关字段</div>
      </div>
    );
  }

  return (
    <div className="product-related-grid">
      {groups.map((group) => (
        <div key={group.name} className="card product-detail-card related-field-card">
          <div className="card-head">
            <div className="card-head-left">
              <h3>{group.name}</h3>
              <span className="record-count">{Object.keys(group.fields).length} 字段</span>
            </div>
          </div>
          <RawFieldList fields={group.fields} />
        </div>
      ))}
    </div>
  );
}

function portalColumns(portal: BusinessProductPortalGroup): string[] {
  const ordered: string[] = [];
  portal.rows.forEach((row) => {
    Object.keys(row).forEach((key) => {
      if (!isInternalIdField(key) && !ordered.includes(key)) ordered.push(key);
    });
  });
  return ordered;
}

function PortalTable({ portal }: { portal: BusinessProductPortalGroup }) {
  const columns = portalColumns(portal);
  return (
    <div className="portal-table-wrap">
      <table className="portal-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{fieldLabel(column)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {portal.rows.map((row, index) => (
            <tr key={`${portal.name}-${row.recordId ?? index}`}>
              {columns.map((column) => {
                const value = row[column];
                return (
                  <td key={column}>
                    {isUrl(value) ? (
                      <a href={value} target="_blank" rel="noreferrer">
                        打开
                      </a>
                    ) : (
                      rawText(value)
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PortalGroups({ portals }: { portals: BusinessProductPortalGroup[] }) {
  if (portals.length === 0) {
    return (
      <div className="card product-detail-card">
        <div className="empty-state">暂无子表记录</div>
      </div>
    );
  }

  return (
    <div className="portal-group-stack">
      {portals.map((portal) => (
        <div key={portal.name} className="card product-detail-card portal-card">
          <div className="card-head">
            <div className="card-head-left">
              <h3>{portal.name}</h3>
              <span className="record-count">{portal.rows.length} 条</span>
            </div>
          </div>
          <PortalTable portal={portal} />
        </div>
      ))}
    </div>
  );
}

export default function BusinessProductDetailPage({
  apiBase = "",
  token,
  product,
  loading,
  formatQty,
  onBack
}: BusinessProductDetailPageProps) {
  const [activeTab, setActiveTab] = useState<DetailTab>("basic");
  const [imageObjectUrl, setImageObjectUrl] = useState("");

  useEffect(() => {
    setActiveTab("basic");
  }, [product?.recordId]);

  useEffect(() => {
    setImageObjectUrl("");
    if (!product?.imageUrl || !product.recordId || !token) return;

    const controller = new AbortController();
    let objectUrl = "";
    void fetch(
      `${apiBase}/api/business-products/${encodeURIComponent(product.recordId)}/image`,
      {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal
      }
    )
      .then((response) => {
        if (!response.ok) throw new Error("产品图片读取失败");
        return response.blob();
      })
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setImageObjectUrl(objectUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) setImageObjectUrl("");
      });

    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [apiBase, product?.imageUrl, product?.recordId, token]);

  const coreItems: DetailItem[] = [
    { label: "产品编号", value: product?.productSku },
    { label: "系统编号", value: product?.systemProductSku },
    { label: "英文名称", value: product?.productName },
    { label: "中文名称", value: product?.productNameCn },
    { label: "车款", value: product?.modelName },
    { label: "比例", value: product?.scale },
    { label: "类别", value: product?.category },
    { label: "审核", value: product?.auditStatus }
  ];
  const businessItems: DetailItem[] = [
    { label: "BOM 日期", value: product?.bomDate },
    { label: "BOM 计数", value: formatQty(product?.bomCount) },
    { label: "下单数量", value: formatQty(product?.orderQty) },
    { label: "库存", value: formatQty(product?.stock) },
    { label: "客户", value: product?.client || product?.customer },
    { label: "权限", value: product?.privilege },
    { label: "分类 1", value: product?.category1 },
    { label: "分类 2", value: product?.category2 },
    { label: "分类 3", value: product?.category3 },
    { label: "供应商", value: product?.vendor },
    { label: "标签规格", value: product?.labelSpec },
    { label: "包装检查", value: product?.packageCheck },
    { label: "DMS 状态", value: product?.dmsStatus }
  ];
  const mainFields = useMemo(() => product?.mainFields ?? {}, [product]);
  const relatedFieldGroups = product?.relatedFieldGroups ?? [];
  const portals = product?.portals ?? [];
  const mainFieldCount = Object.keys(mainFields).length;
  const relatedFieldCount = relatedFieldGroups.reduce((total, group) => total + Object.keys(group.fields).length, 0);
  const portalRowCount = portals.reduce((total, portal) => total + portal.rows.length, 0);

  return (
    <>
      <div className="detail-nav-row">
        <button className="btn" type="button" onClick={onBack}>
          <ArrowLeft size={16} />
          返回列表
        </button>
      </div>

      <section className="product-detail-hero">
        <div className="product-detail-media">
          {imageObjectUrl ? (
            <img src={imageObjectUrl} alt={product?.productNameCn || product?.productName || product?.productSku} />
          ) : (
            <div className="product-image-empty">
              <ImageIcon size={34} />
            </div>
          )}
        </div>
        <div className="product-detail-title">
          <div className="product-title-row">
            <span className="status-chip success">{product?.auditStatus || "未标注"}</span>
            {product?.imageStatus && <span className="status-chip muted">{product.imageStatus}</span>}
          </div>
          <h2>{product?.productNameCn || product?.productSku || (loading ? "加载中..." : "未选择产品")}</h2>
          <p>{product?.productName || "-"}</p>
          <div className="product-detail-code">{product?.productSku || "-"}</div>
        </div>
        <div className="product-detail-actions">
          {product?.selectedFileUrl && (
            <a className="btn" href={product.selectedFileUrl} target="_blank" rel="noreferrer">
              <ExternalLink size={15} />
              文件
            </a>
          )}
          {product?.qrCodeUrl && (
            <a className="btn" href={product.qrCodeUrl} target="_blank" rel="noreferrer">
              <QrCode size={15} />
              QR
            </a>
          )}
        </div>
      </section>

      <section className="product-detail-tabs" aria-label="产品资料详情">
        <div className="detail-tab-list" role="tablist" aria-label="详情分组">
          <button
            className={["detail-tab-button", activeTab === "basic" ? "active" : ""].join(" ")}
            type="button"
            role="tab"
            aria-selected={activeTab === "basic"}
            onClick={() => setActiveTab("basic")}
          >
            <Info size={16} />
            主表信息
            <span>{mainFieldCount}</span>
          </button>
          <button
            className={["detail-tab-button", activeTab === "related" ? "active" : ""].join(" ")}
            type="button"
            role="tab"
            aria-selected={activeTab === "related"}
            onClick={() => setActiveTab("related")}
          >
            <Link2 size={16} />
            相关字段
            <span>{relatedFieldCount}</span>
          </button>
          <button
            className={["detail-tab-button", activeTab === "portals" ? "active" : ""].join(" ")}
            type="button"
            role="tab"
            aria-selected={activeTab === "portals"}
            onClick={() => setActiveTab("portals")}
          >
            <Table2 size={16} />
            子表记录
            <span>{portalRowCount}</span>
          </button>
        </div>

        {activeTab === "basic" && (
          <div className="product-detail-sections" role="tabpanel">
            <div className="card product-detail-card">
              <div className="card-head">
                <div className="card-head-left">
                  <h3>核心资料</h3>
                </div>
              </div>
              <div className="product-detail-grid">
                {coreItems.map((item) => (
                  <div key={item.label}>
                    <span className="meta-label">{item.label}</span>
                    <strong className="meta-value">{textValue(item.value)}</strong>
                  </div>
                ))}
              </div>
            </div>

            <div className="card product-detail-card">
              <div className="card-head">
                <div className="card-head-left">
                  <h3>商务与分类</h3>
                </div>
              </div>
              <div className="product-detail-grid product-detail-grid-wide">
                {businessItems.map((item) => (
                  <div key={item.label}>
                    <span className="meta-label">{item.label}</span>
                    <strong className="meta-value">{textValue(item.value)}</strong>
                  </div>
                ))}
              </div>
            </div>

            <div className="card product-detail-card product-raw-card">
              <div className="card-head">
                <div className="card-head-left">
                  <h3>主表原始字段</h3>
                  <span className="record-count">{mainFieldCount} 个非空字段</span>
                </div>
              </div>
              <RawFieldList fields={mainFields} />
            </div>
          </div>
        )}

        {activeTab === "related" && (
          <div className="product-detail-sections" role="tabpanel">
            <RelatedFieldGroups groups={relatedFieldGroups} />
          </div>
        )}

        {activeTab === "portals" && (
          <div className="product-detail-sections" role="tabpanel">
            <PortalGroups portals={portals} />
          </div>
        )}
      </section>
      <div className="page-footer-spacer" aria-hidden="true" />
    </>
  );
}
