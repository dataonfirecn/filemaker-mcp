import {
  ArrowLeft,
  ArrowLeftRight,
  Box,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Copy,
  Download,
  FileArchive,
  FileImage,
  FileText,
  ImageIcon,
  Layers3,
  LoaderCircle,
  MapPin,
  Ruler,
  ShieldCheck,
  Sparkles,
  Truck,
  Warehouse,
  X,
  ZoomIn
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { PartDirectoryRow } from "./PartDirectoryPage";

type SectionId = "overview" | "procurement" | "specifications" | "quality" | "inventory" | "records" | "gallery";
type AssetCategory = "all" | "photo" | "drawing" | "process" | "package";
type FieldAccent = "" | "positive" | "warning" | "muted";

type PartField = {
  label: string;
  value: string;
  note: string;
  accent: FieldAccent;
};

type PartFieldGroup = {
  title: string;
  description: string;
  fields: PartField[];
};

type PartAsset = {
  id: string;
  partId: string;
  partNumber: string;
  type: string;
  category: Exclude<AssetCategory, "all">;
  role: string;
  visibility: string;
  title: string;
  description: string;
  filename: string;
  mimeType: string;
  fileSize: number | null;
  objectKey: string;
  url: string;
  urlExpiresAt: string;
  isPrimary: boolean;
  sortOrder: number;
  updatedAt: string;
  source: "cos";
};

type RecordItem = {
  id: string;
  title: string;
  subtitle: string;
  meta: string;
  status: string;
};

type RecordGroup = {
  title: string;
  description: string;
  items: RecordItem[];
};

type PartSectionData = {
  section: SectionId;
  groups: PartFieldGroup[];
  recordGroups: RecordGroup[];
  sourceTables: string[];
};

type PartDetailResponse = {
  part: PartDirectoryRow;
  assets: PartAsset[];
  groups: PartFieldGroup[];
  sourceTables: string[];
};

type PartDetailPrototypePageProps = {
  apiBase?: string;
  token: string;
  identifier: string;
  onBack?: () => void;
};

const sectionMeta: Array<{
  id: SectionId;
  label: string;
  icon: typeof Box;
}> = [
  { id: "overview", label: "概览", icon: Layers3 },
  { id: "procurement", label: "采购与成本", icon: Truck },
  { id: "specifications", label: "规格与标识", icon: Ruler },
  { id: "quality", label: "质量与流程", icon: ShieldCheck },
  { id: "inventory", label: "库存交易", icon: ArrowLeftRight },
  { id: "records", label: "关联记录", icon: ClipboardCheck },
  { id: "gallery", label: "零件图库", icon: ImageIcon }
];

const assetCategoryMeta: Array<{ id: AssetCategory; label: string }> = [
  { id: "all", label: "全部" },
  { id: "photo", label: "产品照片" },
  { id: "drawing", label: "工程图" },
  { id: "process", label: "打样 / 工艺" },
  { id: "package", label: "包装" }
];

function responseError(body: string): string {
  try {
    const payload = JSON.parse(body) as { detail?: string | { message?: string } };
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail?.message) return payload.detail.message;
  } catch {
    // Fall through to raw response text.
  }
  return body || "零件详情读取失败";
}

function formatFileSize(value: number | null): string {
  if (!value || value <= 0) return "未知大小";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function display(value: string): string {
  return value.trim() || "—";
}

function assetTypeLabel(asset: PartAsset): string {
  if (asset.category === "drawing") return "工程图面";
  if (asset.category === "process") return "工艺资料";
  if (asset.category === "package") return "包装资料";
  return "零件照片";
}

function FieldGroupCard({ group }: { group: PartFieldGroup }) {
  const Icon = group.title.includes("库存") || group.title.includes("仓储")
    ? Warehouse
    : group.title.includes("供应") || group.title.includes("采购")
      ? Truck
      : group.title.includes("审核") || group.title.includes("质量")
        ? ShieldCheck
        : group.title.includes("规格") || group.title.includes("流程")
          ? Ruler
          : Layers3;
  return (
    <section className="part-prototype-field-card">
      <header>
        <span className="part-prototype-section-icon"><Icon size={17} /></span>
        <div>
          <h3>{group.title}</h3>
          <p>{group.description}</p>
        </div>
      </header>
      <dl>
        {group.fields.map((field) => (
          <div key={`${group.title}-${field.label}`}>
            <dt>{field.label}</dt>
            <dd className={field.accent ? `is-${field.accent}` : ""}>
              {field.value}
              {field.note && <small>{field.note}</small>}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function RecordGroups({ groups }: { groups: RecordGroup[] }) {
  if (!groups.length) return null;
  return (
    <div className="part-prototype-record-grid">
      {groups.map((group) => (
        <section className="part-prototype-field-card" key={group.title}>
          <header>
            <span className="part-prototype-section-icon"><ClipboardCheck size={17} /></span>
            <div><h3>{group.title}</h3><p>{group.description}</p></div>
            <span className="part-prototype-count">{group.items.length}</span>
          </header>
          {group.items.length ? (
            <div className="part-prototype-link-list">
              {group.items.map((item) => (
                <div className="part-prototype-record-item" key={item.id}>
                  <span>
                    <strong>{item.title}</strong>
                    {item.subtitle && <small>{item.subtitle}</small>}
                    {item.meta && <em>{item.meta}</em>}
                  </span>
                  {item.status && <i>{item.status}</i>}
                </div>
              ))}
            </div>
          ) : (
            <div className="part-prototype-record-empty">当前零件没有此类关联记录。</div>
          )}
        </section>
      ))}
    </div>
  );
}

function AssetPreview({ asset, alt }: { asset: PartAsset; alt: string }) {
  if (!asset.url) {
    return (
      <div className="part-prototype-asset-placeholder">
        <FileImage size={42} />
        <strong>文件暂时无法预览</strong>
        <span>{asset.filename || asset.objectKey}</span>
      </div>
    );
  }
  if (asset.mimeType.startsWith("image/")) {
    return <img className="part-prototype-art" src={asset.url} alt={alt} />;
  }
  if (asset.mimeType === "application/pdf") {
    return <iframe className="part-prototype-document" src={asset.url} title={alt} />;
  }
  return (
    <div className="part-prototype-asset-placeholder">
      <FileArchive size={42} />
      <strong>{asset.filename || "零件文件"}</strong>
      <a href={asset.url} target="_blank" rel="noreferrer">打开原文件</a>
    </div>
  );
}

export default function PartDetailPrototypePage({
  apiBase = "",
  token,
  identifier,
  onBack
}: PartDetailPrototypePageProps) {
  const [detail, setDetail] = useState<PartDetailResponse | null>(null);
  const [activeSection, setActiveSection] = useState<SectionId>("overview");
  const [sections, setSections] = useState<Partial<Record<SectionId, PartSectionData>>>({});
  const [activeAssetId, setActiveAssetId] = useState("");
  const [activeAssetCategory, setActiveAssetCategory] = useState<AssetCategory>("all");
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(false);
  const [sectionLoading, setSectionLoading] = useState<SectionId | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sectionError, setSectionError] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !identifier) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setDetail(null);
    setSections({});
    setActiveSection("overview");
    setActiveAssetCategory("all");
    void fetch(`${apiBase}/api/part-directory/${encodeURIComponent(identifier)}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(responseError(await response.text()));
        return response.json() as Promise<PartDetailResponse>;
      })
      .then((nextDetail) => {
        setDetail(nextDetail);
        const primary = nextDetail.assets.find((asset) => asset.isPrimary) ?? nextDetail.assets[0];
        setActiveAssetId(primary?.id ?? "");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "零件详情读取失败");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [apiBase, identifier, token]);

  useEffect(() => {
    if (!token || !identifier || activeSection === "overview" || activeSection === "gallery" || sections[activeSection]) return;
    const controller = new AbortController();
    setSectionLoading(activeSection);
    setSectionError(null);
    void fetch(
      `${apiBase}/api/part-directory/${encodeURIComponent(identifier)}/sections/${activeSection}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal
      }
    )
      .then(async (response) => {
        if (!response.ok) throw new Error(responseError(await response.text()));
        return response.json() as Promise<PartSectionData>;
      })
      .then((section) => {
        setSections((current) => ({ ...current, [activeSection]: section }));
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setSectionError(reason instanceof Error ? reason.message : "选项卡资料读取失败");
      })
      .finally(() => {
        if (!controller.signal.aborted) setSectionLoading(null);
      });
    return () => controller.abort();
  }, [activeSection, apiBase, identifier, sections, token]);

  const assets = detail?.assets ?? [];
  const filteredAssets = useMemo(
    () => activeAssetCategory === "all"
      ? assets
      : assets.filter((asset) => asset.category === activeAssetCategory),
    [activeAssetCategory, assets]
  );
  const activeAsset = useMemo(
    () => filteredAssets.find((asset) => asset.id === activeAssetId)
      ?? filteredAssets[0]
      ?? assets[0],
    [activeAssetId, assets, filteredAssets]
  );
  const activeAssetIndex = activeAsset
    ? Math.max(0, filteredAssets.findIndex((asset) => asset.id === activeAsset.id))
    : 0;
  const primaryAsset = useMemo(
    () => assets.find((asset) => asset.isPrimary) ?? assets[0],
    [assets]
  );
  const currentSection: PartSectionData | null = activeSection === "overview"
    ? detail
      ? {
          section: "overview",
          groups: detail.groups,
          recordGroups: [],
          sourceTables: detail.sourceTables
        }
      : null
    : sections[activeSection] ?? null;

  function selectAssetCategory(category: AssetCategory) {
    const nextAssets = category === "all"
      ? assets
      : assets.filter((asset) => asset.category === category);
    setActiveAssetCategory(category);
    if (!nextAssets.some((asset) => asset.id === activeAssetId)) {
      setActiveAssetId(nextAssets[0]?.id ?? "");
    }
  }

  function stepAsset(direction: -1 | 1) {
    if (!filteredAssets.length) return;
    const nextIndex = (activeAssetIndex + direction + filteredAssets.length) % filteredAssets.length;
    setActiveAssetId(filteredAssets[nextIndex].id);
  }

  function openPrimaryPreview() {
    if (!primaryAsset) return;
    setActiveAssetCategory("all");
    setActiveAssetId(primaryAsset.id);
    setLightboxOpen(true);
  }

  async function copyPartNumber() {
    const partNumber = detail?.part.partNumber;
    if (!partNumber) return;
    try {
      await navigator.clipboard.writeText(partNumber);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  if (loading) {
    return (
      <div className="part-prototype-page">
        {onBack && <button className="part-prototype-back" type="button" onClick={onBack}><ArrowLeft size={16} />返回零件列表</button>}
        <div className="part-prototype-loading"><LoaderCircle className="spin" size={28} /><strong>正在读取零件核心资料与 COS 图片…</strong></div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="part-prototype-page">
        {onBack && <button className="part-prototype-back" type="button" onClick={onBack}><ArrowLeft size={16} />返回零件列表</button>}
        <div className="part-directory-error">{error || "没有可显示的零件资料。"}</div>
      </div>
    );
  }

  const part = detail.part;
  const lowStock = part.safetyStock > 0 && part.stock < part.safetyStock;

  return (
    <div className="part-prototype-page">
      {onBack && (
        <button className="part-prototype-back" type="button" onClick={onBack}>
          <ArrowLeft size={16} />返回零件列表
        </button>
      )}

      <div className="part-prototype-notice">
        <span><Sparkles size={15} />FileMaker 实时资料</span>
        <p>核心资料来自“零件”表；成本、采购、库存和关联记录按选项卡分别读取，图片使用腾讯 COS 短时签名地址。</p>
      </div>

      <section className="part-prototype-hero">
        <div className="part-prototype-identity">
          <div className="part-prototype-eyebrow">
            <span className={`part-directory-status ${lowStock ? "pending" : "success"}`}>{display(part.lifecycleStatus)}</span>
            <span className="part-directory-status muted">{display(part.auditStatus)}</span>
          </div>
          <h2>{display(part.nameInternal)}</h2>
          {part.nameExternal.trim() && part.nameExternal.trim() !== part.nameInternal.trim() ? (
            <p>{display(part.nameExternal)}</p>
          ) : null}
          <div className="part-prototype-code-row">
            <code>{part.partNumber}</code>
            <button type="button" onClick={() => void copyPartNumber()}><Copy size={14} />{copied ? "已复制" : "复制编号"}</button>
          </div>
          <div className="part-prototype-responsibility">
            <span><Truck size={14} />{display(part.manufacturer)}</span>
            <span><Warehouse size={14} />{display(part.warehouseDivision)}</span>
            <span><MapPin size={14} />{display(part.locationPrimary)}</span>
          </div>
        </div>
        {primaryAsset ? (
          <button
            type="button"
            className="part-prototype-hero-thumb"
            onClick={openPrimaryPreview}
            title="查看主图大图"
          >
            {primaryAsset.url && primaryAsset.mimeType.startsWith("image/") ? (
              <img src={primaryAsset.url} alt={primaryAsset.title || part.nameInternal} />
            ) : (
              <span className="part-prototype-hero-thumb-fallback">
                <FileImage size={24} />
                <small>{primaryAsset.mimeType === "application/pdf" ? "PDF 图面" : "零件文件"}</small>
              </span>
            )}
            <span className="part-prototype-hero-thumb-zoom"><ZoomIn size={12} />大图</span>
          </button>
        ) : (
          <div className="part-prototype-hero-thumb is-empty">
            <ImageIcon size={22} />
            <small>暂无图片</small>
          </div>
        )}
      </section>

      <section className="part-prototype-panel">
        <nav className="part-prototype-tabs" aria-label="零件资料分组">
          {sectionMeta.map((section) => {
            const Icon = section.icon;
            const loadedGroups = section.id === "overview" ? detail.groups : sections[section.id]?.groups;
            const fieldCount = loadedGroups?.reduce((sum, group) => sum + group.fields.length, 0);
            const recordCount = sections[section.id]?.recordGroups.reduce((sum, group) => sum + group.items.length, 0);
            const count = section.id === "gallery"
              ? assets.length
              : section.id === "inventory" || section.id === "records"
                ? recordCount
                : fieldCount;
            return (
              <button
                key={section.id}
                className={activeSection === section.id ? "active" : ""}
                type="button"
                onClick={() => setActiveSection(section.id)}
                aria-current={activeSection === section.id ? "page" : undefined}
              >
                <Icon size={16} /><span>{section.label}</span>
                <em>{sectionLoading === section.id ? "…" : count ?? "按需"}</em>
              </button>
            );
          })}
        </nav>

        {activeSection === "gallery" ? (
        <div className="part-prototype-media">
        <div className="part-prototype-stage">
          <header className="part-prototype-stage-head">
            <div>
              <span>{activeAsset ? assetTypeLabel(activeAsset) : "零件图库"}</span>
              <h3>{activeAsset?.title || "暂无图片资料"}</h3>
              <p>{activeAsset?.description || activeAsset?.filename || "PartAssets 中还没有可显示的文件。"}</p>
            </div>
            {activeAsset && (
              <div className="part-prototype-stage-actions">
                <span>{activeAssetIndex + 1} / {filteredAssets.length}</span>
                <button type="button" onClick={() => setLightboxOpen(true)} disabled={!activeAsset.url}><ZoomIn size={16} />查看大图</button>
              </div>
            )}
          </header>
          <div className="part-prototype-canvas">
            {activeAsset ? (
              <AssetPreview asset={activeAsset} alt={activeAsset.title || part.nameInternal} />
            ) : (
              <div className="part-prototype-asset-placeholder"><ImageIcon size={42} /><strong>暂无 COS 图片</strong><span>{part.partNumber}</span></div>
            )}
            {filteredAssets.length > 1 && (
              <>
                <button className="part-prototype-gallery-arrow previous" type="button" onClick={() => stepAsset(-1)} aria-label="上一张图片"><ChevronLeft size={19} /></button>
                <button className="part-prototype-gallery-arrow next" type="button" onClick={() => stepAsset(1)} aria-label="下一张图片"><ChevronRight size={19} /></button>
              </>
            )}
            {activeAsset?.isPrimary && <span className="part-prototype-primary-badge">默认主图</span>}
          </div>
          <div className="part-prototype-file-meta">
            {activeAsset ? (
              <>
                <span>{activeAsset.mimeType}</span>
                <span>{formatFileSize(activeAsset.fileSize)}</span>
                <span>{activeAsset.role}</span>
                <span>{activeAsset.updatedAt || "未记录更新时间"}</span>
                <span>腾讯 COS</span>
              </>
            ) : <span>PartAssets · 0 个文件</span>}
          </div>
        </div>

        <div className="part-prototype-assets">
          <header>
            <div><h3>零件图库</h3><p>按 PartAssets 类型集中展示</p></div>
            <span>{assets.length} 个文件</span>
          </header>
          <div className="part-prototype-asset-filters" aria-label="图片分类">
            {assetCategoryMeta.map((category) => {
              const count = category.id === "all"
                ? assets.length
                : assets.filter((asset) => asset.category === category.id).length;
              if (category.id !== "all" && count === 0) return null;
              return (
                <button
                  key={category.id}
                  type="button"
                  className={activeAssetCategory === category.id ? "active" : ""}
                  aria-pressed={activeAssetCategory === category.id}
                  onClick={() => selectAssetCategory(category.id)}
                >
                  {category.label}<span>{count}</span>
                </button>
              );
            })}
          </div>
          <div className="part-prototype-asset-list">
            {filteredAssets.map((asset) => (
              <button
                key={asset.id}
                className={activeAsset?.id === asset.id ? "active" : ""}
                type="button"
                onClick={() => setActiveAssetId(asset.id)}
              >
                <span className="part-prototype-asset-thumbnail">
                  {asset.url && asset.mimeType.startsWith("image/")
                    ? <img src={asset.url} alt="" loading="lazy" />
                    : asset.category === "drawing"
                      ? <FileText size={28} />
                      : <FileImage size={28} />}
                  {asset.isPrimary && <em>主图</em>}
                </span>
                <span>
                  <strong>{asset.title || asset.filename}</strong>
                  <small>{asset.role} · {formatFileSize(asset.fileSize)}</small>
                </span>
              </button>
            ))}
            {!filteredAssets.length && <div className="part-prototype-record-empty">此分类暂无文件。</div>}
          </div>
          <footer className="part-prototype-gallery-footer">
            <span>产品照片 {part.photoCount}</span><i /><span>工程图 {part.drawingCount}</span><i /><span>其他 {Math.max(0, part.assetCount - part.photoCount - part.drawingCount)}</span>
          </footer>
        </div>
        </div>
        ) : (
        <div className="part-prototype-panel-body">
          {sectionError && <div className="part-directory-error">{sectionError}</div>}
          {sectionLoading === activeSection && !currentSection ? (
            <div className="part-prototype-loading"><LoaderCircle className="spin" size={24} /><strong>正在从相关表读取此选项卡…</strong></div>
          ) : (
            <>
              <div className="part-prototype-field-groups">
                {currentSection?.groups.map((group) => <FieldGroupCard key={group.title} group={group} />)}
              </div>
              <RecordGroups groups={currentSection?.recordGroups ?? []} />
            </>
          )}
        </div>
        )}

        <footer className="part-prototype-footer">
          <FileArchive size={15} />
          <span>本选项卡来源：{activeSection === "gallery" ? "PartAssets、腾讯 COS" : currentSection?.sourceTables.join("、") || "—"}</span>
          <CheckCircle2 size={15} />
        </footer>
      </section>

      {lightboxOpen && activeAsset && (
        <div
          className="part-prototype-lightbox"
          role="dialog"
          aria-modal="true"
          aria-label={`${activeAsset.title}大图预览`}
          onClick={(event) => {
            if (event.currentTarget === event.target) setLightboxOpen(false);
          }}
        >
          <div className="part-prototype-lightbox-panel">
            <header>
              <div>
                <span>{assetTypeLabel(activeAsset)} · {activeAsset.role}</span>
                <h3>{activeAsset.title || activeAsset.filename}</h3>
                <p>{activeAsset.filename}</p>
              </div>
              <button type="button" onClick={() => setLightboxOpen(false)} aria-label="关闭大图预览"><X size={20} /></button>
            </header>
            <div className="part-prototype-lightbox-canvas">
              <AssetPreview asset={activeAsset} alt={activeAsset.title || part.nameInternal} />
              {filteredAssets.length > 1 && (
                <>
                  <button type="button" className="previous" onClick={() => stepAsset(-1)} aria-label="上一张大图"><ChevronLeft size={22} /></button>
                  <button type="button" className="next" onClick={() => stepAsset(1)} aria-label="下一张大图"><ChevronRight size={22} /></button>
                </>
              )}
            </div>
            <footer>
              <span><strong>{activeAssetIndex + 1}</strong> / {filteredAssets.length}</span>
              <span>{activeAsset.mimeType} · {formatFileSize(activeAsset.fileSize)} · 腾讯 COS</span>
              {activeAsset.url && (
                <a href={activeAsset.url} target="_blank" rel="noreferrer"><Download size={15} />打开原文件</a>
              )}
            </footer>
          </div>
        </div>
      )}
    </div>
  );
}
