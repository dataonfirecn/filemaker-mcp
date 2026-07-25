import { useEffect, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  Loader2,
  LockKeyhole,
  Moon,
  PackageSearch,
  ShieldCheck,
  Sparkles,
  Sun,
  UserRound
} from "lucide-react";
import type { ThemeMode } from "../types";
import CustomerPortalContent from "./CustomerPortalContent";
import {
  normalizeCustomerProfile,
  requestJson,
  type CustomerPasswordChangeResponse,
  type CustomerProfile
} from "./customerPortalApi";

const tokenStorageKey = "customer-portal-token";
const themeStorageKey = "customer-portal-theme";

type LoginResponse = {
  token: string;
  expiresAt: number;
  customer: CustomerProfile;
};

function initialTheme(): ThemeMode {
  const stored = window.localStorage.getItem(themeStorageKey);
  if (stored === "light" || stored === "dark") return stored;
  return "light";
}

export default function CustomerChatApp() {
  const [theme, setTheme] = useState<ThemeMode>(() => initialTheme());
  const [token, setToken] = useState(() => window.sessionStorage.getItem(tokenStorageKey) ?? "");
  const [profile, setProfile] = useState<CustomerProfile | null>(null);
  const [restoring, setRestoring] = useState(Boolean(token));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem(themeStorageKey, theme);
  }, [theme]);

  useEffect(() => {
    document.title = "Customer Inventory Portal";
  }, []);

  useEffect(() => {
    if (!token || profile) {
      setRestoring(false);
      return;
    }
    let active = true;
    void requestJson<CustomerProfile>("/api/customer-chat/me", {}, token)
      .then((data) => {
        if (active) setProfile(normalizeCustomerProfile(data));
      })
      .catch(() => {
        if (!active) return;
        window.sessionStorage.removeItem(tokenStorageKey);
        setToken("");
      })
      .finally(() => {
        if (active) setRestoring(false);
      });
    return () => { active = false; };
  }, [token, profile]);

  function logout(message?: string) {
    window.sessionStorage.removeItem(tokenStorageKey);
    window.history.replaceState({}, "", "/customer-chat");
    setToken("");
    setProfile(null);
    setPassword("");
    setLoginError(message ?? null);
  }

  function renewSession(result: CustomerPasswordChangeResponse) {
    window.sessionStorage.setItem(tokenStorageKey, result.token);
    setToken(result.token);
    setProfile(normalizeCustomerProfile(result.customer));
  }

  async function handleLogin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!username.trim() || !password) {
      setLoginError("Enter your customer ID and password.");
      return;
    }
    setLoginLoading(true);
    setLoginError(null);
    try {
      const result = await requestJson<LoginResponse>("/api/customer-chat/login", {
        method: "POST",
        body: JSON.stringify({ username: username.trim(), password })
      });
      window.sessionStorage.setItem(tokenStorageKey, result.token);
      setToken(result.token);
      setProfile(normalizeCustomerProfile(result.customer));
      setPassword("");
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : "Sign-in failed. Please try again.");
    } finally {
      setLoginLoading(false);
    }
  }

  const themeToggle = (
    <button
      className="cp-icon-btn cp-login-theme"
      type="button"
      onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
    >
      {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );

  if (restoring) {
    return (
      <div className="cp-root cp-auth-loading" aria-live="polite">
        <span className="cp-brand-mark" aria-hidden="true"><PackageSearch size={22} /></span>
        <Loader2 className="spin" size={22} />
        <p>Restoring your secure session…</p>
      </div>
    );
  }

  if (profile && token) {
    return (
      <CustomerPortalContent
        token={token}
        profile={profile}
        theme={theme}
        onThemeChange={setTheme}
        onSessionRenewed={renewSession}
        onLogout={logout}
      />
    );
  }

  return (
    <main className="cp-root cp-login">
      <section className="cp-login-brand" aria-label="Customer inventory portal introduction">
        <div className="cp-brand">
          <span className="cp-brand-mark" aria-hidden="true"><PackageSearch size={18} /></span>
          <span><strong>Customer Portal</strong><small>Orders, Products &amp; Parts</small></span>
        </div>
        <span className="cp-login-badge"><Sparkles size={14} /> Product &amp; inventory workspace</span>
        <h1>Find the parts<br />you need, <em>fast.</em></h1>
        <p className="cp-login-sub">Sign in to browse orders, product and part catalogs, live inventory, shipment details, and BOM data.</p>
        <ul className="cp-login-features">
          <li><span className="cp-fi"><ShieldCheck size={16} /></span><div><strong>Account-scoped results</strong><span>Only records assigned to your account are returned</span></div></li>
          <li><span className="cp-fi"><PackageSearch size={16} /></span><div><strong>Orders and catalogs</strong><span>Search shipments, products, parts, inventory and BOM data</span></div></li>
          <li><span className="cp-fi"><CheckCircle2 size={16} /></span><div><strong>Read-only access</strong><span>This portal cannot modify business data</span></div></li>
        </ul>
      </section>

      <section className="cp-login-form" aria-label="Customer sign in">
        {themeToggle}
        <form className="cp-login-card" onSubmit={handleLogin}>
          <h2>Customer sign in</h2>
          <p>Use your assigned customer account to continue</p>

          <label className="cp-field">
            <span>Customer ID</span>
            <span className="cp-control">
              <UserRound size={17} />
              <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" placeholder="Enter your customer ID" disabled={loginLoading} autoFocus />
            </span>
          </label>

          <label className="cp-field">
            <span>Password</span>
            <span className="cp-control">
              <LockKeyhole size={17} />
              <input type={showPassword ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" placeholder="Enter your password" disabled={loginLoading} />
              <button className="cp-eye" type="button" onClick={() => setShowPassword((current) => !current)} aria-label={showPassword ? "Hide password" : "Show password"} title={showPassword ? "Hide password" : "Show password"}>
                {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </span>
          </label>

          {loginError && <div className="cp-login-error" role="alert">{loginError}</div>}
          <button className="cp-btn-primary" type="submit" disabled={loginLoading}>
            {loginLoading ? <Loader2 className="spin" size={18} /> : <LockKeyhole size={17} />}
            {loginLoading ? "Signing in…" : "Sign in securely"}
            {!loginLoading && <ArrowRight size={17} />}
          </button>
          <p className="cp-login-hint">Contact your account representative if you need access or assistance.</p>
        </form>
      </section>
    </main>
  );
}
