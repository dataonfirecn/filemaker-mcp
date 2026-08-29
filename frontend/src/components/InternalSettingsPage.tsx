import {
  Bot,
  Check,
  CheckCircle2,
  ChevronRight,
  KeyRound,
  LoaderCircle,
  LogOut,
  Moon,
  ShieldCheck,
  Sun,
  UserRound
} from "lucide-react";
import { useEffect, useState } from "react";
import type { ThemeMode, WebViewerPermissions } from "../types";
import type { InternalUserMenuUser } from "./InternalUserMenu";

export type InternalSettingsPageProps = {
  apiBase: string;
  token: string;
  user: InternalUserMenuUser;
  permissions: WebViewerPermissions;
  readOnly: boolean;
  theme: ThemeMode;
  onThemeChange: (theme: ThemeMode) => void;
  onOpenAccountAdmin?: () => void;
  onSignOut: () => void;
};

type LlmProviderId = "deepseek" | "lm_studio";

type LlmProviderOption = {
  id: LlmProviderId;
  label: string;
  model: string;
  baseUrl: string;
  configured: boolean;
  active: boolean;
};

type LlmProviderStatus = {
  enabled: boolean;
  activeProvider: LlmProviderId;
  updatedAt: string | null;
  updatedBy: string;
  providers: LlmProviderOption[];
};

function llmErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  return fallback;
}

export default function InternalSettingsPage({
  apiBase,
  token,
  user,
  permissions,
  readOnly,
  theme,
  onThemeChange,
  onOpenAccountAdmin,
  onSignOut
}: InternalSettingsPageProps) {
  const [llmStatus, setLlmStatus] = useState<LlmProviderStatus | null>(null);
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmSwitching, setLlmSwitching] = useState<LlmProviderId | null>(null);
  const [llmError, setLlmError] = useState<string | null>(null);

  useEffect(() => {
    if (!permissions.canManageAccounts) return;
    let cancelled = false;
    setLlmLoading(true);
    setLlmError(null);
    void fetch(`${apiBase}/api/webviewer/admin/llm-provider`, {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => null);
        if (!response.ok) throw new Error(llmErrorMessage(payload, "无法读取 LLM 设置。"));
        if (!cancelled) setLlmStatus(payload as LlmProviderStatus);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLlmError(error instanceof Error ? error.message : "无法读取 LLM 设置。");
        }
      })
      .finally(() => {
        if (!cancelled) setLlmLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [apiBase, permissions.canManageAccounts, token]);

  async function switchLlmProvider(provider: LlmProviderId) {
    if (llmSwitching || llmStatus?.activeProvider === provider) return;
    setLlmSwitching(provider);
    setLlmError(null);
    try {
      const response = await fetch(`${apiBase}/api/webviewer/admin/llm-provider/switch`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ provider })
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(llmErrorMessage(payload, "LLM 切换失败。"));
      setLlmStatus(payload as LlmProviderStatus);
    } catch (error) {
      setLlmError(error instanceof Error ? error.message : "LLM 切换失败。");
    } finally {
      setLlmSwitching(null);
    }
  }

  return (
    <section className="internal-settings-page" aria-label="个人设置">
      <div className="internal-settings-profile">
        <span className="internal-settings-avatar" aria-hidden="true">
          {Array.from(user.displayName || user.username || "U").slice(0, 2).join("").toUpperCase()}
        </span>
        <div>
          <span className="internal-settings-eyebrow">当前登录用户</span>
          <h2>{user.displayName || user.username}</h2>
          <p>
            @{user.username}
            <span aria-hidden="true"> · </span>
            {permissions.canManageAccounts ? "系统管理员" : "内部员工"}
          </p>
        </div>
      </div>

      <div className="internal-settings-grid">
        <article className="internal-settings-card">
          <header>
            <span className="internal-settings-card-icon teal"><Sun size={19} /></span>
            <div>
              <h3>界面外观</h3>
              <p>选择适合当前环境的显示主题。</p>
            </div>
          </header>
          <div className="internal-theme-options" role="radiogroup" aria-label="显示主题">
            <button
              type="button"
              role="radio"
              aria-checked={theme === "light"}
              className={theme === "light" ? "active" : ""}
              onClick={() => onThemeChange("light")}
            >
              <span><Sun size={20} /></span>
              <strong>浅色模式</strong>
              <small>明亮、清晰的工作界面</small>
              {theme === "light" && <Check size={17} />}
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={theme === "dark"}
              className={theme === "dark" ? "active" : ""}
              onClick={() => onThemeChange("dark")}
            >
              <span><Moon size={20} /></span>
              <strong>深色模式</strong>
              <small>适合低光环境使用</small>
              {theme === "dark" && <Check size={17} />}
            </button>
          </div>
        </article>

        <article className="internal-settings-card">
          <header>
            <span className="internal-settings-card-icon blue"><UserRound size={19} /></span>
            <div>
              <h3>账号资料</h3>
              <p>当前会话中的身份与 FileMaker 权限。</p>
            </div>
          </header>
          <dl className="internal-settings-facts">
            <div><dt>显示名称</dt><dd>{user.displayName || "—"}</dd></div>
            <div><dt>用户名</dt><dd>{user.username || "—"}</dd></div>
            <div><dt>FileMaker 权限集</dt><dd>{user.privilegeSet || "—"}</dd></div>
            <div><dt>数据访问</dt><dd>{readOnly ? "只读模式" : "受控写入"}</dd></div>
          </dl>
          {permissions.canManageAccounts && onOpenAccountAdmin && (
            <button className="internal-settings-link" type="button" onClick={onOpenAccountAdmin}>
              <span>
                <ShieldCheck size={17} />
                管理账号与权限
              </span>
              <ChevronRight size={17} />
            </button>
          )}
        </article>

        {permissions.canManageAccounts && (
          <article className="internal-settings-card internal-settings-llm">
            <header>
              <span className="internal-settings-card-icon violet"><Bot size={19} /></span>
              <div>
                <h3>智能对话模型</h3>
                <p>管理员可即时切换供应商，选择会保存并在服务重启后继续生效。</p>
              </div>
            </header>

            {llmLoading && !llmStatus ? (
              <div className="internal-llm-loading">
                <LoaderCircle className="spin" size={18} />
                正在读取模型配置…
              </div>
            ) : (
              <div className="internal-llm-options" role="radiogroup" aria-label="智能对话模型供应商">
                {llmStatus?.providers.map((provider) => (
                  <button
                    key={provider.id}
                    type="button"
                    role="radio"
                    aria-checked={provider.active}
                    className={provider.active ? "active" : ""}
                    disabled={!provider.configured || Boolean(llmSwitching)}
                    onClick={() => void switchLlmProvider(provider.id)}
                  >
                    <span className="internal-llm-provider-heading">
                      <strong>{provider.label}</strong>
                      {provider.active ? (
                        <em><CheckCircle2 size={14} />当前使用</em>
                      ) : (
                        <em className={provider.configured ? "ready" : "missing"}>
                          {provider.configured ? "可切换" : "未配置 Key"}
                        </em>
                      )}
                    </span>
                    <span className="internal-llm-provider-model">{provider.model}</span>
                    <code>{provider.baseUrl}</code>
                    {llmSwitching === provider.id && (
                      <span className="internal-llm-switching">
                        <LoaderCircle className="spin" size={13} />切换中…
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}

            {llmStatus && !llmStatus.enabled && (
              <p className="internal-llm-notice">LLM 总开关当前关闭，请在服务器 `.env` 中启用 NATURAL_QUERY_LLM_ENABLED。</p>
            )}
            {llmError && <p className="internal-llm-error" role="alert">{llmError}</p>}
            <p className="internal-llm-footnote">
              API Key 仅从服务器 `.env` 读取，浏览器不会获取或保存密钥。
            </p>
          </article>
        )}

        <article className="internal-settings-card internal-settings-security">
          <header>
            <span className="internal-settings-card-icon amber"><KeyRound size={19} /></span>
            <div>
              <h3>登录与安全</h3>
              <p>管理当前浏览器中的登录状态。</p>
            </div>
          </header>
          <div className="internal-settings-session">
            <span><ShieldCheck size={18} /></span>
            <div>
              <strong>当前会话已受保护</strong>
              <p>退出后，此浏览器会清除当前工作台会话及已载入的业务数据。</p>
            </div>
          </div>
          <div className="internal-settings-security-footer">
            <p>密码由 StarRC 管理员或 FileMaker“安全性”统一维护。</p>
            <button type="button" onClick={onSignOut}>
              <LogOut size={17} />
              退出当前账号
            </button>
          </div>
        </article>
      </div>
    </section>
  );
}
