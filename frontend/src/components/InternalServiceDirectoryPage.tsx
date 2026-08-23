import {
  Bot,
  Boxes,
  ClipboardList,
  Database,
  ExternalLink,
  FileCode2,
  KeyRound,
  Layers3,
  MessageCircle,
  Monitor,
  PackagePlus,
  PanelTop,
  QrCode,
  Search,
  ShieldCheck,
  ShoppingCart,
  UserRound,
  Webhook
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";
import type { SessionResponse } from "../types";
import { openPreviewWindow } from "../utils/previewSession";

type PageEntry = {
  name: string;
  description: string;
  route: string;
  previewRoute?: string;
  testParameters?: Array<{
    name: string;
    value: string;
    description: string;
  }>;
  access: string;
  note?: string;
  Icon: LucideIcon;
};

type ApiEndpoint = {
  method: "GET" | "POST";
  path: string;
};

type ApiService = {
  name: string;
  description: string;
  direction: string;
  authentication: string;
  endpoints: ApiEndpoint[];
  icon: string;
};

type ApiServiceDirectoryResponse = {
  services: ApiService[];
};

const browserPages: PageEntry[] = [
  {
    name: "导航首页",
    description: "内部员工的业务入口与权限概览。",
    route: "/",
    access: "StarRC 员工账号",
    Icon: Monitor
  },
  {
    name: "智能对话",
    description: "自然语言查询产品、零件、库存和日期数据。",
    route: "/?page=chat",
    access: "智能问答权限",
    note: "同时支持 FileMaker 内嵌",
    Icon: MessageCircle
  },
  {
    name: "订单详情",
    description: "浏览出货单、订单明细并生成整单 BOM。",
    route: "/?page=orderDetail",
    previewRoute: "/?page=orderDetail&orderId=PI0017287",
    testParameters: [
      { name: "orderId", value: "PI0017287", description: "有效出货单 ID" }
    ],
    access: "订单查看权限",
    Icon: ShoppingCart
  },
  {
    name: "BOM 计算",
    description: "选择产品、读取 BOM、微调并确认计算单。",
    route: "/?page=bom",
    previewRoute: "/?page=bom&productSku=STRX-202",
    testParameters: [
      { name: "productSku", value: "STRX-202", description: "含 6 条 BOM 的产品" }
    ],
    access: "BOM 查看权限",
    Icon: ClipboardList
  },
  {
    name: "产品资料",
    description: "产品主数据、商务分类和详情查询。",
    route: "/?page=businessProducts",
    access: "产品查看权限",
    Icon: Boxes
  },
  {
    name: "零件资料",
    description: "零件主数据、关联资料、图片与图面。",
    route: "/?page=parts",
    previewRoute: "/?page=parts&partQuery=AL05094-F1",
    testParameters: [
      { name: "partQuery", value: "AL05094-F1", description: "可查询到的零件编号" }
    ],
    access: "产品与零件查看权限",
    Icon: Search
  },
  {
    name: "零件包发料",
    description: "按订单查看 FileMaker 发料分类明细。",
    route: "/?page=kitIssue",
    previewRoute: "/?page=kitIssue&orderId=NB07088",
    testParameters: [
      { name: "orderId", value: "NB07088", description: "作为发料订单号带入" }
    ],
    access: "BOM / 发料权限",
    Icon: Database
  },
  {
    name: "RAG 控制",
    description: "索引状态、刷新、搜索调试和关系映射。",
    route: "/?page=ragControl",
    access: "RAG 管理权限",
    Icon: Bot
  },
  {
    name: "个人设置",
    description: "查看账号资料、切换主题和退出当前会话。",
    route: "/?page=settings",
    access: "已登录用户",
    Icon: UserRound
  },
  {
    name: "账号与权限",
    description: "管理 FileMaker 账号映射、权限集与功能授权。",
    route: "/?page=accessAdmin",
    access: "系统管理员",
    Icon: ShieldCheck
  }
];

const filemakerPages: PageEntry[] = [
  {
    name: "员工智能对话",
    description: "FileMaker 内自动识别当前账号，无需再次登录。",
    route: "/?page=chat",
    access: "StarRC｜员工对话",
    note: "WebViewer：wv_starrc_employee_chat",
    Icon: MessageCircle
  },
  {
    name: "产品出入库记录",
    description: "在产品布局中显示库存摘要、趋势和流水。",
    route: "/?page=productInventory",
    access: "产品布局 / 出入记录页签",
    note: "WebViewer：wv_product_inventory",
    Icon: Database
  },
  {
    name: "内部订单合并",
    description: "在客户上下文中选择订单、预览并受控合并。",
    route: "/?page=internalOrderMerge",
    access: "客户｜订单合并 WebViewer",
    note: "WebViewer：wv_internal_order_merge",
    Icon: Layers3
  },
  {
    name: "零件编号生成",
    description: "读取编号选项、检查重复并回调 FileMaker 脚本。",
    route: "/?page=materialIdWebViewer",
    access: "MaterialIDGenerator_WebViewer",
    note: "WebViewer：wv_material_id_generator",
    Icon: FileCode2
  },
  {
    name: "新建零件",
    description: "完成零件资料录入、校验、图片上传和建立记录。",
    route: "/?page=newPartWebViewer",
    access: "Create New Part_Web",
    note: "WebViewer：wv_new_part",
    Icon: PackagePlus
  }
];

const apiIcons: Record<string, LucideIcon> = {
  key: KeyRound,
  message: MessageCircle,
  database: Database,
  orders: ShoppingCart,
  code: FileCode2,
  package: PackagePlus,
  webhook: Webhook,
  qr: QrCode
};

function PageCard({
  entry,
  tone,
  onPreview
}: {
  entry: PageEntry;
  tone: "browser" | "filemaker";
  onPreview?: (entry: PageEntry) => void;
}) {
  const Icon = entry.Icon;
  const previewRoute = entry.previewRoute ?? entry.route;
  return (
    <article className={`internal-directory-page-card ${tone}`}>
      <span className="internal-directory-page-icon"><Icon size={20} /></span>
      <div className="internal-directory-page-copy">
        <div>
          <h3>{entry.name}</h3>
          {entry.note && <span>{entry.note}</span>}
        </div>
        <p>{entry.description}</p>
        <div className="internal-directory-route">
          <span>入口 URL</span>
          <code>{entry.route}</code>
        </div>
        {tone === "browser" && (
          <div className="internal-directory-preview">
            <div className="internal-directory-preview-heading">
              <span>测试预览</span>
              <small>{entry.testParameters?.length ? `${entry.testParameters.length} 个参数` : "无需参数"}</small>
            </div>
            <code>{new URL(previewRoute, window.location.origin).toString()}</code>
            {entry.testParameters?.map((parameter) => (
              <div className="internal-directory-test-parameter" key={parameter.name}>
                <span>{parameter.name}</span>
                <strong>{parameter.value}</strong>
                <small>{parameter.description}</small>
              </div>
            ))}
          </div>
        )}
        <div className="internal-directory-page-footer">
          <small>{entry.access}</small>
          {tone === "browser" && onPreview && (
            <button type="button" onClick={() => onPreview(entry)}>
              打开预览
              <ExternalLink size={13} />
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

export default function InternalServiceDirectoryPage({
  apiBase,
  session
}: {
  apiBase: string;
  session: SessionResponse;
}) {
  const [apiServices, setApiServices] = useState<ApiService[]>([]);
  const [apiLoading, setApiLoading] = useState(true);
  const [apiError, setApiError] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setApiLoading(true);
    setApiError(null);
    fetch(`${apiBase}/api/webviewer/admin/service-directory`, {
      headers: { Authorization: `Bearer ${session.token}` },
      signal: controller.signal
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(await response.text());
        return response.json() as Promise<ApiServiceDirectoryResponse>;
      })
      .then((response) => {
        if (active) setApiServices(response.services);
      })
      .catch((error: unknown) => {
        if (active && (error as Error).name !== "AbortError") {
          setApiError("无法读取管理员 API 清单，请稍后重试。");
        }
      })
      .finally(() => {
        if (active) setApiLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [apiBase, session.token]);

  function handlePreview(entry: PageEntry) {
    setPreviewError(null);
    if (!openPreviewWindow(entry.previewRoute ?? entry.route, session)) {
      setPreviewError("浏览器阻止了新标签页。请允许 StarRC 打开弹出式窗口后重试。");
    }
  }

  return (
    <section className="internal-directory-page" aria-label="应用与接口目录">
      <div className="internal-directory-hero">
        <div>
          <span className="internal-directory-eyebrow">SYSTEM DIRECTORY</span>
          <h2>StarRC 应用与接口目录</h2>
          <p>按实际打开方式和调用方向分类。浏览器页面使用员工账号登录；内嵌页面由 FileMaker 生成签名上下文。</p>
        </div>
        <div className="internal-directory-summary" aria-label="目录统计">
          <div><strong>{browserPages.length}</strong><span>浏览器页面</span></div>
          <div><strong>{filemakerPages.length}</strong><span>内嵌页面</span></div>
          <div><strong>{apiLoading ? "…" : apiServices.length}</strong><span>API 服务组</span></div>
        </div>
      </div>

      <section className="internal-directory-section">
        <header>
          <span className="internal-directory-channel-icon browser"><Monitor size={21} /></span>
          <div>
            <span>CHANNEL 01</span>
            <h2>浏览器登录工作台</h2>
            <p>直接打开 StarRC，由内部员工账号登录；功能仍按 FileMaker 权限集开放。</p>
          </div>
          <strong>{browserPages.length} 个入口</strong>
        </header>
        {previewError && <div className="internal-directory-preview-error">{previewError}</div>}
        <div className="internal-directory-page-grid">
          {browserPages.map((entry) => (
            <PageCard entry={entry} key={entry.name} tone="browser" onPreview={handlePreview} />
          ))}
        </div>
      </section>

      <section className="internal-directory-section">
        <header>
          <span className="internal-directory-channel-icon filemaker"><PanelTop size={21} /></span>
          <div>
            <span>CHANNEL 02</span>
            <h2>FileMaker 内嵌页面</h2>
            <p>从布局、按钮或脚本打开 WebViewer；正式环境必须携带 ctx / sig，不显示网页登录。</p>
          </div>
          <strong>{filemakerPages.length} 个入口</strong>
        </header>
        <div className="internal-directory-page-grid">
          {filemakerPages.map((entry) => <PageCard entry={entry} key={entry.name} tone="filemaker" />)}
        </div>
      </section>

      <section className="internal-directory-section internal-directory-api-section">
        <header>
          <span className="internal-directory-channel-icon api"><Webhook size={21} /></span>
          <div>
            <span>ADMIN ONLY · CHANNEL 03</span>
            <h2>FileMaker 集成 API 服务</h2>
            <p>只在管理员目录中展示。清单按业务服务聚合，并明确调用方向与鉴权方式。</p>
          </div>
          <strong><ShieldCheck size={14} /> 管理员可见</strong>
        </header>
        {apiLoading && <div className="internal-directory-api-state">正在读取管理员 API 清单…</div>}
        {apiError && <div className="internal-directory-api-state error">{apiError}</div>}
        <div className="internal-directory-api-grid">
          {apiServices.map((service) => {
            const Icon = apiIcons[service.icon] ?? Webhook;
            return (
              <article className="internal-directory-api-card" key={service.name}>
                <div className="internal-directory-api-head">
                  <span><Icon size={19} /></span>
                  <div>
                    <h3>{service.name}</h3>
                    <p>{service.description}</p>
                  </div>
                </div>
                <dl>
                  <div><dt>调用方向</dt><dd>{service.direction}</dd></div>
                  <div><dt>鉴权</dt><dd>{service.authentication}</dd></div>
                </dl>
                <div className="internal-directory-endpoints">
                  {service.endpoints.map((endpoint) => (
                    <div key={`${endpoint.method}-${endpoint.path}`}>
                      <span className={endpoint.method.toLowerCase()}>{endpoint.method}</span>
                      <code>{endpoint.path}</code>
                    </div>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </section>
  );
}
