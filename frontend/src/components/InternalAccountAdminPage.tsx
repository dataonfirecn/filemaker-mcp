import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  ArrowLeft,
  BadgeDollarSign,
  CheckCircle2,
  Eye,
  KeyRound,
  Loader2,
  Pencil,
  Power,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Smartphone,
  Trash2,
  UserPlus,
  UsersRound
} from "lucide-react";
import type {
  PartPermissionCatalog,
  PartPermissionCatalogGroup,
  PartPermissionMap,
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
type AccountFilter = "all" | "enabled" | "disabled" | "mobile" | "price";
type AdminScreen =
  | "accounts"
  | "privilegeSets"
  | "accountView"
  | "accountEdit"
  | "accountCreate"
  | "privilegeSetEdit";

type AccountDraft = {
  username: string;
  displayName: string;
  filemakerPrivilegeSet: string;
  enabled: boolean;
  mobileOnly: boolean;
  password: string;
  confirmPassword: string;
  permissions: WebViewerPermissions;
  partPermissions: PartPermissionMap;
  inheritPrivilegeSet: boolean;
  inheritPartPermissions: boolean;
};

type PrivilegeDraft = {
  enabled: boolean;
  permissions: WebViewerPermissions;
  partPermissions: PartPermissionMap;
};

const blankPermissions: WebViewerPermissions = {
  canViewPrice: false,
  canManageAccounts: false,
  canViewProducts: false,
  canEditProducts: false,
  canEditProductPrices: false,
  canManageProductSync: false,
  canViewOrders: false,
  canViewQuality: false,
  canAddCompletedReceipts: false,
  canViewInventory: false,
  canViewBom: false,
  canUseNaturalQuery: false,
  canManageRag: false,
  canMergeOrders: false
};

const permissionOptions: Array<{
  key: PermissionKey;
  label: string;
  description: string;
  critical?: boolean;
}> = [
  { key: "canEditProducts", label: "编辑产品", description: "新增产品、编辑产品字段与附件" },
  { key: "canEditProductPrices", label: "编辑产品价格", description: "编辑产品价格、成本字段及客户群报价", critical: true },
  { key: "canManageProductSync", label: "处理产品同步", description: "重试同步和处理 FileMaker 冲突", critical: true },
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
    key: "canViewQuality",
    label: "来料品检",
    description: "扫描采购来货、创建并处理来料检查单"
  },
  {
    key: "canAddCompletedReceipts",
    label: "已完成单追加",
    description: "允许对已完成订单继续提交追加入库"
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
  if (!value) return "尚未登录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function emptyPartPermissions(catalog: PartPermissionCatalog | null): PartPermissionMap {
  if (!catalog) return {};
  return Object.fromEntries(
    catalog.groups.flatMap((group) =>
      group.modules.flatMap((module) =>
        module.actions.map((action) => [action.permission, false])
      )
    )
  );
}

function groupPermissionKeys(group: PartPermissionCatalogGroup): string[] {
  return group.modules.flatMap((module) =>
    module.actions.map((action) => action.permission)
  );
}

function PermissionGrid({
  permissions,
  onChange,
  disabled,
  lockedKeys = []
}: {
  permissions: WebViewerPermissions;
  onChange?: (key: PermissionKey, value: boolean) => void;
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
            onChange={(event) => onChange?.(option.key, event.target.checked)}
            disabled={disabled || lockedKeys.includes(option.key) || !onChange}
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

function PartPermissionEditor({
  catalog,
  values,
  onChange,
  disabled = false
}: {
  catalog: PartPermissionCatalog;
  values: PartPermissionMap;
  onChange?: (next: PartPermissionMap) => void;
  disabled?: boolean;
}) {
  function setKeys(keys: string[], enabled: boolean) {
    if (!onChange) return;
    const next = { ...values };
    keys.forEach((key) => {
      next[key] = enabled;
    });
    onChange(next);
  }

  return (
    <div className="part-permission-editor">
      {catalog.groups.map((group, groupIndex) => {
        const groupKeys = groupPermissionKeys(group);
        const enabledCount = groupKeys.filter((key) => values[key]).length;
        return (
          <details
            className="part-permission-group"
            key={group.key}
            open={groupIndex === 0}
          >
            <summary>
              <span className="part-permission-group-title">
                <strong>{group.label}</strong>
                <small>{group.description}</small>
              </span>
              <span className="part-permission-count">
                {enabledCount} / {groupKeys.length}
              </span>
            </summary>
            <div className="part-permission-group-body">
              {!disabled && onChange && (
                <div className="part-permission-bulk-actions">
                  <span>组级批量设置</span>
                  <button
                    className="btn"
                    type="button"
                    onClick={() => setKeys(groupKeys, true)}
                  >
                    全部开启
                  </button>
                  <button
                    className="btn"
                    type="button"
                    onClick={() => setKeys(groupKeys, false)}
                  >
                    全部关闭
                  </button>
                </div>
              )}
              {group.modules.map((module) => {
                const moduleKeys = module.actions.map((action) => action.permission);
                const moduleEnabled = moduleKeys.filter((key) => values[key]).length;
                return (
                  <section className="part-permission-module" key={module.key}>
                    <header>
                      <span>
                        <strong>{module.label}</strong>
                        <small>{module.description}</small>
                      </span>
                      <span className="part-permission-module-tools">
                        <em>{moduleEnabled} / {moduleKeys.length}</em>
                        {!disabled && onChange && (
                          <>
                            <button
                              type="button"
                              onClick={() => setKeys(moduleKeys, true)}
                            >
                              全开
                            </button>
                            <button
                              type="button"
                              onClick={() => setKeys(moduleKeys, false)}
                            >
                              全关
                            </button>
                          </>
                        )}
                      </span>
                    </header>
                    <div className="part-permission-actions">
                      {module.actions.map((action) => (
                        <label
                          className={`part-permission-action risk-${action.risk}`}
                          key={action.permission}
                          title={action.description}
                        >
                          <input
                            type="checkbox"
                            checked={Boolean(values[action.permission])}
                            disabled={disabled || !onChange}
                            onChange={(event) =>
                              setKeys([action.permission], event.target.checked)
                            }
                          />
                          <span>{action.label}</span>
                        </label>
                      ))}
                    </div>
                  </section>
                );
              })}
            </div>
          </details>
        );
      })}
    </div>
  );
}

function PartPermissionSummary({
  catalog,
  values
}: {
  catalog: PartPermissionCatalog;
  values: PartPermissionMap;
}) {
  return (
    <div className="part-permission-summary">
      {catalog.groups.map((group) => {
        const keys = groupPermissionKeys(group);
        const enabledActions = keys.filter((key) => values[key]).length;
        const enabledModules = group.modules.filter((module) =>
          module.actions.some((action) => values[action.permission])
        ).length;
        return (
          <article key={group.key}>
            <span>
              <strong>{group.label}</strong>
              <small>{enabledModules} / {group.modules.length} 个模块已授权</small>
            </span>
            <b>{enabledActions} / {keys.length}</b>
          </article>
        );
      })}
    </div>
  );
}

export default function InternalAccountAdminPage({
  apiBase,
  token,
  currentUsername
}: InternalAccountAdminPageProps) {
  const [data, setData] = useState<WebViewerAccountAdminResponse | null>(null);
  const [catalog, setCatalog] = useState<PartPermissionCatalog | null>(null);
  const [screen, setScreen] = useState<AdminScreen>("accounts");
  const [selectedAccount, setSelectedAccount] =
    useState<WebViewerAdminAccount | null>(null);
  const [selectedPrivilegeSet, setSelectedPrivilegeSet] =
    useState<WebViewerAdminPrivilegeSet | null>(null);
  const [accountDraft, setAccountDraft] = useState<AccountDraft | null>(null);
  const [privilegeDraft, setPrivilegeDraft] = useState<PrivilegeDraft | null>(null);
  const [accountQuery, setAccountQuery] = useState("");
  const [accountFilter, setAccountFilter] = useState<AccountFilter>("all");
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [deleteCandidate, setDeleteCandidate] =
    useState<WebViewerAdminAccount | null>(null);

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
        account.filemakerPrivilegeSet
          .toLocaleLowerCase()
          .includes(normalizedQuery);
      const matchesFilter =
        accountFilter === "all" ||
        (accountFilter === "enabled" && account.enabled) ||
        (accountFilter === "disabled" && !account.enabled) ||
        (accountFilter === "mobile" && account.mobileOnly) ||
        (accountFilter === "price" &&
          account.enabled &&
          account.permissions.canViewPrice);
      return matchesQuery && matchesFilter;
    });
  }, [accountFilter, accountQuery, data]);

  async function load(options: { quiet?: boolean } = {}) {
    if (!options.quiet) setLoading(true);
    setError(null);
    try {
      const [accounts, permissionCatalog] = await Promise.all([
        requestJson<WebViewerAccountAdminResponse>(
          apiBase,
          token,
          "/api/webviewer/admin/accounts"
        ),
        requestJson<PartPermissionCatalog>(
          apiBase,
          token,
          "/api/webviewer/admin/part-permission-catalog"
        )
      ]);
      setData(accounts);
      setCatalog(permissionCatalog);
      return accounts;
    } catch (err) {
      setError(parseError(err));
      return null;
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // The active session token is the authority boundary for this page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function findPrivilegeSet(name: string): WebViewerAdminPrivilegeSet | null {
    return (
      data?.privilegeSets.find(
        (item) => item.name.toLocaleLowerCase() === name.toLocaleLowerCase()
      ) ?? null
    );
  }

  function accountToDraft(account: WebViewerAdminAccount): AccountDraft {
    return {
      username: account.username,
      displayName: account.displayName,
      filemakerPrivilegeSet: account.filemakerPrivilegeSet,
      enabled: account.enabled,
      mobileOnly: account.mobileOnly,
      password: "",
      confirmPassword: "",
      permissions: { ...account.permissions },
      partPermissions: { ...account.partPermissions },
      inheritPrivilegeSet: account.inheritsPrivilegeSet,
      inheritPartPermissions: account.inheritsPartPermissions
    };
  }

  async function openAccount(
    account: WebViewerAdminAccount,
    destination: "accountView" | "accountEdit"
  ) {
    setLoading(true);
    setError(null);
    try {
      const detail = await requestJson<WebViewerAdminAccount>(
        apiBase,
        token,
        `/api/webviewer/admin/accounts/${encodeURIComponent(account.username)}`
      );
      setSelectedAccount(detail);
      setAccountDraft(accountToDraft(detail));
      setScreen(destination);
    } catch (err) {
      setError(parseError(err));
    } finally {
      setLoading(false);
    }
  }

  function openCreate() {
    setSelectedAccount(null);
    setAccountDraft({
      username: "",
      displayName: "",
      filemakerPrivilegeSet: "",
      enabled: true,
      mobileOnly: true,
      password: "",
      confirmPassword: "",
      permissions: { ...blankPermissions },
      partPermissions: emptyPartPermissions(catalog),
      inheritPrivilegeSet: true,
      inheritPartPermissions: true
    });
    setScreen("accountCreate");
  }

  function choosePrivilegeSet(name: string) {
    const privilegeSet = findPrivilegeSet(name);
    setAccountDraft((current) =>
      current
        ? {
            ...current,
            filemakerPrivilegeSet: name,
            permissions:
              current.inheritPrivilegeSet && privilegeSet
                ? { ...privilegeSet.permissions }
                : current.permissions,
            partPermissions:
              current.inheritPartPermissions && privilegeSet
                ? { ...privilegeSet.partPermissions }
                : current.partPermissions
          }
        : current
    );
  }

  function toggleLegacyInheritance(enabled: boolean) {
    const privilegeSet = accountDraft
      ? findPrivilegeSet(accountDraft.filemakerPrivilegeSet)
      : null;
    setAccountDraft((current) =>
      current
        ? {
            ...current,
            inheritPrivilegeSet: enabled,
            permissions:
              enabled && privilegeSet
                ? { ...privilegeSet.permissions }
                : current.permissions
          }
        : current
    );
  }

  function togglePartInheritance(enabled: boolean) {
    const privilegeSet = accountDraft
      ? findPrivilegeSet(accountDraft.filemakerPrivilegeSet)
      : null;
    setAccountDraft((current) =>
      current
        ? {
            ...current,
            inheritPartPermissions: enabled,
            partPermissions:
              enabled && privilegeSet
                ? { ...privilegeSet.partPermissions }
                : current.partPermissions
          }
        : current
    );
  }

  async function saveAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accountDraft) return;
    const creating = screen === "accountCreate";
    if (creating && !accountDraft.password) {
      setError("创建账号时必须设置初始密码。");
      return;
    }
    if (accountDraft.password !== accountDraft.confirmPassword) {
      setError("两次输入的密码不一致。");
      return;
    }
    setSavingKey(creating ? "account:create" : `account:${accountDraft.username}`);
    setError(null);
    setNotice(null);
    try {
      const path = creating
        ? "/api/webviewer/admin/accounts"
        : `/api/webviewer/admin/accounts/${encodeURIComponent(accountDraft.username)}`;
      const updated = await requestJson<WebViewerAdminAccount>(
        apiBase,
        token,
        path,
        {
          method: creating ? "POST" : "PATCH",
          body: JSON.stringify({
            username: accountDraft.username,
            displayName: accountDraft.displayName,
            filemakerPrivilegeSet: accountDraft.filemakerPrivilegeSet,
            enabled: accountDraft.enabled,
            mobileOnly: accountDraft.mobileOnly,
            password: accountDraft.password || undefined,
            permissions: accountDraft.permissions,
            partPermissions: accountDraft.partPermissions,
            inheritPrivilegeSet: accountDraft.inheritPrivilegeSet,
            inheritPartPermissions: accountDraft.inheritPartPermissions
          })
        }
      );
      await load({ quiet: true });
      setSelectedAccount(updated);
      setAccountDraft(accountToDraft(updated));
      setScreen("accountView");
      setNotice(
        creating
          ? "Web 账号已建立，可直接使用该账号和密码登录。"
          : `${updated.displayName} 的账号资料与权限已保存。`
      );
    } catch (err) {
      setError(parseError(err));
    } finally {
      setSavingKey("");
    }
  }

  async function deleteAccount() {
    if (!deleteCandidate) return;
    setSavingKey(`delete:${deleteCandidate.username}`);
    setError(null);
    setNotice(null);
    try {
      const result = await requestJson<{
        ok: boolean;
        username: string;
        willResync: boolean;
      }>(
        apiBase,
        token,
        `/api/webviewer/admin/accounts/${encodeURIComponent(
          deleteCandidate.username
        )}`,
        { method: "DELETE" }
      );
      setDeleteCandidate(null);
      setSelectedAccount(null);
      setAccountDraft(null);
      setScreen("accounts");
      await load({ quiet: true });
      setNotice(
        result.willResync
          ? `${result.username} 的 Web 权限记录已删除；旧版同步登录时仍可能重新出现。`
          : `${result.username} 已删除。`
      );
    } catch (err) {
      setError(parseError(err));
    } finally {
      setSavingKey("");
    }
  }

  function openPrivilegeSetEditor(item: WebViewerAdminPrivilegeSet) {
    setSelectedPrivilegeSet(item);
    setPrivilegeDraft({
      enabled: item.enabled,
      permissions: { ...item.permissions },
      partPermissions: { ...item.partPermissions }
    });
    setScreen("privilegeSetEdit");
  }

  async function savePrivilegeSet(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedPrivilegeSet || !privilegeDraft) return;
    setSavingKey(`privilege:${selectedPrivilegeSet.name}`);
    setError(null);
    setNotice(null);
    try {
      const updated = await requestJson<WebViewerAdminPrivilegeSet>(
        apiBase,
        token,
        `/api/webviewer/admin/privilege-sets/${encodeURIComponent(
          selectedPrivilegeSet.name
        )}`,
        {
          method: "PATCH",
          body: JSON.stringify(privilegeDraft)
        }
      );
      setSelectedPrivilegeSet(updated);
      setPrivilegeDraft({
        enabled: updated.enabled,
        permissions: { ...updated.permissions },
        partPermissions: { ...updated.partPermissions }
      });
      await load({ quiet: true });
      setNotice(`${updated.name} 的默认权限已保存，继承账号会立即使用新设置。`);
    } catch (err) {
      setError(parseError(err));
    } finally {
      setSavingKey("");
    }
  }

  const isAccountForm =
    screen === "accountCreate" || screen === "accountEdit";
  const isSelf =
    Boolean(accountDraft) &&
    accountDraft?.username.toLocaleLowerCase() ===
      currentUsername.toLocaleLowerCase();

  return (
    <section className="internal-access-page">
      <div className="internal-access-hero">
        <div>
          <span className="internal-access-eyebrow">
            <ShieldCheck size={15} /> 管理员权限中心
          </span>
          <h2>Web 账号与 StarRC 细粒度权限</h2>
          <p>
            账号、密码哈希、角色和权限保存在 Web 后端；iPad 登录后，每次操作都会
            携带具体账号。所有变更在下一次接口请求生效。
          </p>
        </div>
        <div className="internal-access-price-card">
          <KeyRound size={21} />
          <span>
            <strong>仅管理员可配置</strong>
            <small>前端隐藏入口，后端每个管理接口再次校验管理员权限</small>
          </span>
        </div>
      </div>

      {(screen === "accounts" || screen === "privilegeSets") && (
        <div className="internal-access-metrics" aria-label="账号权限概览">
          <div><small>账号总数</small><strong>{accountMetrics.total}</strong></div>
          <div><small>允许登录</small><strong>{accountMetrics.enabled}</strong></div>
          <div className="price">
            <small>可查看价格</small><strong>{accountMetrics.price}</strong>
          </div>
          <div><small>系统管理员</small><strong>{accountMetrics.admins}</strong></div>
        </div>
      )}

      {(screen === "accounts" || screen === "privilegeSets") && (
        <div className="internal-access-toolbar">
          <div className="internal-access-tabs" role="tablist">
            <button
              className={screen === "accounts" ? "active" : ""}
              type="button"
              onClick={() => setScreen("accounts")}
            >
              <UsersRound size={16} />用户 {data?.accounts.length ?? 0}
            </button>
            <button
              className={screen === "privilegeSets" ? "active" : ""}
              type="button"
              onClick={() => setScreen("privilegeSets")}
            >
              <ShieldCheck size={16} />权限集 {data?.privilegeSets.length ?? 0}
            </button>
          </div>
          <div className="internal-access-actions">
            {screen === "accounts" && (
              <button className="btn primary" type="button" onClick={openCreate}>
                <UserPlus size={16} />新增用户
              </button>
            )}
            <button
              className="btn"
              type="button"
              onClick={() => void load()}
              disabled={loading}
            >
              <RefreshCw className={loading ? "spin" : ""} size={16} />刷新
            </button>
          </div>
        </div>
      )}

      {error && <div className="alert" role="alert">{error}</div>}
      {notice && (
        <div className="internal-access-notice" role="status">
          <CheckCircle2 size={17} />{notice}
        </div>
      )}
      {loading && !data && (
        <div className="internal-access-loading">正在读取后台权限…</div>
      )}

      {screen === "accounts" && data && (
        <>
          <div className="internal-access-filters">
            <label className="internal-access-search">
              <Search size={16} />
              <input
                value={accountQuery}
                onChange={(event) => setAccountQuery(event.target.value)}
                placeholder="搜索账号、姓名或角色"
                aria-label="搜索账号"
              />
            </label>
            <select
              value={accountFilter}
              onChange={(event) =>
                setAccountFilter(event.target.value as AccountFilter)
              }
            >
              <option value="all">全部用户</option>
              <option value="enabled">允许登录</option>
              <option value="disabled">已停用</option>
              <option value="mobile">仅移动端</option>
              <option value="price">可查看价格</option>
            </select>
            <small>显示 {filteredAccounts.length} / {data.accounts.length}</small>
          </div>
          <div className="internal-access-table-card">
            <div className="internal-access-table-head">
              <div><UsersRound size={17} /><strong>StarRC 内部用户</strong></div>
              <small>列表只显示摘要；查看页与编辑页已分开</small>
            </div>
            <div className="internal-access-table-wrap">
              <table className="internal-access-table">
                <thead>
                  <tr>
                    <th>用户</th>
                    <th>账号角色</th>
                    <th>状态</th>
                    <th>基础权限</th>
                    <th>6 组细分权限</th>
                    <th>最后同步</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAccounts.map((account) => {
                    const legacyCount = Object.values(account.permissions).filter(
                      Boolean
                    ).length;
                    const partCount = Object.values(account.partPermissions).filter(
                      Boolean
                    ).length;
                    const self =
                      account.username.toLocaleLowerCase() ===
                      currentUsername.toLocaleLowerCase();
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
                          <small>{account.username}{self ? " · 当前用户" : ""}</small>
                        </td>
                        <td>
                          <span className="internal-access-set-badge">
                            {account.filemakerPrivilegeSet}
                          </span>
                        </td>
                        <td>
                          <span
                            className={`internal-access-state-label ${
                              account.enabled ? "enabled" : "disabled"
                            }`}
                          >
                            <Power size={13} />
                            {account.enabled ? "允许登录" : "已停用"}
                          </span>
                          {account.mobileOnly && (
                            <small><Smartphone size={12} />仅移动端</small>
                          )}
                        </td>
                        <td>
                          <strong>{legacyCount} / {permissionOptions.length}</strong>
                          <small>
                            {account.inheritsPrivilegeSet ? "继承" : "用户覆盖"}
                          </small>
                        </td>
                        <td>
                          <strong>{partCount} / {catalog?.permissionCount ?? 0}</strong>
                          <small>
                            {account.inheritsPartPermissions ? "继承" : "用户覆盖"}
                          </small>
                        </td>
                        <td>
                          {formatDateTime(account.lastSeenAt)}
                          <small>
                            {account.origin === "filemaker"
                              ? "旧版同步账号"
                              : "Web 账号"}
                          </small>
                        </td>
                        <td>
                          <div className="internal-access-row-actions">
                            <button
                              className="btn icon"
                              type="button"
                              title="查看"
                              onClick={() => void openAccount(account, "accountView")}
                            >
                              <Eye size={15} />
                            </button>
                            <button
                              className="btn icon"
                              type="button"
                              title="编辑"
                              onClick={() => void openAccount(account, "accountEdit")}
                            >
                              <Pencil size={15} />
                            </button>
                            <button
                              className="btn icon danger"
                              type="button"
                              title={self ? "不能删除当前用户" : "删除"}
                              disabled={self}
                              onClick={() => setDeleteCandidate(account)}
                            >
                              <Trash2 size={15} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {filteredAccounts.length === 0 && (
                <div className="internal-access-empty">
                  没有符合当前筛选条件的用户。
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {screen === "privilegeSets" && data && (
        <div className="internal-access-table-card">
          <div className="internal-access-table-head">
            <div><ShieldCheck size={17} /><strong>账号角色默认值</strong></div>
            <small>用户可完全继承，也可在用户编辑页逐项覆盖</small>
          </div>
          <div className="internal-access-table-wrap">
            <table className="internal-access-table">
              <thead>
                <tr>
                  <th>权限集</th>
                  <th>状态</th>
                  <th>用户数</th>
                  <th>基础权限</th>
                  <th>6 组细分权限</th>
                  <th>最后修改</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {data.privilegeSets.map((item) => (
                  <tr key={item.name}>
                    <td><strong>{item.name}</strong></td>
                    <td>
                      <span
                        className={`internal-access-state-label ${
                          item.enabled ? "enabled" : "disabled"
                        }`}
                      >
                        <Power size={13} />{item.enabled ? "启用" : "停用"}
                      </span>
                    </td>
                    <td>{item.accountCount}</td>
                    <td>
                      {Object.values(item.permissions).filter(Boolean).length} /{" "}
                      {permissionOptions.length}
                    </td>
                    <td>
                      {Object.values(item.partPermissions).filter(Boolean).length} /{" "}
                      {catalog?.permissionCount ?? 0}
                    </td>
                    <td>
                      {formatDateTime(item.updatedAt)}
                      <small>{item.updatedBy}</small>
                    </td>
                    <td>
                      <button
                        className="btn"
                        type="button"
                        onClick={() => openPrivilegeSetEditor(item)}
                      >
                        <Pencil size={15} />配置默认权限
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {screen === "accountView" && selectedAccount && catalog && (
        <div className="internal-access-detail-page">
          <div className="internal-access-page-head">
            <button
              className="btn"
              type="button"
              onClick={() => setScreen("accounts")}
            >
              <ArrowLeft size={16} />返回用户列表
            </button>
            <div>
              <span>用户显示页 · 只读</span>
              <h3>{selectedAccount.displayName}</h3>
              <p>{selectedAccount.username}</p>
            </div>
            <div className="internal-access-actions">
              <button
                className="btn primary"
                type="button"
                onClick={() => {
                  setAccountDraft(accountToDraft(selectedAccount));
                  setScreen("accountEdit");
                }}
              >
                <Pencil size={16} />进入编辑页
              </button>
              <button
                className="btn danger"
                type="button"
                disabled={
                  selectedAccount.username.toLocaleLowerCase() ===
                  currentUsername.toLocaleLowerCase()
                }
                onClick={() => setDeleteCandidate(selectedAccount)}
              >
                <Trash2 size={16} />删除用户
              </button>
            </div>
          </div>
          <div className="internal-access-identity-grid">
            <article><small>账号角色</small><strong>{selectedAccount.filemakerPrivilegeSet}</strong></article>
            <article><small>登录状态</small><strong>{selectedAccount.enabled ? "允许登录" : "已停用"}</strong></article>
            <article><small>登录入口</small><strong>{selectedAccount.mobileOnly ? "仅移动端" : "Web 与移动端"}</strong></article>
            <article><small>密码状态</small><strong>{selectedAccount.hasPassword ? "已设置" : "未设置"}</strong></article>
            <article><small>账号来源</small><strong>{selectedAccount.origin === "filemaker" ? "旧版同步账号" : "Web 后台"}</strong></article>
            <article><small>最后登录</small><strong>{formatDateTime(selectedAccount.lastSeenAt)}</strong></article>
          </div>
          <section className="internal-access-section">
            <header>
              <div>
                <h4>StarRC 基础功能</h4>
                <p>
                  {selectedAccount.inheritsPrivilegeSet
                    ? "完全继承账号角色默认值"
                    : "包含用户级覆盖"}
                </p>
              </div>
            </header>
            <PermissionGrid permissions={selectedAccount.permissions} disabled />
          </section>
          <section className="internal-access-section">
            <header>
              <div>
                <h4>6 组业务权限摘要</h4>
                <p>
                  {selectedAccount.inheritsPartPermissions
                    ? "完全继承权限集默认值"
                    : "包含用户级细分权限覆盖"}
                </p>
              </div>
            </header>
            <PartPermissionSummary
              catalog={catalog}
              values={selectedAccount.partPermissions}
            />
          </section>
          <section className="internal-access-section">
            <header>
              <div>
                <h4>完整权限明细</h4>
                <p>展开每组查看模块和所有独立动作权限。</p>
              </div>
            </header>
            <PartPermissionEditor
              catalog={catalog}
              values={selectedAccount.partPermissions}
              disabled
            />
          </section>
        </div>
      )}

      {isAccountForm && accountDraft && catalog && (
        <form className="internal-access-detail-page" onSubmit={saveAccount}>
          <div className="internal-access-page-head">
            <button
              className="btn"
              type="button"
              onClick={() =>
                setScreen(screen === "accountEdit" ? "accountView" : "accounts")
              }
            >
              <ArrowLeft size={16} />
              {screen === "accountEdit" ? "返回显示页" : "返回用户列表"}
            </button>
            <div>
              <span>{screen === "accountCreate" ? "用户新增页" : "用户编辑页"}</span>
              <h3>
                {screen === "accountCreate"
                  ? "新增 StarRC 用户"
                  : `编辑 ${accountDraft.displayName}`}
              </h3>
              <p>身份、状态、基础功能和 6 组业务权限在此统一配置。</p>
            </div>
            <button
              className="btn primary"
              type="submit"
              disabled={Boolean(savingKey)}
            >
              {savingKey ? (
                <Loader2 className="spin" size={16} />
              ) : (
                <Save size={16} />
              )}
              {screen === "accountCreate" ? "创建用户" : "保存修改"}
            </button>
          </div>

          <section className="internal-access-section">
            <header>
              <div><h4>用户身份与状态</h4><p>账号和密码由 Web 后端独立验证。</p></div>
            </header>
            <div className="internal-access-form-grid">
              <label>
                <span>登录账号</span>
                <input
                  value={accountDraft.username}
                  disabled={screen === "accountEdit"}
                  onChange={(event) =>
                    setAccountDraft((current) =>
                      current ? { ...current, username: event.target.value } : current
                    )
                  }
                  required
                />
              </label>
              <label>
                <span>显示名称</span>
                <input
                  value={accountDraft.displayName}
                  onChange={(event) =>
                    setAccountDraft((current) =>
                      current
                        ? { ...current, displayName: event.target.value }
                        : current
                    )
                  }
                  required
                />
              </label>
              <label>
                <span>{screen === "accountCreate" ? "初始密码" : "重置密码（选填）"}</span>
                <input
                  type="password"
                  value={accountDraft.password}
                  minLength={8}
                  autoComplete="new-password"
                  onChange={(event) =>
                    setAccountDraft((current) =>
                      current ? { ...current, password: event.target.value } : current
                    )
                  }
                  required={screen === "accountCreate"}
                />
                <small>至少 8 位；后端只保存 PBKDF2 密码哈希。</small>
              </label>
              <label>
                <span>确认密码</span>
                <input
                  type="password"
                  value={accountDraft.confirmPassword}
                  minLength={8}
                  autoComplete="new-password"
                  onChange={(event) =>
                    setAccountDraft((current) =>
                      current
                        ? { ...current, confirmPassword: event.target.value }
                        : current
                    )
                  }
                  required={Boolean(accountDraft.password)}
                />
              </label>
              <label>
                <span>账号角色</span>
                <select
                  value={accountDraft.filemakerPrivilegeSet}
                  onChange={(event) => choosePrivilegeSet(event.target.value)}
                  required
                >
                  <option value="">请选择角色</option>
                  {data?.privilegeSets.map((item) => (
                    <option key={item.name} value={item.name}>
                      {item.name}{item.enabled ? "" : "（已停用）"}
                    </option>
                  ))}
                </select>
              </label>
              <label className="internal-access-enabled form-switch">
                <input
                  type="checkbox"
                  checked={accountDraft.enabled}
                  disabled={isSelf}
                  onChange={(event) =>
                    setAccountDraft((current) =>
                      current
                        ? { ...current, enabled: event.target.checked }
                        : current
                    )
                  }
                />
                <span>允许登录 StarRC</span>
              </label>
              <label className="internal-access-enabled form-switch">
                <input
                  type="checkbox"
                  checked={accountDraft.mobileOnly}
                  disabled={isSelf}
                  onChange={(event) =>
                    setAccountDraft((current) =>
                      current
                        ? { ...current, mobileOnly: event.target.checked }
                        : current
                    )
                  }
                />
                <span>仅移动端登录</span>
                <small>启用后禁止登录和访问后台 Web。</small>
              </label>
            </div>
          </section>

          <section className="internal-access-section">
            <header>
              <div>
                <h4>StarRC 基础功能</h4>
                <p>控制价格、产品、订单、库存、BOM、问答和管理功能。</p>
              </div>
              <label className="internal-access-inherit-toggle">
                <input
                  type="checkbox"
                  checked={accountDraft.inheritPrivilegeSet}
                  onChange={(event) =>
                    toggleLegacyInheritance(event.target.checked)
                  }
                />
                <span>继承权限集默认值</span>
              </label>
            </header>
            <PermissionGrid
              permissions={accountDraft.permissions}
              disabled={accountDraft.inheritPrivilegeSet}
              lockedKeys={isSelf ? ["canManageAccounts"] : []}
              onChange={(key, value) =>
                setAccountDraft((current) =>
                  current
                    ? {
                        ...current,
                        permissions: { ...current.permissions, [key]: value }
                      }
                    : current
                )
              }
            />
            <div className="internal-access-price-rule">
              <BadgeDollarSign size={18} />
              <p>
                <strong>价格查看是敏感权限。</strong>
                关闭后，页面隐藏价格，后台同时移除售价、成本、金额、报价与批次价格字段。
              </p>
            </div>
          </section>

          <section className="internal-access-section">
            <header>
              <div>
                <h4>6 组业务细分权限</h4>
                <p>
                  每个模块中的查看、新增、编辑、提交、审核、发布、上传、导出等动作均可独立开关。
                </p>
              </div>
              <label className="internal-access-inherit-toggle">
                <input
                  type="checkbox"
                  checked={accountDraft.inheritPartPermissions}
                  onChange={(event) => togglePartInheritance(event.target.checked)}
                />
                <span>继承权限集默认值</span>
              </label>
            </header>
            <PartPermissionEditor
              catalog={catalog}
              values={accountDraft.partPermissions}
              disabled={accountDraft.inheritPartPermissions}
              onChange={(partPermissions) =>
                setAccountDraft((current) =>
                  current ? { ...current, partPermissions } : current
                )
              }
            />
          </section>

          <div className="internal-access-form-footer">
            <button
              className="btn"
              type="button"
              onClick={() =>
                setScreen(screen === "accountEdit" ? "accountView" : "accounts")
              }
            >
              取消
            </button>
            <button
              className="btn primary"
              type="submit"
              disabled={Boolean(savingKey)}
            >
              {savingKey ? (
                <Loader2 className="spin" size={16} />
              ) : (
                <Save size={16} />
              )}
              {screen === "accountCreate" ? "创建用户" : "保存修改"}
            </button>
          </div>
        </form>
      )}

      {screen === "privilegeSetEdit" &&
        selectedPrivilegeSet &&
        privilegeDraft &&
        catalog && (
          <form className="internal-access-detail-page" onSubmit={savePrivilegeSet}>
            <div className="internal-access-page-head">
              <button
                className="btn"
                type="button"
                onClick={() => setScreen("privilegeSets")}
              >
                <ArrowLeft size={16} />返回权限集列表
              </button>
              <div>
                <span>权限集编辑页</span>
                <h3>{selectedPrivilegeSet.name}</h3>
                <p>{selectedPrivilegeSet.accountCount} 个用户使用此权限集。</p>
              </div>
              <button
                className="btn primary"
                type="submit"
                disabled={Boolean(savingKey)}
              >
                <Save size={16} />保存权限集
              </button>
            </div>
            <section className="internal-access-section">
              <header>
                <div><h4>权限集状态</h4><p>停用后，此权限集下的所有用户都不能登录。</p></div>
                <label className="internal-access-enabled">
                  <input
                    type="checkbox"
                    checked={privilegeDraft.enabled}
                    onChange={(event) =>
                      setPrivilegeDraft((current) =>
                        current
                          ? { ...current, enabled: event.target.checked }
                          : current
                      )
                    }
                  />
                  <span>启用权限集</span>
                </label>
              </header>
            </section>
            <section className="internal-access-section">
              <header><div><h4>StarRC 基础功能默认值</h4><p>继承用户会实时获得这些权限。</p></div></header>
              <PermissionGrid
                permissions={privilegeDraft.permissions}
                onChange={(key, value) =>
                  setPrivilegeDraft((current) =>
                    current
                      ? {
                          ...current,
                          permissions: { ...current.permissions, [key]: value }
                        }
                      : current
                  )
                }
              />
            </section>
            <section className="internal-access-section">
              <header><div><h4>6 组业务权限默认值</h4><p>所有动作都能独立开启或关闭。</p></div></header>
              <PartPermissionEditor
                catalog={catalog}
                values={privilegeDraft.partPermissions}
                onChange={(partPermissions) =>
                  setPrivilegeDraft((current) =>
                    current ? { ...current, partPermissions } : current
                  )
                }
              />
            </section>
            <div className="internal-access-form-footer">
              <button
                className="btn"
                type="button"
                onClick={() => setScreen("privilegeSets")}
              >
                取消
              </button>
              <button
                className="btn primary"
                type="submit"
                disabled={Boolean(savingKey)}
              >
                <Save size={16} />保存权限集
              </button>
            </div>
          </form>
        )}

      {deleteCandidate && (
        <div className="internal-access-modal-backdrop" role="presentation">
          <div
            className="internal-access-delete-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-account-title"
          >
            <span className="internal-access-delete-icon"><Trash2 size={22} /></span>
            <h3 id="delete-account-title">删除 {deleteCandidate.displayName}？</h3>
            <p>
              将删除该用户的 Web 登录密码、角色和权限配置。
              {deleteCandidate.origin === "filemaker" &&
                " 此账号来自旧版同步，下次旧版登录时仍可能重新出现。"}
            </p>
            <div>
              <button
                className="btn"
                type="button"
                disabled={Boolean(savingKey)}
                onClick={() => setDeleteCandidate(null)}
              >
                取消
              </button>
              <button
                className="btn danger"
                type="button"
                disabled={Boolean(savingKey)}
                onClick={() => void deleteAccount()}
              >
                {savingKey ? (
                  <Loader2 className="spin" size={16} />
                ) : (
                  <Trash2 size={16} />
                )}
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}

      {loading && data && (
        <div className="internal-access-page-loading">
          <Loader2 className="spin" size={18} />正在更新…
        </div>
      )}
    </section>
  );
}
