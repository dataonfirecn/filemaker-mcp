import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Database,
  ExternalLink,
  ImagePlus,
  Loader2,
  PackageCheck,
  PackagePlus,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  UploadCloud,
  X
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { SessionResponse } from "../types";
import { parseError } from "../utils/error";
import { MaterialIdSearchSelect } from "./MaterialIdWebViewerApp";
import "./new-part-webviewer.css";

const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";
const placeholderName = "新零件，請填寫正確中文名稱＆詳細資訊";
const maxPhotoInputBytes = 20 * 1024 * 1024;
const maxPhotoDimension = 1800;
const completeScriptName = "新建零件_WebViewer回调";

type Option = {
  code: string;
  label: string;
};

type VendorOption = {
  vendorId: string;
  vendorNumber: string;
  vendorName: string;
  status: string;
  selectable: boolean;
};

type VendorSearchResponse = {
  items: VendorOption[];
  foundCount: number;
};

type GeneratorOptions = {
  materials: Option[];
  customers: Option[];
  manufactures: Option[];
  colors: Option[];
  others: Option[];
};

type PartCreationOptions = {
  warehouseDivisions: Option[];
  materialCategories: Option[];
  machiningCategories: Option[];
  departmentDivisions: Option[];
  statisticsCategories: Option[];
  useDepartments: Option[];
  lifecycleStatuses: Option[];
  partCategories: Option[];
  materialProperties: Option[];
  warehouseCodes: Option[];
  materialSizes: Option[];
  exclusiveCustomers: Option[];
  generator: GeneratorOptions;
  assetUploadsEnabled: boolean;
  defaults: {
    departmentDivision: string;
    statisticsCategory: string;
    machiningCategory: string;
  };
};

type GeneratorState = {
  material: string;
  customer: string;
  serial: string;
  manufacture: string;
  color: string;
  other: string;
};

type GeneratorResponse = {
  partNumber: string;
  serial: string;
  prefix: string;
  autoSerial: boolean;
  exists: boolean;
  scannedCount: number;
  algorithmVersion: string;
};

type FormState = {
  partNumber: string;
  internalName: string;
  externalName: string;
  inventoryNotice: boolean;
  warehouseDivision: string;
  machiningCategory: string;
  statisticsCategory: string;
  useDepartment: string;
  lifecycleStatus: string;
  vendorId: string;
  vendorNumber: string;
  vendorName: string;
  materialCategory: string;
  departmentDivision: string;
  partCategory: string;
  materialProperties: string;
  materialSpec: string;
  warehouseCode: string;
  locationPrimary: string;
  locationSecondary: string;
  weightGrams: string;
  materialSize: string;
  customerCode: string;
  customerName: string;
  customerPartNumber: string;
};

type PartPhoto = {
  name: string;
  mimeType: string;
  base64: string;
  blob: Blob;
  previewUrl: string;
  size: number;
};

type ValidationResponse = {
  valid: boolean;
  errors: Record<string, string>;
  warnings: string[];
};

type CreateResponse = {
  ok: boolean;
  recordId: string;
  partId: string;
  partNumber: string;
  photoUploaded: boolean;
  photoAssetId?: string;
  warnings: string[];
};

type FileMakerCompletionAction = "return" | "openPart";

class ApiError extends Error {
  fieldErrors: Record<string, string>;

  constructor(message: string, fieldErrors: Record<string, string> = {}) {
    super(message);
    this.fieldErrors = fieldErrors;
  }
}

declare global {
  interface Window {
    FileMaker?: {
      PerformScript: (scriptName: string, parameter?: string) => void;
    };
  }
}

const emptyForm: FormState = {
  partNumber: "",
  internalName: "",
  externalName: "",
  inventoryNotice: false,
  warehouseDivision: "",
  machiningCategory: "",
  statisticsCategory: "",
  useDepartment: "",
  lifecycleStatus: "",
  vendorId: "",
  vendorNumber: "",
  vendorName: "",
  materialCategory: "",
  departmentDivision: "",
  partCategory: "",
  materialProperties: "",
  materialSpec: "",
  warehouseCode: "",
  locationPrimary: "",
  locationSecondary: "",
  weightGrams: "",
  materialSize: "",
  customerCode: "",
  customerName: "",
  customerPartNumber: ""
};

const emptyGenerator: GeneratorState = {
  material: "",
  customer: "",
  serial: "",
  manufacture: "",
  color: "",
  other: ""
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
  if (!response.ok) {
    const text = await response.text();
    try {
      const parsed = JSON.parse(text) as {
        detail?: {
          message?: string;
          errors?: Record<string, string>;
        };
      };
      if (parsed.detail?.message) {
        throw new ApiError(parsed.detail.message, parsed.detail.errors ?? {});
      }
    } catch (error) {
      if (error instanceof ApiError) throw error;
    }
    throw new Error(text);
  }
  return response.json() as Promise<T>;
}

function readFileAsDataUrl(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("无法读取照片文件。"));
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.readAsDataURL(file);
  });
}

function loadImage(source: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onerror = () => reject(new Error("照片格式无法识别，请改用 JPG、PNG 或 WebP。"));
    image.onload = () => resolve(image);
    image.src = source;
  });
}

async function preparePhoto(file: File): Promise<PartPhoto> {
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
    throw new Error("请选择 JPG、PNG 或 WebP 格式的照片。");
  }
  if (file.size > maxPhotoInputBytes) {
    throw new Error("原始照片不能超过 20 MB。");
  }
  const source = await readFileAsDataUrl(file);
  const image = await loadImage(source);
  const scale = Math.min(
    1,
    maxPhotoDimension / Math.max(image.naturalWidth, image.naturalHeight)
  );
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
  const context = canvas.getContext("2d");
  if (!context) throw new Error("当前 WebViewer 无法处理照片。");
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  const output = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("照片压缩失败。")),
      "image/jpeg",
      0.86
    );
  });
  const previewUrl = await readFileAsDataUrl(output);
  const stem = file.name.replace(/\.[^.]+$/, "").trim() || "零件照片";
  return {
    name: `${stem}.jpg`,
    mimeType: "image/jpeg",
    base64: previewUrl.split(",", 2)[1] ?? "",
    blob: output,
    previewUrl,
    size: output.size
  };
}

function optionText(option: Option): string {
  return option.label && option.label !== option.code
    ? `${option.code} · ${option.label}`
    : option.code;
}

function findOption(options: Option[], code: string): Option | null {
  return options.find((option) => option.code === code) ?? null;
}

function SelectField({
  label,
  value,
  options,
  placeholder,
  required,
  error,
  onChange
}: {
  label: string;
  value: string;
  options: Option[];
  placeholder: string;
  required?: boolean;
  error?: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className={`npw-field ${error ? "has-error" : ""}`}>
      <span className="npw-label">
        {label}
        {required && <b>*</b>}
      </span>
      <span className={`npw-select-wrap ${value ? "has-value" : ""}`}>
        <select
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">{placeholder}</option>
          {options.map((option) => (
            <option key={option.code} value={option.code}>
              {optionText(option)}
            </option>
          ))}
        </select>
        {value && (
          <button
            className="npw-select-clear"
            type="button"
            aria-label={`清空${label}`}
            title={`清空${label}`}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onChange("");
            }}
          >
            <X size={14} />
          </button>
        )}
        <ChevronDown size={16} />
      </span>
      {error && <small className="npw-field-error">{error}</small>}
    </div>
  );
}

function TextField({
  label,
  value,
  placeholder,
  suffix,
  error,
  onChange
}: {
  label: string;
  value: string;
  placeholder?: string;
  suffix?: string;
  error?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className={`npw-field ${error ? "has-error" : ""}`}>
      <span className="npw-label">{label}</span>
      <span className="npw-input-wrap">
        <input
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
        />
        {suffix && <em>{suffix}</em>}
      </span>
      {error && <small className="npw-field-error">{error}</small>}
    </label>
  );
}

export default function NewPartWebViewerApp() {
  const didStart = useRef(false);
  const photoInputRef = useRef<HTMLInputElement>(null);
  const vendorFieldRef = useRef<HTMLDivElement>(null);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [options, setOptions] = useState<PartCreationOptions | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [generator, setGenerator] = useState<GeneratorState>(emptyGenerator);
  const [generatorModalOpen, setGeneratorModalOpen] = useState(false);
  const [generatorResult, setGeneratorResult] = useState<GeneratorResponse | null>(null);
  const [generatorError, setGeneratorError] = useState<string | null>(null);
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
  const [photo, setPhoto] = useState<PartPhoto | null>(null);
  const [photoPreparing, setPhotoPreparing] = useState(false);
  const [starting, setStarting] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [validating, setValidating] = useState(false);
  const [creating, setCreating] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreateResponse | null>(null);
  const [fileMakerActionError, setFileMakerActionError] = useState<string | null>(null);
  const [customerQuery, setCustomerQuery] = useState("");
  const [vendorQuery, setVendorQuery] = useState("");
  const [vendorResults, setVendorResults] = useState<VendorOption[]>([]);
  const [vendorSearching, setVendorSearching] = useState(false);
  const [vendorSearchError, setVendorSearchError] = useState<string | null>(null);
  const [vendorOpen, setVendorOpen] = useState(false);

  useEffect(() => {
    document.title = "新建零件";
    document.documentElement.dataset.theme = "light";
    document.documentElement.style.colorScheme = "light";
  }, []);

  useEffect(() => {
    if (!generatorModalOpen && !resetConfirmOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (resetConfirmOpen) {
        setResetConfirmOpen(false);
      } else if (!generating) {
        setGeneratorModalOpen(false);
      }
    }

    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [generating, generatorModalOpen, resetConfirmOpen]);

  useEffect(() => {
    function closeVendorOnOutsideClick(event: MouseEvent) {
      if (!vendorFieldRef.current?.contains(event.target as Node)) {
        setVendorOpen(false);
      }
    }
    document.addEventListener("mousedown", closeVendorOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeVendorOnOutsideClick);
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
                account: "new-part.preview",
                name: "新建零件预览",
                privilege: "mock"
              }
            })
          }
        );
        const nextOptions = await requestJson<PartCreationOptions>(
          "/api/part-creation/options",
          {},
          nextSession.token
        );
        setSession(nextSession);
        setOptions(nextOptions);
        setForm((current) => ({
          ...current,
          departmentDivision: nextOptions.defaults.departmentDivision,
          statisticsCategory: nextOptions.defaults.statisticsCategory,
          machiningCategory: nextOptions.defaults.machiningCategory
        }));
      } catch (nextError) {
        setError(parseError(nextError));
      } finally {
        setStarting(false);
      }
    }
    void start();
  }, []);

  useEffect(() => {
    if (!session || !vendorOpen || form.vendorId) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setVendorSearching(true);
      setVendorSearchError(null);
      try {
        const params = new URLSearchParams({
          q: vendorQuery.trim(),
          limit: "40"
        });
        const response = await requestJson<VendorSearchResponse>(
          `/api/part-creation/vendors?${params.toString()}`,
          { signal: controller.signal },
          session.token
        );
        setVendorResults(response.items);
      } catch (nextError) {
        if (nextError instanceof DOMException && nextError.name === "AbortError") return;
        setVendorResults([]);
        setVendorSearchError(parseError(nextError));
      } finally {
        if (!controller.signal.aborted) setVendorSearching(false);
      }
    }, 220);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [form.vendorId, session, vendorOpen, vendorQuery]);

  const filteredCustomers = useMemo(() => {
    if (!options) return [];
    const term = customerQuery.trim().toLocaleLowerCase();
    if (!term) return options.exclusiveCustomers.slice(0, 40);
    return options.exclusiveCustomers
      .filter((option) =>
        `${option.code} ${option.label}`.toLocaleLowerCase().includes(term)
      )
      .slice(0, 40);
  }, [customerQuery, options]);

  const generatorComponentCodes = [
    generator.material,
    generator.customer,
    generator.serial.trim() || "自动",
    generator.manufacture,
    generator.color,
    generator.other
  ].filter(Boolean);

  function patchForm(patch: Partial<FormState>) {
    setForm((current) => ({ ...current, ...patch }));
    setCreated(null);
    setError(null);
    setWarnings([]);
    const changed = new Set(Object.keys(patch));
    setFieldErrors((current) =>
      Object.fromEntries(Object.entries(current).filter(([key]) => !changed.has(key)))
    );
  }

  function setMaterialCategory(value: string) {
    patchForm({ materialCategory: value });
    if (options?.generator.materials.some((item) => item.code === value)) {
      patchGenerator({ material: value });
    }
  }

  function patchGenerator(patch: Partial<GeneratorState>) {
    setGenerator((current) => ({ ...current, ...patch }));
    setGeneratorResult(null);
    setGeneratorError(null);
  }

  async function selectPhoto(file: File | undefined) {
    if (!file) return;
    setPhotoPreparing(true);
    setError(null);
    setFieldErrors((current) => {
      const next = { ...current };
      delete next.photo;
      return next;
    });
    try {
      setPhoto(await preparePhoto(file));
    } catch (nextError) {
      setPhoto(null);
      setFieldErrors((current) => ({ ...current, photo: parseError(nextError) }));
    } finally {
      setPhotoPreparing(false);
      if (photoInputRef.current) photoInputRef.current.value = "";
    }
  }

  async function generatePartNumber() {
    if (!session) return;
    if (!generator.material || !generator.customer) {
      setGeneratorError("请先选择性质和客户。");
      return;
    }
    setGenerating(true);
    setGeneratorError(null);
    try {
      const response = await requestJson<GeneratorResponse>(
        "/api/material-ids/generate",
        {
          method: "POST",
          body: JSON.stringify(generator)
        },
        session.token
      );
      setGeneratorResult(response);
    } catch (nextError) {
      setGeneratorError(parseError(nextError));
      setGeneratorResult(null);
    } finally {
      setGenerating(false);
    }
  }

  function confirmGeneratedPartNumber() {
    if (!generatorResult) {
      setGeneratorError("请先生成编号，再确认使用。");
      return;
    }
    if (generatorResult.exists) {
      setGeneratorError("这个编号已经存在，请重新生成。");
      return;
    }
    const customer = options?.exclusiveCustomers.find(
      (item) => item.code === generator.customer
    );
    if (!customer) {
      setGeneratorError("此编号客户没有可用的 FileMaker 客户资料，请重新选择客户。");
      return;
    }
    patchForm({
      partNumber: generatorResult.partNumber,
      customerCode: customer.code,
      customerName: customer.label,
      ...(options?.materialCategories.some(
        (item) => item.code === generator.material
      )
        ? { materialCategory: generator.material }
        : {})
    });
    setGeneratorModalOpen(false);
  }

  function payload(photoUploadId = "") {
    const useCosUpload = options?.assetUploadsEnabled ?? false;
    return {
      ...form,
      photoName: useCosUpload ? "" : photo?.name ?? "",
      photoMimeType: useCosUpload ? "" : photo?.mimeType ?? "",
      photoBase64: useCosUpload ? "" : photo?.base64 ?? "",
      photoUploadId
    };
  }

  async function sha256Hex(blob: Blob): Promise<string> {
    const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
    return Array.from(new Uint8Array(digest))
      .map((value) => value.toString(16).padStart(2, "0"))
      .join("");
  }

  async function uploadPhotoToCos(): Promise<string> {
    if (!session || !photo) return "";
    const sha256 = await sha256Hex(photo.blob);
    const draftId = `part_${crypto.randomUUID().replace(/-/g, "")}`;
    const presign = await requestJson<{
      uploadId: string;
      uploadUrl: string;
      headers: Record<string, string>;
    }>(
      "/api/part-assets/uploads/presign",
      {
        method: "POST",
        body: JSON.stringify({
          draftId,
          filename: photo.name,
          mimeType: photo.mimeType,
          fileSize: photo.size,
          sha256,
          assetType: "part_image",
          assetRole: "primary",
          visibility: "customer",
          source: "file_picker"
        })
      },
      session.token
    );
    const upload = await fetch(presign.uploadUrl, {
      method: "PUT",
      headers: presign.headers,
      body: photo.blob
    });
    if (!upload.ok) {
      throw new Error(`照片上传 COS 失败：HTTP ${upload.status}`);
    }
    await requestJson(
      `/api/part-assets/uploads/${encodeURIComponent(presign.uploadId)}/complete`,
      {
        method: "POST",
        body: JSON.stringify({
          etag: upload.headers.get("etag") ?? "",
          fileSize: photo.size,
          sha256
        })
      },
      session.token
    );
    return presign.uploadId;
  }

  async function validateForm(): Promise<boolean> {
    if (!session) return false;
    setValidating(true);
    setError(null);
    try {
      const response = await requestJson<ValidationResponse>(
        "/api/part-creation/validate",
        {
          method: "POST",
          body: JSON.stringify(payload())
        },
        session.token
      );
      setFieldErrors(response.errors);
      setWarnings(response.warnings);
      if (!response.valid) {
        setError("尚有必填或格式问题，请按红色提示修正。");
      }
      return response.valid;
    } catch (nextError) {
      if (nextError instanceof ApiError) setFieldErrors(nextError.fieldErrors);
      setError(parseError(nextError));
      return false;
    } finally {
      setValidating(false);
    }
  }

  async function createNewPart() {
    if (!session || creating) return;
    if (!(await validateForm())) return;
    setCreating(true);
    setError(null);
    try {
      const photoUploadId =
        photo && options?.assetUploadsEnabled ? await uploadPhotoToCos() : "";
      const response = await requestJson<CreateResponse>(
        "/api/part-creation",
        {
          method: "POST",
          body: JSON.stringify(payload(photoUploadId))
        },
        session.token
      );
      setCreated(response);
      setWarnings(response.warnings);
    } catch (nextError) {
      if (nextError instanceof ApiError) setFieldErrors(nextError.fieldErrors);
      setError(parseError(nextError));
    } finally {
      setCreating(false);
    }
  }

  function completeInFileMaker(action: FileMakerCompletionAction) {
    if (!created) return;
    if (!window.FileMaker) {
      setFileMakerActionError(
        "当前页面不在 FileMaker WebViewer 中，无法切换 FileMaker 画面。"
      );
      return;
    }
    setFileMakerActionError(null);
    try {
      window.FileMaker.PerformScript(
        completeScriptName,
        JSON.stringify({ ...created, action })
      );
    } catch (nextError) {
      setFileMakerActionError(`无法调用 FileMaker：${parseError(nextError)}`);
    }
  }

  function reset() {
    setForm({
      ...emptyForm,
      departmentDivision: options?.defaults.departmentDivision ?? "",
      statisticsCategory: options?.defaults.statisticsCategory ?? "",
      machiningCategory: options?.defaults.machiningCategory ?? ""
    });
    setGenerator(emptyGenerator);
    setGeneratorResult(null);
    setGeneratorError(null);
    setGeneratorModalOpen(false);
    setResetConfirmOpen(false);
    setPhoto(null);
    setFieldErrors({});
    setWarnings([]);
    setError(null);
    setCreated(null);
    setFileMakerActionError(null);
    setCustomerQuery("");
    setVendorQuery("");
    setVendorResults([]);
    setVendorSearching(false);
    setVendorSearchError(null);
    setVendorOpen(false);
  }

  if (starting) {
    return (
      <main className="npw-root npw-centered">
        <span className="npw-loading-icon"><PackagePlus size={24} /></span>
        <Loader2 className="npw-spin" size={25} />
        <strong>正在连接 FileMaker…</strong>
        <small>读取新建零件字段、值列表与编号规则</small>
      </main>
    );
  }

  if (!session || !options) {
    return (
      <main className="npw-root npw-centered">
        <span className="npw-error-icon"><AlertCircle size={23} /></span>
        <h1>无法打开新建零件页面</h1>
        <p>{error ?? "WebViewer 会话初始化失败。"}</p>
        <button type="button" onClick={() => window.location.reload()}>
          <RefreshCw size={16} /> 重新载入
        </button>
      </main>
    );
  }

  if (created) {
    return (
      <main className="npw-root npw-complete-root">
        <header className="npw-header">
          <span className="npw-brand"><PackageCheck size={21} /></span>
          <span className="npw-title">
            <strong>零件创建完成</strong>
            <small>资料已经保存到 FileMaker</small>
          </span>
          <span className="npw-connected"><i /> 已连接 FileMaker</span>
        </header>

        <div className="npw-complete-page">
          <section className="npw-complete-card" aria-live="polite">
            <span className="npw-complete-mark">
              <CheckCircle2 size={38} strokeWidth={2.25} />
            </span>
            <span className="npw-complete-kicker">创建成功</span>
            <h1>{created.partNumber}</h1>
            <p className="npw-complete-copy">
              新零件已经写入 FileMaker。请选择返回原画面，或直接转到刚创建的零件。
            </p>

            <dl className="npw-complete-details">
              <div>
                <dt>FileMaker Record ID</dt>
                <dd>{created.recordId}</dd>
              </div>
              <div>
                <dt>零件 ID</dt>
                <dd>{created.partId || "—"}</dd>
              </div>
              <div>
                <dt>零件照片</dt>
                <dd>{created.photoUploaded ? "已上传" : "未上传"}</dd>
              </div>
            </dl>

            {warnings.length > 0 && (
              <div className="npw-complete-notices">
                {warnings.map((warning) => (
                  <div className="npw-alert warning" key={warning}>
                    <AlertCircle size={17} />
                    <span>{warning}</span>
                  </div>
                ))}
              </div>
            )}

            {fileMakerActionError && (
              <div className="npw-alert error npw-complete-error" role="alert">
                <AlertCircle size={17} />
                <span>{fileMakerActionError}</span>
              </div>
            )}

            <div className="npw-complete-actions">
              <button
                className="npw-btn npw-complete-return"
                type="button"
                onClick={() => completeInFileMaker("return")}
              >
                <ArrowLeft size={17} />
                返回 FileMaker 原画面
              </button>
              <button
                className="npw-btn npw-complete-open"
                type="button"
                onClick={() => completeInFileMaker("openPart")}
              >
                <ExternalLink size={17} />
                转到新建的零件
              </button>
            </div>

            <button className="npw-complete-another" type="button" onClick={reset}>
              <Plus size={15} />
              继续建立另一个零件
            </button>
          </section>
        </div>
      </main>
    );
  }

  return (
    <main className="npw-root">
      <header className="npw-header">
        <span className="npw-brand"><PackagePlus size={21} /></span>
        <span className="npw-title">
          <strong>新建零件资料</strong>
          <small>验证完成后通过 FileMaker Data API 建立零件</small>
        </span>
        <span className="npw-connected"><i /> 已连接 FileMaker</span>
      </header>

      <div className="npw-page">
        <section className="npw-card npw-identity-card">
          <div className="npw-section-title">
            <span><small>01</small><strong>编号与名称</strong></span>
            <em>带 * 为必填项</em>
          </div>

          <div className="npw-number-row">
            <label className={`npw-field ${fieldErrors.partNumber ? "has-error" : ""}`}>
              <span className="npw-label">零件编号 <b>*</b></span>
              <span className="npw-number-input">
                <input
                  autoFocus
                  value={form.partNumber}
                  placeholder="输入或生成零件编号"
                  onChange={(event) => patchForm({ partNumber: event.target.value })}
                />
                {generatorResult && form.partNumber === generatorResult.partNumber && (
                  <span><CheckCircle2 size={14} /> API 已验证</span>
                )}
              </span>
              {fieldErrors.partNumber && (
                <small className="npw-field-error">{fieldErrors.partNumber}</small>
              )}
            </label>
            <button
              className="npw-btn npw-btn-generate"
              type="button"
              onClick={() => {
                setGeneratorError(null);
                setGeneratorModalOpen(true);
              }}
            >
              <Sparkles size={17} />
              生成零件编号
            </button>
          </div>

          <div className="npw-name-grid">
            <label className={`npw-field ${fieldErrors.internalName ? "has-error" : ""}`}>
              <span className="npw-label">内部名称 <b>*</b></span>
              <textarea
                value={form.internalName}
                rows={3}
                placeholder={placeholderName}
                onChange={(event) => patchForm({ internalName: event.target.value })}
              />
              {fieldErrors.internalName && (
                <small className="npw-field-error">{fieldErrors.internalName}</small>
              )}
            </label>
            <label className={`npw-field ${fieldErrors.externalName ? "has-error" : ""}`}>
              <span className="npw-label">对外名称 <b>*</b></span>
              <textarea
                value={form.externalName}
                rows={3}
                placeholder={placeholderName}
                onChange={(event) => patchForm({ externalName: event.target.value })}
              />
              {fieldErrors.externalName && (
                <small className="npw-field-error">{fieldErrors.externalName}</small>
              )}
            </label>
            <label className="npw-check">
              <input
                type="checkbox"
                checked={form.inventoryNotice}
                onChange={(event) => patchForm({ inventoryNotice: event.target.checked })}
              />
              <span><Check size={14} /></span>
              <strong>库存提醒</strong>
              <small>库存不足时显示提醒</small>
            </label>
          </div>
        </section>

        <section className="npw-card">
          <div className="npw-section-title">
            <span><small>02</small><strong>分类与仓储</strong></span>
            <em>选项实时来自 FileMaker 值列表</em>
          </div>

          <div className="npw-classification-grid">
            <div className="npw-field-column">
              <SelectField label="仓库分工" value={form.warehouseDivision} options={options.warehouseDivisions} placeholder="选择发料分类" required error={fieldErrors.warehouseDivision} onChange={(warehouseDivision) => patchForm({ warehouseDivision })} />
              <SelectField label="加工分类" value={form.machiningCategory} options={options.machiningCategories} placeholder="选择加工分类" error={fieldErrors.machiningCategory} onChange={(machiningCategory) => patchForm({ machiningCategory })} />
              <SelectField label="统计分类" value={form.statisticsCategory} options={options.statisticsCategories} placeholder="选择统计分类" error={fieldErrors.statisticsCategory} onChange={(statisticsCategory) => patchForm({ statisticsCategory })} />
              <SelectField label="使用部门" value={form.useDepartment} options={options.useDepartments} placeholder="选择使用部门" error={fieldErrors.useDepartment} onChange={(useDepartment) => patchForm({ useDepartment })} />
              <SelectField label="量产状况" value={form.lifecycleStatus} options={options.lifecycleStatuses} placeholder="选择量产状况" error={fieldErrors.lifecycleStatus} onChange={(lifecycleStatus) => patchForm({ lifecycleStatus })} />
              <div
                className={`npw-customer-field npw-vendor-field ${fieldErrors.vendorId ? "has-error" : ""}`}
                ref={vendorFieldRef}
              >
                <span className="npw-label">厂商</span>
                {form.vendorId ? (
                  <span className="npw-customer-selected npw-vendor-selected">
                    <strong>{form.vendorName}</strong>
                    <small>{form.vendorNumber || "未设置编号"}</small>
                    <button
                      type="button"
                      aria-label="清空厂商"
                      title="清空厂商"
                      onClick={() => {
                        patchForm({ vendorId: "", vendorNumber: "", vendorName: "" });
                        setVendorQuery("");
                        setVendorResults([]);
                        setVendorOpen(false);
                      }}
                    >
                      <X size={14} />
                    </button>
                  </span>
                ) : (
                  <span className="npw-customer-search npw-vendor-search">
                    <Search size={15} />
                    <input
                      value={vendorQuery}
                      placeholder="搜索厂商名称或编号"
                      aria-label="搜索厂商名称或编号"
                      onFocus={() => setVendorOpen(true)}
                      onClick={() => setVendorOpen(true)}
                      onChange={(event) => {
                        setVendorQuery(event.target.value);
                        setVendorOpen(true);
                      }}
                    />
                    {vendorSearching && <Loader2 className="npw-spin" size={15} />}
                    {vendorQuery && !vendorSearching && (
                      <button
                        className="npw-search-clear"
                        type="button"
                        aria-label="清空厂商搜索"
                        title="清空厂商搜索"
                        onClick={() => {
                          setVendorQuery("");
                          setVendorOpen(true);
                        }}
                      >
                        <X size={14} />
                      </button>
                    )}
                    {vendorOpen && (
                      <span className="npw-customer-results npw-vendor-results">
                        {vendorSearching ? (
                          <em>正在读取 FileMaker 厂商资料…</em>
                        ) : vendorSearchError ? (
                          <em className="error">{vendorSearchError}</em>
                        ) : vendorResults.length ? (
                          vendorResults.map((vendor) => (
                            <button
                              key={vendor.vendorId}
                              type="button"
                              disabled={!vendor.selectable}
                              title={
                                vendor.selectable
                                  ? `${vendor.vendorName} · ${vendor.vendorNumber || "未设置编号"}`
                                  : `${vendor.status || "未审核"}，暂不可选`
                              }
                              onClick={() => {
                                if (!vendor.selectable) return;
                                patchForm({
                                  vendorId: vendor.vendorId,
                                  vendorNumber: vendor.vendorNumber,
                                  vendorName: vendor.vendorName
                                });
                                setVendorQuery("");
                                setVendorResults([]);
                                setVendorOpen(false);
                              }}
                            >
                              <span>
                                <strong>{vendor.vendorName}</strong>
                                <small>{vendor.vendorNumber || "未设置编号"}</small>
                              </span>
                              <i className={vendor.selectable ? "approved" : "pending"}>
                                {vendor.selectable ? "已审核" : vendor.status || "未审核"}
                              </i>
                            </button>
                          ))
                        ) : (
                          <em>没有匹配厂商</em>
                        )}
                      </span>
                    )}
                  </span>
                )}
                {fieldErrors.vendorId && (
                  <small className="npw-field-error">{fieldErrors.vendorId}</small>
                )}
              </div>
            </div>

            <div className="npw-field-column">
              <SelectField label="零件性质" value={form.materialCategory} options={options.materialCategories} placeholder="选择零件性质" required error={fieldErrors.materialCategory} onChange={setMaterialCategory} />
              <SelectField label="部门分工" value={form.departmentDivision} options={options.departmentDivisions} placeholder="选择部门分工" error={fieldErrors.departmentDivision} onChange={(departmentDivision) => patchForm({ departmentDivision })} />
              <SelectField label="零件品种" value={form.partCategory} options={options.partCategories} placeholder="选择零件品种" error={fieldErrors.partCategory} onChange={(partCategory) => patchForm({ partCategory })} />
              <SelectField label="材料性质" value={form.materialProperties} options={options.materialProperties} placeholder="选择材料分类" error={fieldErrors.materialProperties} onChange={(materialProperties) => patchForm({ materialProperties })} />
              <TextField label="材质" value={form.materialSpec} placeholder="输入材质说明" onChange={(materialSpec) => patchForm({ materialSpec })} />
              <div className="npw-customer-field">
                <span className="npw-label">专属客户</span>
                {form.customerCode ? (
                  <span className="npw-customer-selected">
                    <strong>{form.customerName}</strong>
                    <small>{form.customerCode}</small>
                    <button type="button" onClick={() => patchForm({ customerCode: "", customerName: "" })}><X size={14} /></button>
                  </span>
                ) : (
                  <span className="npw-customer-search">
                    <Search size={15} />
                    <input value={customerQuery} placeholder="搜索客户名称或代码" onChange={(event) => setCustomerQuery(event.target.value)} />
                    {customerQuery && (
                      <span className="npw-customer-results">
                        {filteredCustomers.length ? filteredCustomers.map((customer) => (
                          <button key={customer.code} type="button" onClick={() => {
                            patchForm({ customerCode: customer.code, customerName: customer.label });
                            setCustomerQuery("");
                          }}>
                            <strong>{customer.label}</strong><small>{customer.code}</small>
                          </button>
                        )) : <em>没有匹配客户</em>}
                      </span>
                    )}
                  </span>
                )}
                {fieldErrors.customerCode && <small className="npw-field-error">{fieldErrors.customerCode}</small>}
              </div>
            </div>

            <div className="npw-field-column npw-storage-column">
              {options.warehouseCodes.length ? (
                <SelectField label="仓库" value={form.warehouseCode} options={options.warehouseCodes} placeholder="选择仓库位置" onChange={(warehouseCode) => patchForm({ warehouseCode })} />
              ) : (
                <TextField label="仓库" value={form.warehouseCode} placeholder="FileMaker 当前无仓库选项" onChange={(warehouseCode) => patchForm({ warehouseCode })} />
              )}
              <TextField label="位置 1" value={form.locationPrimary} placeholder="输入主要位置" onChange={(locationPrimary) => patchForm({ locationPrimary })} />
              <TextField label="位置 2" value={form.locationSecondary} placeholder="输入次要位置" onChange={(locationSecondary) => patchForm({ locationSecondary })} />
              <TextField label="重量" value={form.weightGrams} placeholder="0" suffix="g" error={fieldErrors.weightGrams} onChange={(weightGrams) => patchForm({ weightGrams })} />
              <label className="npw-field">
                <span className="npw-label">材料尺寸</span>
                <span className={`npw-input-wrap ${form.materialSize ? "has-value" : ""}`}>
                  <input
                    list="npw-material-sizes"
                    value={form.materialSize}
                    placeholder="选择或输入材料尺寸"
                    onChange={(event) => patchForm({ materialSize: event.target.value })}
                  />
                  {form.materialSize && (
                    <button
                      className="npw-input-clear"
                      type="button"
                      aria-label="清空材料尺寸"
                      title="清空材料尺寸"
                      onClick={() => patchForm({ materialSize: "" })}
                    >
                      <X size={14} />
                    </button>
                  )}
                  <datalist id="npw-material-sizes">
                    {options.materialSizes.map((option) => (
                      <option key={option.code} value={option.code}>{option.label}</option>
                    ))}
                  </datalist>
                </span>
              </label>
              <TextField label="客户零件号" value={form.customerPartNumber} placeholder="可选" onChange={(customerPartNumber) => patchForm({ customerPartNumber })} />
            </div>
          </div>
        </section>

        <section className="npw-card">
          <div className="npw-section-title">
            <span><small>03</small><strong>零件照片</strong></span>
            <em>可选 · 建立后上传到 FileMaker 容器字段</em>
          </div>
          <input ref={photoInputRef} hidden type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => void selectPhoto(event.target.files?.[0])} />
          <div
            className={`npw-photo-zone ${photo ? "has-photo" : ""} ${fieldErrors.photo ? "has-error" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              event.dataTransfer.dropEffect = "copy";
            }}
            onDrop={(event) => {
              event.preventDefault();
              void selectPhoto(event.dataTransfer.files?.[0]);
            }}
          >
            {photo ? (
              <>
                <img src={photo.previewUrl} alt="零件照片预览" />
                <span>
                  <strong>{photo.name}</strong>
                  <small>{Math.max(1, Math.round(photo.size / 1024))} KB · 已压缩为 JPG</small>
                  <button type="button" onClick={() => photoInputRef.current?.click()}><UploadCloud size={15} /> 更换照片</button>
                </span>
                <button className="npw-photo-remove" type="button" onClick={() => setPhoto(null)}><Trash2 size={16} /></button>
              </>
            ) : (
              <button type="button" disabled={photoPreparing} onClick={() => photoInputRef.current?.click()}>
                <span>{photoPreparing ? <Loader2 className="npw-spin" size={24} /> : <ImagePlus size={24} />}</span>
                <strong>{photoPreparing ? "正在处理照片…" : "点击选择或拖入零件照片"}</strong>
                <small>支持 JPG、PNG、WebP；自动压缩并限制尺寸</small>
              </button>
            )}
          </div>
          {fieldErrors.photo && <small className="npw-field-error npw-photo-error">{fieldErrors.photo}</small>}
        </section>

        {(error || warnings.length > 0) && (
          <section className="npw-feedback" aria-live="polite">
            {error && <div className="npw-alert error"><AlertCircle size={17} /><span>{error}</span></div>}
            {warnings.map((warning) => <div className="npw-alert warning" key={warning}><AlertCircle size={17} /><span>{warning}</span></div>)}
          </section>
        )}

      </div>

      <footer className="npw-actions">
        <div className="npw-actions-inner">
          <button
            className="npw-btn npw-btn-reset"
            type="button"
            onClick={() => setResetConfirmOpen(true)}
            disabled={creating}
          >
            <RefreshCw size={16} /> 清空重来
          </button>
          <button className="npw-btn npw-btn-validate" type="button" onClick={() => void validateForm()} disabled={validating || creating}>
            {validating ? <Loader2 className="npw-spin" size={16} /> : <Check size={16} />}
            {validating ? "正在验证…" : "检查资料"}
          </button>
          <button className="npw-btn npw-btn-create" type="button" onClick={() => void createNewPart()} disabled={creating || photoPreparing}>
            {creating ? <Loader2 className="npw-spin" size={17} /> : <PackagePlus size={17} />}
            {creating ? "正在建立零件…" : "建立零件"}
          </button>
        </div>
      </footer>

      {generatorModalOpen && (
        <div
          className="npw-modal-overlay npw-generator-overlay"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !generating) {
              setGeneratorModalOpen(false);
            }
          }}
        >
          <section
            className="npw-modal npw-generator-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="npw-generator-modal-title"
          >
            <header className="npw-modal-header">
              <span className="npw-modal-mark"><Sparkles size={19} /></span>
              <span>
                <strong id="npw-generator-modal-title">生成零件编号</strong>
                <small>复用现有编号规则，确认后才写入新零件表单</small>
              </span>
              <button
                type="button"
                aria-label="关闭编号生成"
                onClick={() => setGeneratorModalOpen(false)}
                disabled={generating}
              >
                <X size={18} />
              </button>
            </header>

            <div className="npw-generator-modal-grid">
              <section className="npw-generator-form-panel">
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
                    value={findOption(options.generator.materials, generator.material)}
                    options={options.generator.materials}
                    required
                    onChange={(material) => patchGenerator({ material: material?.code ?? "" })}
                  />
                  <MaterialIdSearchSelect
                    label="客户"
                    placeholder="选择客户代码或名称"
                    value={findOption(options.generator.customers, generator.customer)}
                    options={options.generator.customers}
                    required
                    onChange={(customer) => patchGenerator({ customer: customer?.code ?? "" })}
                  />
                  <label className="mid-field">
                    <span className="mid-label">
                      手工序号
                      <span className="mid-help" title="留空时自动查找下一个序号">
                        <CircleHelp size={14} />
                      </span>
                    </span>
                    <input
                      className="mid-input"
                      value={generator.serial}
                      maxLength={20}
                      onChange={(event) => patchGenerator({ serial: event.target.value })}
                      placeholder="留空则自动生成"
                    />
                  </label>
                  <MaterialIdSearchSelect
                    label="加工"
                    placeholder="可选加工程序"
                    value={findOption(options.generator.manufactures, generator.manufacture)}
                    options={options.generator.manufactures}
                    onChange={(manufacture) => patchGenerator({ manufacture: manufacture?.code ?? "" })}
                  />
                  <MaterialIdSearchSelect
                    label="颜色"
                    placeholder="可选颜色代码"
                    value={findOption(options.generator.colors, generator.color)}
                    options={options.generator.colors}
                    onChange={(color) => patchGenerator({ color: color?.code ?? "" })}
                  />
                  <MaterialIdSearchSelect
                    label="其他"
                    placeholder="可选特殊需求"
                    value={findOption(options.generator.others, generator.other)}
                    options={options.generator.others}
                    onChange={(other) => patchGenerator({ other: other?.code ?? "" })}
                  />
                </div>

                <div className="mid-composition" aria-label="编号组成预览">
                  <span>组成预览</span>
                  <div>
                    {generatorComponentCodes.map((code, index) => (
                      <span key={`${code}-${index}`} className={code === "自动" ? "auto" : ""}>
                        {code}
                      </span>
                    ))}
                    {!generatorComponentCodes.length && <em>选择上方项目后显示</em>}
                  </div>
                </div>
              </section>

              <aside className="npw-generator-result-panel">
                <div className="mid-result-title">
                  <span><PackageCheck size={18} /></span>
                  <div>
                    <strong>生成结果</strong>
                    <small>与现行 FileMaker 编号规则一致</small>
                  </div>
                </div>

                <div className={`mid-number-panel ${generatorResult ? "ready" : ""}`}>
                  <small>{generatorResult ? "待确认零件编号" : "等待生成"}</small>
                  <strong>{generatorResult?.partNumber ?? "— — —"}</strong>
                  {generatorResult ? (
                    <span>
                      <i />
                      {generatorResult.autoSerial
                        ? `自动序号 ${generatorResult.serial}`
                        : `手工序号 ${generatorResult.serial}`}
                    </span>
                  ) : (
                    <p>选择性质与客户后生成编号</p>
                  )}
                </div>

                {generatorResult && (
                  <div className="mid-result-details">
                    <div><span>编号前缀</span><strong>{generatorResult.prefix}</strong></div>
                    <div><span>已扫描同前缀</span><strong>{generatorResult.scannedCount} 条</strong></div>
                    <div><span>规则版本</span><strong>{generatorResult.algorithmVersion}</strong></div>
                  </div>
                )}

                {generatorError && (
                  <div className="mid-alert" role="alert">
                    <AlertCircle size={17} />
                    <span>{generatorError}</span>
                  </div>
                )}

                <footer className="mid-source-note">
                  <Database size={14} />
                  <span>选项与重复编号检查均实时读取 FileMaker</span>
                </footer>
              </aside>
            </div>

            <footer className="npw-modal-actions">
              <button
                className="npw-btn npw-btn-reset"
                type="button"
                onClick={() => setGeneratorModalOpen(false)}
                disabled={generating}
              >
                取消
              </button>
              <button
                className="npw-btn npw-btn-generate"
                type="button"
                onClick={() => void generatePartNumber()}
                disabled={generating || !generator.material || !generator.customer}
              >
                {generating ? <Loader2 className="npw-spin" size={17} /> : <Sparkles size={17} />}
                {generating ? "正在计算…" : generatorResult ? "重新生成" : "生成编号"}
              </button>
              <button
                className="npw-btn npw-btn-create"
                type="button"
                onClick={confirmGeneratedPartNumber}
                disabled={!generatorResult || generatorResult.exists || generating}
              >
                <Check size={17} />
                确认使用此编号
              </button>
            </footer>
          </section>
        </div>
      )}

      {resetConfirmOpen && (
        <div className="npw-modal-overlay npw-confirm-overlay">
          <section
            className="npw-modal npw-confirm-modal"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="npw-reset-confirm-title"
          >
            <span className="npw-confirm-mark"><RefreshCw size={20} /></span>
            <div>
              <strong id="npw-reset-confirm-title">确认清空全部内容？</strong>
              <p>已填写的名称、分类、仓库、编号和照片都会恢复为初始状态。</p>
            </div>
            <footer className="npw-modal-actions">
              <button
                className="npw-btn npw-btn-reset"
                type="button"
                onClick={() => setResetConfirmOpen(false)}
              >
                取消
              </button>
              <button className="npw-btn npw-btn-danger" type="button" onClick={reset}>
                确认清空
              </button>
            </footer>
          </section>
        </div>
      )}
    </main>
  );
}
