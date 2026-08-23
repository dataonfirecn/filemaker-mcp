import {
  Check,
  ChevronRight,
  KeyRound,
  LogOut,
  Moon,
  ShieldCheck,
  Sun,
  UserRound
} from "lucide-react";
import type { ThemeMode, WebViewerPermissions } from "../types";
import type { InternalUserMenuUser } from "./InternalUserMenu";

export type InternalSettingsPageProps = {
  user: InternalUserMenuUser;
  permissions: WebViewerPermissions;
  readOnly: boolean;
  theme: ThemeMode;
  onThemeChange: (theme: ThemeMode) => void;
  onOpenAccountAdmin?: () => void;
  onSignOut: () => void;
};

export default function InternalSettingsPage({
  user,
  permissions,
  readOnly,
  theme,
  onThemeChange,
  onOpenAccountAdmin,
  onSignOut
}: InternalSettingsPageProps) {
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
