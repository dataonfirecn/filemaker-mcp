import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  BadgeDollarSign,
  CheckCircle2,
  KeyRound,
  Loader2,
  Mail,
  Pencil,
  Power,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  UserPlus,
  UsersRound,
  X
} from "lucide-react";
import type {
  WebViewerAccountAdminResponse,
  WebViewerAdminAccount,
  WebViewerAdminPrivilegeSet,
  WebViewerPermissions
} from "../types";
import { parseError } from "../utils/error";

type InternalAccountAdminPageProps = {
  apiBase: string;
  token: string;
  currentUsername: string;
};

type PermissionKey = keyof WebViewerPermissions;
type AccountDraft = Pick<WebViewerAdminAccount, "enabled" | "permissions">;
type PrivilegeDraft = Pick<WebViewerAdminPrivilegeSet, "enabled" | "permissions">;
type AccountFilter = "all" | "enabled" | "disabled" | "price";

const permissionOptions: Array<{
  key: PermissionKey;
  label: string;
  description: string;
  critical?: boolean;
}> = [
  {
    key: "canViewPrice",
    label: "查看价格",
    description: "产品售价、订单金额、批次价格及成本字段",
    critical: true
  },
  {
    key: "canManageAccounts",
    label: "账号管理",
    description: "查看和修改 StarRC 账号与权限集"
  },
  {
    key: "canViewProducts",
    label: "产品资料",
    description: "产品列表、产品详情及相关字段"
  },
  {
    key: "canViewOrders",
    label: "订单资料",
    description: "订单列表、订单详情及图片"
  },
  {
    key: "canViewInventory",
    label: "库存流水",
    description: "产品出入库与库存趋势"
  },
  {
    key: "canViewBom",
    label: "BOM / 发料",
    description: "BOM、零件、发料和物料编码"
  },
  {
    key: "canUseNaturalQuery",
    label: "智能问答",
    description: "FileMaker 自然语言查询"
  },
  {
    key: "canManageRag",
    label: "RAG 控制",
    description: "索引刷新、OData 关系与分析"
  },
  {
    key: "canMergeOrders",
    label: "合并订单",
    description: "预览并执行内部订单合并"
  }
];

async function requestJson<T>(
  apiBase: string,
  token: string,
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init.headers ?? {})
    }
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

function formatDateTime(value: string | null): string {
  if (!value) return "尚未从 FileMaker 登录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function PermissionGrid({
  permissions,
  onChange,
  disabled,
  lockedKeys = []
}: {
  permissions: WebViewerPermissions;
  onChange: (key: PermissionKey, value: boolean) => void;
  disabled?: boolean;
  lockedKeys?: PermissionKey[];
}) {
  return (
    <div className="internal-access-permission-grid">
      {permissionOptions.map((option) => (
        <label
          className={`internal-access-permission ${option.critical ? "critical" : ""}`}
          key={option.key}
        >
          <input
            type="checkbox"
            checked={permissions[option.key]}
            onChange={(event) => onChange(option.key, event.target.checked)}
            disabled={disabled || lockedKeys.includes(option.key)}
          />
          <span>
            <strong>{option.label}</strong>
            <small>{option.description}</small>
          </span>
        </label>
      ))}
    </div>
  );
}

export default function InternalAccountAdminPage({
  apiBase,
  token,
  currentUsername
}: InternalAccountAdminPageProps) {
  const [data, setData] = useState<WebViewerAccountAdminResponse | null>(null);
  const [tab, setTab] = useState<"accounts" | "privilegeSets">("accounts");
  const [accountDrafts, setAccountDrafts] = useState<Record<string, AccountDraft>>({});
  const [privilegeDrafts, setPrivilegeDrafts] = useState<Record<string, PrivilegeDraft>>({});
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showRegister, setShowRegister] = useState(false);
  const [editingUsername, setEditingUsername] = useState<string | null>(null);
  const [accountQuery, setAccountQuery] = useState("");
  const [accountFilter, setAccountFilter] = useState<AccountFilter>("all");
  const [registerForm, setRegisterForm] = useState({
    username: "",
    displayName: "",
    filemakerPrivilegeSet: ""
  });
  const [showSendCredentials, setShowSendCredentials] = useState(false);
  const [credentialsEmail, setCredentialsEmail] = useState("");

  const privilegeSetNames = useMemo(
    () => data?.privilegeSets.map((item) => item.name) ?? [],
    [data]
  );
  const accountMetrics = useMemo(() => {
    const accounts = data?.accounts ?? [];
    return {
      total: accounts.length,
      enabled: accounts.filter((account) => account.enabled).length,
      price: accounts.filter(
        (account) => account.enabled && account.permissions.canViewPrice
      ).length,
      admins: accounts.filter(
        (account) => account.enabled && account.permissions.canManageAccounts
      ).length
    };
  }, [data]);
  const filteredAccounts = useMemo(() => {
    const normalizedQuery = accountQuery.trim().toLocaleLowerCase();
    return (data?.accounts ?? []).filter((account) => {
      const matchesQuery =
        !normalizedQuery ||
        account.username.toLocaleLowerCase().includes(normalizedQuery) ||
        account.displayName.toLocaleLowerCase().includes(normalizedQuery) ||
        account.filemakerPrivilegeSet.toLocaleLowerCase().includes(normalizedQuery);
      const matchesFilter =
        accountFilter === "all" ||
        (accountFilter === "enabled" && account.enabled) ||
        (accountFilter === "disabled" && !account.enabled) ||
        (accountFilter === "price" && account.enabled && account.permissions.canViewPrice);
      return matchesQuery && matchesFilter;
    });
  }, [accountFilter, accountQuery, data]);
  const editingAccount = useMemo(
    () =>
      editingUsername
        ? data?.accounts.find((account) => account.username === editingUsername) ?? null
        : null,
    [data, editingUsername]
  );

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const result = await requestJson<WebViewerAccountAdminResponse>(
        apiBase,
        token,
        "/api/webviewer/admin/accounts"
      );
      setData(result);
      setAccountDrafts(
        Object.fromEntries(
          result.accounts.map((account) => [
            account.username,
            { enabled: account.enabled, permissions: { ...account.permissions } }
          ])
        )
      );
      setPrivilegeDrafts(
        Object.fromEntries(
          result.privilegeSets.map((item) => [
            item.name,
            { enabled: item.enabled, permissions: { ...item.permissions } }
          ])
        )
      );
    } catch (err) {
      setError(parseError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // The active session token is the authority boundary for this page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function updateAccountPermission(
    account: WebViewerAdminAccount,
    key: PermissionKey,
    value: boolean
  ) {
    setAccountDrafts((current) => ({
      ...current,
      [account.username]: {
        ...(current[account.username] ?? {
          enabled: account.enabled,
          permissions: account.permissions
        }),
        permissions: {
          ...(current[account.username]?.permissions ?? account.permissions),
          [key]: value
        }
      }
    }));
  }

  async function saveAccount(
    account: WebViewerAdminAccount,
    inheritPrivilegeSet = false,
    nextDraft?: AccountDraft
  ): Promise<boolean> {
    const draft = nextDraft ?? accountDrafts[account.username];
    if (!draft) return false;
    setSavingKey(`account:${account.username}`);
    setError(null);
    setNotice(null);
    try {
      const updated = await requestJson<WebViewerAdminAccount>(
        apiBase,
        token,
        `/api/webviewer/admin/accounts/${encodeURIComponent(account.username)}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            enabled: draft.enabled,
            permissions: draft.permissions,
            inheritPrivilegeSet
          })
        }
      );
      setData((current) =>
        current
          ? {
              ...current,
              accounts: current.accounts.map((item) =>
                item.username === updated.username ? updated : item
              )
            }
          : current
      );
      setAccountDrafts((current) => ({
        ...current,
        [updated.username]: {
          enabled: updated.enabled,
          permissions: { ...updated.permissions }
        }
      }));
      setNotice(
        inheritPrivilegeSet
          ? `${updated.displayName} 已恢复跟随 FileMaker 权限集。`
          : `${updated.displayName} 的 StarRC 权限已保存。`
      );
      return true;
    } catch (err) {
      setError(parseError(err));
      return false;
    } finally {
      setSavingKey("");
    }
  }

  async function quickUpdateAccount(
    account: WebViewerAdminAccount,
    change: {
      enabled?: boolean;
      permission?: { key: PermissionKey; value: boolean };
    }
  ) {
    const current = accountDrafts[account.username] ?? {
      enabled: account.enabled,
      permissions: account.permissions
    };
    const draft: AccountDraft = {
      enabled: change.enabled ?? current.enabled,
      permissions: change.permission
        ? {
            ...current.permissions,
            [change.permission.key]: change.permission.value
          }
        : current.permissions
    };
    setAccountDrafts((drafts) => ({ ...drafts, [account.username]: draft }));
    await saveAccount(account, false, draft);
  }

  function openAccountEditor(account: WebViewerAdminAccount) {
    setAccountDrafts((current) => ({
      ...current,
      [account.username]: {
        enabled: account.enabled,
        permissions: { ...account.permissions }
      }
    }));
    setEditingUsername(account.username);
  }

  async function savePrivilegeSet(item: WebViewerAdminPrivilegeSet) {
    const draft = privilegeDrafts[item.name];
    if (!draft) return;
    setSavingKey(`privilege:${item.name}`);
    setError(null);
    setNotice(null);
    try {
      const updated = await requestJson<WebViewerAdminPrivilegeSet>(
        apiBase,
        token,
        `/api/webviewer/admin/privilege-sets/${encodeURIComponent(item.name)}`,
        {
          method: "PATCH",
          body: JSON.stringify(draft)
        }
      );
      setData((current) =>
        current
          ? {
              ...current,
              privilegeSets: current.privilegeSets.map((entry) =>
                entry.name === updated.name ? updated : entry
              )
            }
          : current
      );
      setNotice(`${updated.name} 的默认权限已保存，未单独覆盖的账号会立即继承。`);
      await load();
    } catch (err) {
      setError(parseError(err));
    } finally {
      setSavingKey("");
    }
  }

  async function registerAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSavingKey("register");
    setError(null);
    setNotice(null);
    try {
      await requestJson<WebViewerAdminAccount>(
        apiBase,
        token,
        "/api/webviewer/admin/accounts",
        { method: "POST", body: JSON.stringify(registerForm) }
      );
      setRegisterForm({ username: "", displayName: "", filemakerPrivilegeSet: "" });
      setShowRegister(false);
      setNotice("账号映射已建立；该账号仍需在 FileMaker“安全性”中存在才能登录。");
      await load();
    } catch (err) {
      setError(parseError(err));
    } finally {
      setSavingKey("");
    }
  }

  async function sendCredentials(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const recipient = credentialsEmail.trim();
    if (!recipient) return;
    setSavingKey("send-credentials");
    setError(null);
    setNotice(null);
    try {
      await requestJson<{ ok: boolean; recipient: string }>(
        apiBase,
        token,
        "/api/webviewer/admin/accounts/send-credentials",
        {
          method: "POST",
          body: JSON.stringify({ recipientEmail: recipient })
        }
      );
      setNotice(`管理员登录信息已发送到 ${recipient}。`);
      setCredentialsEmail("");
      setShowSendCredentials(false);
    } catch (err) {
      setError(parseError(err));
    } finally {
      setSavingKey("");
    }
  }

  return (
    <section className="internal-access-page">
      <div className="internal-access-hero">
        <div>
          <span className="internal-access-eyebrow"><ShieldCheck size={15} /> 双层授权</span>
          <h2>FileMaker 账号与 StarRC 权限</h2>
          <p>
            FileMaker 权限集决定账号身份和数据库基础权限；StarRC 再控制网页功能与价格字段。
            权限修改会在下一次接口请求立即生效。
          </p>
        </div>
        <div className="internal-access-price-card">
          <KeyRound size={21} />
          <span><strong>价格默认关闭</strong><small>只有明确授权的账号才会收到价格字段</small></span>
        </div>
      </div>

      <div className="internal-access-metrics" aria-label="账号权限概览">
        <div><small>账号总数</small><strong>{accountMetrics.total}</strong></div>
        <div><small>允许登录</small><strong>{accountMetrics.enabled}</strong></div>
        <div className="price"><small>可查看价格</small><strong>{accountMetrics.price}</strong></div>
        <div><small>系统管理员</small><strong>{accountMetrics.admins}</strong></div>
      </div>

      <div className="internal-access-toolbar">
        <div className="internal-access-tabs" role="tablist" aria-label="权限管理范围">
          <button className={tab === "accounts" ? "active" : ""} type="button" onClick={() => setTab("accounts")}>
            <UsersRound size={16} />账号 {data?.accounts.length ?? 0}
          </button>
          <button className={tab === "privilegeSets" ? "active" : ""} type="button" onClick={() => setTab("privilegeSets")}>
            <ShieldCheck size={16} />权限集 {data?.privilegeSets.length ?? 0}
          </button>
        </div>
        <div className="internal-access-actions">
          {tab === "accounts" && (
            <>
              <button className="btn" type="button" onClick={() => setShowRegister((value) => !value)}>
                <UserPlus size={16} />绑定 FileMaker 账号
              </button>
              <button
                className="btn"
                type="button"
                onClick={() => setShowSendCredentials((value) => !value)}
                title="把 .env 中的 admin 后台登录信息发送到指定邮箱"
              >
                <Mail size={16} />发送管理员登录信息
              </button>
            </>
          )}
          <button className="btn" type="button" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={loading ? "spin" : ""} size={16} />刷新
          </button>
        </div>
      </div>

      {error && <div className="alert" role="alert">{error}</div>}
      {notice && (
        <div className="internal-access-notice" role="status">
          <CheckCircle2 size={17} />{notice}
        </div>
      )}

      {showRegister && (
        <form className="internal-access-register" onSubmit={registerAccount}>
          <label><span>FileMaker 账号名</span><input value={registerForm.username} onChange={(event) => setRegisterForm((current) => ({ ...current, username: event.target.value }))} required /></label>
          <label><span>显示名称</span><input value={registerForm.displayName} onChange={(event) => setRegisterForm((current) => ({ ...current, displayName: event.target.value }))} required /></label>
          <label>
            <span>FileMaker 权限集</span>
            <input
              list="filemaker-privilege-sets"
              value={registerForm.filemakerPrivilegeSet}
              onChange={(event) => setRegisterForm((current) => ({ ...current, filemakerPrivilegeSet: event.target.value }))}
              required
            />
            <datalist id="filemaker-privilege-sets">
              {privilegeSetNames.map((name) => <option key={name} value={name} />)}
            </datalist>
          </label>
          <button className="btn primary" type="submit" disabled={savingKey === "register"}><UserPlus size={16} />建立映射</button>
        </form>
      )}

      {showSendCredentials && (
        <form className="internal-access-register" onSubmit={sendCredentials}>
          <label>
            <span>收件邮箱</span>
            <input
              type="email"
              value={credentialsEmail}
              onChange={(event) => setCredentialsEmail(event.target.value)}
              placeholder="例如 someone@example.com"
              required
            />
          </label>
          <small className="internal-access-register-hint">
            将把后端 .env 中配置的 admin 后台登录信息（用户名与密码）以邮件方式发送给该收件人。
          </small>
          <button className="btn primary" type="submit" disabled={savingKey === "send-credentials"}>
            {savingKey === "send-credentials" ? <Loader2 className="spin" size={16} /> : <Mail size={16} />}
            发送登录信息
          </button>
        </form>
      )}

      {tab === "accounts" && data && (
        <div className="internal-access-filters">
          <label className="internal-access-search">
            <Search size={16} />
            <input
              value={accountQuery}
              onChange={(event) => setAccountQuery(event.target.value)}
              placeholder="搜索账号、姓名或 FileMaker 权限集"
              aria-label="搜索账号"
            />
          </label>
          <select
            value={accountFilter}
            onChange={(event) => setAccountFilter(event.target.value as AccountFilter)}
            aria-label="筛选账号"
          >
            <option value="all">全部账号</option>
            <option value="enabled">允许登录</option>
            <option value="disabled">已停用</option>
            <option value="price">可查看价格</option>
          </select>
          <small>显示 {filteredAccounts.length} / {data.accounts.length}</small>
        </div>
      )}

      {loading && !data && <div className="internal-access-loading">正在读取后台权限…</div>}

      {tab === "accounts" && data && (
        <div className="internal-access-table-card">
          <div className="internal-access-table-head">
            <div><UsersRound size={17} /><strong>StarRC 内部账号</strong></div>
            <small>身份与权限集来自 FileMaker；价格和网页功能在 StarRC 二次授权</small>
          </div>
          <div className="internal-access-table-wrap">
            <table className="internal-access-table">
              <thead>
                <tr>
                  <th>账号</th>
                  <th>FileMaker 权限集</th>
                  <th>登录状态</th>
                  <th>价格权限</th>
                  <th>权限方式</th>
                  <th>最后同步</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredAccounts.map((account) => {
                  const saving = savingKey === `account:${account.username}`;
                  const isSelf =
                    account.username.toLocaleLowerCase() ===
                    currentUsername.toLocaleLowerCase();
                  const enabledPermissionCount = Object.values(account.permissions).filter(
                    Boolean
                  ).length;
                  return (
                    <tr key={account.username}>
                      <td>
                        <span className="internal-access-account-cell">
                          <strong>{account.displayName}</strong>
                          {account.permissions.canManageAccounts && (
                            <span className="internal-access-admin-badge">
                              <ShieldCheck size={11} />管理员
                            </span>
                          )}
                        </span>
                        <small>{account.username}{isSelf ? " · 当前账号" : ""}</small>
                      </td>
                      <td>
                        <span className="internal-access-set-badge">
                          {account.filemakerPrivilegeSet}
                        </span>
                      </td>
                      <td>
                        <button
                          className={`internal-access-quick-toggle ${
                            account.enabled ? "enabled" : "disabled"
                          }`}
                          type="button"
                          disabled={saving || isSelf}
                          title={isSelf ? "不能停用当前管理员账号" : "切换登录状态"}
                          onClick={() =>
                            void quickUpdateAccount(account, {
                              enabled: !account.enabled
                            })
                          }
                        >
                          {saving ? (
                            <Loader2 className="spin" size={14} />
                          ) : (
                            <Power size={14} />
                          )}
                          {account.enabled ? "允许登录" : "已停用"}
                        </button>
                      </td>
                      <td>
                        <button
                          className={`internal-access-quick-toggle ${
                            account.permissions.canViewPrice ? "price-on" : "price-off"
                          }`}
                          type="button"
                          disabled={saving}
                          onClick={() =>
                            void quickUpdateAccount(account, {
                              permission: {
                                key: "canViewPrice",
                                value: !account.permissions.canViewPrice
                              }
                            })
                          }
                        >
                          {saving ? (
                            <Loader2 className="spin" size={14} />
                          ) : (
                            <BadgeDollarSign size={14} />
                          )}
                          {account.permissions.canViewPrice ? "可查看价格" : "价格隐藏"}
                        </button>
                      </td>
                      <td>
                        <strong>{enabledPermissionCount} / {permissionOptions.length} 项</strong>
                        <small>
                          {account.inheritsPrivilegeSet ? "跟随权限集" : "含账号级覆盖"}
                        </small>
                      </td>
                      <td>
                        {formatDateTime(account.lastSeenAt)}
                        <small>
                          {account.origin === "filemaker"
                            ? "FileMaker 会话"
                            : "后台预先绑定"}
                        </small>
                      </td>
                      <td>
                        <button
                          className="btn icon"
                          type="button"
                          title={`编辑 ${account.displayName}`}
                          aria-label={`编辑 ${account.displayName}`}
                          onClick={() => openAccountEditor(account)}
                        >
                          <Pencil size={15} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {filteredAccounts.length === 0 && (
              <div className="internal-access-empty">没有符合当前筛选条件的账号。</div>
            )}
          </div>
        </div>
      )}

      {tab === "privilegeSets" && data && (
        <div className="internal-access-list">
          {data.privilegeSets.map((item) => {
            const draft = privilegeDrafts[item.name] ?? item;
            return (
              <article className="internal-access-card privilege" key={item.name}>
                <header>
                  <div className="internal-access-account-title">
                    <span className={`internal-access-status ${draft.enabled ? "enabled" : "disabled"}`} />
                    <div><strong>{item.name}</strong><small>{item.accountCount} 个已同步账号</small></div>
                  </div>
                  <label className="internal-access-enabled">
                    <input
                      type="checkbox"
                      checked={draft.enabled}
                      onChange={(event) => setPrivilegeDrafts((current) => ({
                        ...current,
                        [item.name]: { ...draft, enabled: event.target.checked }
                      }))}
                    />
                    <span>启用权限集</span>
                  </label>
                </header>
                <PermissionGrid
                  permissions={draft.permissions}
                  onChange={(key, value) => setPrivilegeDrafts((current) => ({
                    ...current,
                    [item.name]: {
                      ...draft,
                      permissions: { ...draft.permissions, [key]: value }
                    }
                  }))}
                />
                <footer>
                  <small>未单独覆盖的账号会实时继承这组设定</small>
                  <button className="btn primary" type="button" onClick={() => void savePrivilegeSet(item)} disabled={Boolean(savingKey)}>
                    <Save size={15} />保存权限集
                  </button>
                </footer>
              </article>
            );
          })}
        </div>
      )}

      {editingAccount && (
        <div className="internal-access-modal-backdrop" role="presentation">
          <div
            className="internal-access-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="internal-access-editor-title"
          >
            <div className="internal-access-modal-head">
              <div>
                <span>账号级 StarRC 授权</span>
                <h3 id="internal-access-editor-title">
                  编辑 {editingAccount.displayName}
                </h3>
                <p>
                  FileMaker 权限集：{editingAccount.filemakerPrivilegeSet}。只保存与权限集不同的项目。
                </p>
              </div>
              <button
                className="btn icon"
                type="button"
                aria-label="关闭"
                disabled={Boolean(savingKey)}
                onClick={() => setEditingUsername(null)}
              >
                <X size={17} />
              </button>
            </div>
            <div className="internal-access-modal-body">
              <div className="internal-access-editor-summary">
                <label className="internal-access-enabled">
                  <input
                    type="checkbox"
                    checked={
                      (accountDrafts[editingAccount.username] ?? editingAccount).enabled
                    }
                    disabled={
                      editingAccount.username.toLocaleLowerCase() ===
                      currentUsername.toLocaleLowerCase()
                    }
                    onChange={(event) =>
                      setAccountDrafts((current) => ({
                        ...current,
                        [editingAccount.username]: {
                          ...(current[editingAccount.username] ?? {
                            enabled: editingAccount.enabled,
                            permissions: editingAccount.permissions
                          }),
                          enabled: event.target.checked
                        }
                      }))
                    }
                  />
                  <span>允许登录 StarRC</span>
                </label>
                <span className={editingAccount.inheritsPrivilegeSet ? "inherited" : "overridden"}>
                  {editingAccount.inheritsPrivilegeSet
                    ? "当前完全跟随权限集"
                    : "当前含账号级覆盖"}
                </span>
              </div>
              <PermissionGrid
                permissions={
                  (accountDrafts[editingAccount.username] ?? editingAccount).permissions
                }
                onChange={(key, value) =>
                  updateAccountPermission(editingAccount, key, value)
                }
                lockedKeys={
                  editingAccount.username.toLocaleLowerCase() ===
                  currentUsername.toLocaleLowerCase()
                    ? ["canManageAccounts"]
                    : []
                }
              />
              <div className="internal-access-price-rule">
                <BadgeDollarSign size={18} />
                <p>
                  <strong>价格查看是敏感权限。</strong>
                  关闭后，页面隐藏价格，后台同时移除售价、成本、金额、报价与批次价格字段。
                </p>
              </div>
            </div>
            <div className="internal-access-modal-footer">
              <div>
                {!editingAccount.inheritsPrivilegeSet && (
                  <button
                    className="btn"
                    type="button"
                    disabled={Boolean(savingKey)}
                    onClick={async () => {
                      if (await saveAccount(editingAccount, true)) {
                        setEditingUsername(null);
                      }
                    }}
                  >
                    恢复跟随权限集
                  </button>
                )}
              </div>
              <div>
                <button
                  className="btn"
                  type="button"
                  disabled={Boolean(savingKey)}
                  onClick={() => setEditingUsername(null)}
                >
                  取消
                </button>
                <button
                  className="btn primary"
                  type="button"
                  disabled={Boolean(savingKey)}
                  onClick={async () => {
                    if (await saveAccount(editingAccount)) {
                      setEditingUsername(null);
                    }
                  }}
                >
                  {savingKey ? (
                    <Loader2 className="spin" size={15} />
                  ) : (
                    <Save size={15} />
                  )}
                  保存权限
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
