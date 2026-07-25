import {
  AlertCircle,
  Check,
  ChevronDown,
  CircleHelp,
  Database,
  Loader2,
  PackageCheck,
  RefreshCw,
  Search,
  Sparkles,
  X
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { SessionResponse } from "../types";
import { parseError } from "../utils/error";
import "./material-id-webviewer.css";

const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";
const useScriptName = "DOF_IDGen_WebViewer使用";

type Option = {
  code: string;
  label: string;
};

type MaterialIdOptions = {
  materials: Option[];
  customers: Option[];
  manufactures: Option[];
  colors: Option[];
  others: Option[];
};

type RelatedPart = {
  partNumber: string;
  internalName: string;
  externalName: string;
};

type RelatedPartSearchResponse = {
  items: RelatedPart[];
  foundCount: number;
};

type GenerationResponse = {
  partNumber: string;
  serial: string;
  prefix: string;
  autoSerial: boolean;
  exists: boolean;
  scriptPartNumber: string;
  matchesScript: boolean | null;
  scannedCount: number;
  algorithmVersion: string;
  explanation: string[];
};

type FormState = {
  material: Option | null;
  customer: Option | null;
  serial: string;
  manufacture: Option | null;
  color: Option | null;
  other: Option | null;
};

declare global {
  interface Window {
    FileMaker?: {
      PerformScript: (scriptName: string, parameter?: string) => void;
    };
  }
}

const emptyForm: FormState = {
  material: null,
  customer: null,
  serial: "",
  manufacture: null,
  color: null,
  other: null
};

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
  token?: string
): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers
    }
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

function optionText(option: Option): string {
  return option.label && option.label !== option.code
    ? `${option.code} · ${option.label}`
    : option.code;
}

export function MaterialIdSearchSelect({
  label,
  placeholder,
  value,
  options,
  required,
  disabled,
  onChange
}: {
  label: string;
  placeholder: string;
  value: Option | null;
  options: Option[];
  required?: boolean;
  disabled?: boolean;
  onChange: (option: Option | null) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    function closeOnOutsideClick(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, []);

  const filtered = useMemo(() => {
    const term = query.trim().toLocaleLowerCase();
    if (!term) return options;
    return options.filter((option) =>
      `${option.code} ${option.label}`.toLocaleLowerCase().includes(term)
    );
  }, [options, query]);

  return (
    <div className="mid-field" ref={rootRef}>
      <span className="mid-label">
        {label}
        {required && <b aria-label="必填">*</b>}
      </span>
      <button
        className={`mid-select-trigger ${value ? "has-value" : ""}`}
        type="button"
        disabled={disabled}
        title={value ? optionText(value) : undefined}
        aria-label={`${label}${required ? " 必填" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={(event) => {
          event.stopPropagation();
          setQuery("");
          setOpen((current) => !current);
        }}
      >
        <span>{value ? optionText(value) : placeholder}</span>
        <ChevronDown size={16} />
      </button>
      {open && (
        <span className="mid-select-popover">
          <span className="mid-select-search">
            <Search size={15} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={`搜索${label}`}
              autoFocus
            />
          </span>
          <span className="mid-option-list" role="listbox">
            {filtered.length ? (
              filtered.map((option) => (
                <button
                  className={value?.code === option.code ? "selected" : ""}
                  type="button"
                  role="option"
                  aria-selected={value?.code === option.code}
                  key={option.code}
                  onClick={(event) => {
                    event.stopPropagation();
                    onChange(option);
                    setQuery("");
                    setOpen(false);
                  }}
                >
                  <strong>{option.code}</strong>
                  <span>{option.label}</span>
                  {value?.code === option.code && <Check size={15} />}
                </button>
              ))
            ) : (
              <em>没有匹配选项</em>
            )}
          </span>
        </span>
      )}
    </div>
  );
}

export default function MaterialIdWebViewerApp() {
  const didStart = useRef(false);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [options, setOptions] = useState<MaterialIdOptions | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [relatedQuery, setRelatedQuery] = useState("");
  const [relatedResults, setRelatedResults] = useState<RelatedPart[]>([]);
  const [relatedPart, setRelatedPart] = useState<RelatedPart | null>(null);
  const [relatedLoading, setRelatedLoading] = useState(false);
  const [result, setResult] = useState<GenerationResponse | null>(null);
  const [starting, setStarting] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [usingResult, setUsingResult] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [relatedError, setRelatedError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "零件编号生成";
    document.documentElement.dataset.theme = "light";
    document.documentElement.style.colorScheme = "light";
  }, []);

  useEffect(() => {
    if (didStart.current) return;
    didStart.current = true;

    async function start() {
      const params = new URLSearchParams(window.location.search);
      try {
        const nextSession = await requestJson<SessionResponse>(
          "/api/webviewer/session",
          {
            method: "POST",
            body: JSON.stringify({
              ctx: params.get("ctx"),
              sig: params.get("sig"),
              mock: !(params.get("ctx") && params.get("sig")),
              operator: {
                account: "material-id.preview",
                name: "编号预览",
                privilege: "mock"
              }
            })
          }
        );
        const nextOptions = await requestJson<MaterialIdOptions>(
          "/api/material-ids/options",
          {},
          nextSession.token
        );
        setSession(nextSession);
        setOptions(nextOptions);
      } catch (nextError) {
        setError(parseError(nextError));
      } finally {
        setStarting(false);
      }
    }

    void start();
  }, []);

  useEffect(() => {
    if (!session || relatedPart || relatedQuery.trim().length < 2) {
      setRelatedResults([]);
      setRelatedLoading(false);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setRelatedLoading(true);
      setRelatedError(null);
      try {
        const response = await requestJson<RelatedPartSearchResponse>(
          `/api/material-ids/related-parts?query=${encodeURIComponent(relatedQuery.trim())}&limit=20`,
          { signal: controller.signal },
          session.token
        );
        setRelatedResults(response.items);
      } catch (nextError) {
        if ((nextError as Error).name !== "AbortError") {
          setRelatedError(parseError(nextError));
        }
      } finally {
        setRelatedLoading(false);
      }
    }, 320);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [relatedPart, relatedQuery, session]);

  const componentCodes = [
    form.material?.code,
    form.customer?.code,
    form.serial.trim() || "自动",
    form.manufacture?.code,
    form.color?.code,
    form.other?.code
  ].filter(Boolean) as string[];

  function patchForm(patch: Partial<FormState>) {
    setForm((current) => ({ ...current, ...patch }));
    setResult(null);
    setError(null);
  }

  async function generate() {
    if (!session) return;
    if (!form.material || !form.customer) {
      setError("请先选择性质和客户。");
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const response = await requestJson<GenerationResponse>(
        "/api/material-ids/generate",
        {
          method: "POST",
          body: JSON.stringify({
            material: form.material.code,
            customer: form.customer.code,
            serial: form.serial.trim(),
            manufacture: form.manufacture?.code ?? "",
            color: form.color?.code ?? "",
            other: form.other?.code ?? ""
          })
        },
        session.token
      );
      setResult(response);
    } catch (nextError) {
      setError(parseError(nextError));
      setResult(null);
    } finally {
      setGenerating(false);
    }
  }

  function useGeneratedNumber() {
    if (!result || !form.material || !form.customer) {
      setError("请先生成编号。");
      return;
    }
    if (!window.FileMaker?.PerformScript) {
      setError("当前页面不在 FileMaker WebViewer 中，无法写回零件资料。");
      return;
    }
    setUsingResult(true);
    setError(null);
    window.FileMaker.PerformScript(
      useScriptName,
      JSON.stringify({
        material: form.material.code,
        customer: form.customer.code,
        serial: result.serial,
        manufacture: form.manufacture?.code ?? "",
        color: form.color?.code ?? "",
        other: form.other?.code ?? "",
        output: result.partNumber,
        relatedPartNumber: relatedPart?.partNumber ?? ""
      })
    );
  }

  function reset() {
    setForm(emptyForm);
    setRelatedQuery("");
    setRelatedPart(null);
    setRelatedResults([]);
    setResult(null);
    setError(null);
    setUsingResult(false);
  }

  if (starting) {
    return (
      <main className="mid-root mid-centered" aria-live="polite">
        <span className="mid-loading-mark"><Sparkles size={21} /></span>
        <Loader2 className="mid-spin" size={25} />
        <strong>正在连接 FileMaker…</strong>
        <small>读取性质、客户与编号配置</small>
      </main>
    );
  }

  if (!session || !options) {
    return (
      <main className="mid-root mid-centered">
        <span className="mid-error-mark"><AlertCircle size={22} /></span>
        <h1>无法打开编号生成器</h1>
        <p>{error ?? "WebViewer 会话初始化失败。"}</p>
        <button className="mid-btn mid-btn-secondary" type="button" onClick={() => window.location.reload()}>
          <RefreshCw size={16} /> 重新载入
        </button>
      </main>
    );
  }

  return (
    <main className="mid-root">
      <header className="mid-header">
        <span className="mid-brand-mark"><Sparkles size={19} /></span>
        <span className="mid-heading">
          <strong>零件编号生成</strong>
          <small>FileMaker Data API · 实时规则</small>
        </span>
        <span className="mid-connected"><i /> 已连接 FileMaker</span>
      </header>

      <div className="mid-workspace">
        <section className="mid-card mid-form-card">
          <div className="mid-section-heading">
            <span>
              <small>01</small>
              <strong>编号组成</strong>
            </span>
            <em>带 * 为必选项</em>
          </div>

          <div className="mid-form-grid">
            <MaterialIdSearchSelect
              label="性质"
              placeholder="选择零件性质"
              value={form.material}
              options={options.materials}
              required
              onChange={(material) => patchForm({ material })}
            />
            <MaterialIdSearchSelect
              label="客户"
              placeholder="选择客户代码或名称"
              value={form.customer}
              options={options.customers}
              required
              onChange={(customer) => patchForm({ customer })}
            />
            <label className="mid-field">
              <span className="mid-label">
                手工序号
                <span className="mid-help" title="留空时自动查找下一个三位序号">
                  <CircleHelp size={14} />
                </span>
              </span>
              <input
                className="mid-input"
                value={form.serial}
                maxLength={20}
                onChange={(event) => patchForm({ serial: event.target.value })}
                placeholder="留空则自动生成"
              />
            </label>
            <MaterialIdSearchSelect
              label="加工"
              placeholder="可选加工程序"
              value={form.manufacture}
              options={options.manufactures}
              onChange={(manufacture) => patchForm({ manufacture })}
            />
            <MaterialIdSearchSelect
              label="颜色"
              placeholder="可选颜色代码"
              value={form.color}
              options={options.colors}
              onChange={(color) => patchForm({ color })}
            />
            <MaterialIdSearchSelect
              label="其他"
              placeholder="可选特殊需求"
              value={form.other}
              options={options.others}
              onChange={(other) => patchForm({ other })}
            />
          </div>

          <div className="mid-composition" aria-label="编号组成预览">
            <span>组成预览</span>
            <div>
              {componentCodes.map((code, index) => (
                <span key={`${code}-${index}`} className={code === "自动" ? "auto" : ""}>
                  {code}
                </span>
              ))}
              {!componentCodes.length && <em>选择上方项目后显示</em>}
            </div>
          </div>

          <div className="mid-divider" />

          <div className="mid-section-heading mid-related-heading">
            <span>
              <small>02</small>
              <strong>相关零件</strong>
            </span>
            <em>可选，用于带入名称</em>
          </div>

          <div className="mid-related">
            <label className="mid-field mid-related-search">
              <span className="mid-label">相关零件</span>
              <span className="mid-search-input">
                <Search size={16} />
                <input
                  value={relatedPart ? relatedPart.partNumber : relatedQuery}
                  onChange={(event) => {
                    setRelatedPart(null);
                    setRelatedQuery(event.target.value);
                  }}
                  placeholder="输入编号或名称，至少 2 个字符"
                />
                {relatedLoading && <Loader2 className="mid-spin" size={16} />}
                {(relatedPart || relatedQuery) && !relatedLoading && (
                  <button
                    type="button"
                    aria-label="清除相关零件"
                    onClick={() => {
                      setRelatedPart(null);
                      setRelatedQuery("");
                      setRelatedResults([]);
                    }}
                  >
                    <X size={15} />
                  </button>
                )}
              </span>
              {!relatedPart && relatedResults.length > 0 && (
                <span className="mid-related-results">
                  {relatedResults.map((part) => (
                    <button
                      type="button"
                      key={part.partNumber}
                      onClick={() => {
                        setRelatedPart(part);
                        setRelatedQuery(part.partNumber);
                        setRelatedResults([]);
                      }}
                    >
                      <strong>{part.partNumber}</strong>
                      <span>{part.internalName || part.externalName || "未填写名称"}</span>
                    </button>
                  ))}
                </span>
              )}
              {relatedError && <span className="mid-inline-error">{relatedError}</span>}
            </label>

            <dl className="mid-related-names">
              <div>
                <dt>内部名称</dt>
                <dd>{relatedPart?.internalName || "—"}</dd>
              </div>
              <div>
                <dt>对外名称</dt>
                <dd>{relatedPart?.externalName || "—"}</dd>
              </div>
            </dl>
          </div>
        </section>

        <aside className="mid-card mid-result-card">
          <div className="mid-result-title">
            <span><PackageCheck size={18} /></span>
            <div>
              <strong>生成结果</strong>
              <small>与现行 FileMaker 编号规则一致</small>
            </div>
          </div>

          <div className={`mid-number-panel ${result ? "ready" : ""}`}>
            <small>{result ? "零件编号" : "等待生成"}</small>
            <strong>{result?.partNumber ?? "— — —"}</strong>
            {result ? (
              <span>
                <i />
                {result.autoSerial ? `自动序号 ${result.serial}` : `手工序号 ${result.serial}`}
              </span>
            ) : (
              <p>选择性质与客户后即可生成</p>
            )}
          </div>

          {result && (
            <div className="mid-result-details">
              <div><span>编号前缀</span><strong>{result.prefix}</strong></div>
              <div><span>已扫描同前缀</span><strong>{result.scannedCount} 条</strong></div>
              <div><span>规则版本</span><strong>{result.algorithmVersion}</strong></div>
            </div>
          )}

          {error && (
            <div className="mid-alert" role="alert">
              <AlertCircle size={17} />
              <span>{error}</span>
            </div>
          )}

          <div className="mid-actions">
            <button
              className="mid-btn mid-btn-primary"
              type="button"
              onClick={() => void generate()}
              disabled={
                generating ||
                !form.material ||
                !form.customer
              }
            >
              {generating ? <Loader2 className="mid-spin" size={17} /> : <Sparkles size={17} />}
              {generating ? "正在计算…" : result ? "重新生成" : "生成编号"}
            </button>
            <button
              className="mid-btn mid-btn-use"
              type="button"
              onClick={useGeneratedNumber}
              disabled={!result || usingResult}
            >
              <Check size={18} />
              {usingResult ? "已提交给 FileMaker" : "使用此编号"}
            </button>
            <button className="mid-btn mid-btn-secondary" type="button" onClick={reset}>
              <RefreshCw size={15} /> 清空重来
            </button>
          </div>

          <footer className="mid-source-note">
            <Database size={14} />
            <span>选项与重复编号检查均实时读取 FileMaker</span>
          </footer>
        </aside>
      </div>
    </main>
  );
}
