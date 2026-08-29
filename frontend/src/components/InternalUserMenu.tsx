import { ChevronDown, LogOut, Settings, ShieldCheck, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export type InternalUserMenuUser = {
  username: string;
  displayName: string;
  privilegeSet: string;
};

export type InternalUserMenuProps = {
  user: InternalUserMenuUser;
  canManageAccounts: boolean;
  onOpenSettings: () => void;
  onOpenAccountAdmin?: () => void;
  onSignOut: () => void;
};

function userInitials(user: InternalUserMenuUser): string {
  const source = user.displayName.trim() || user.username.trim() || "U";
  return Array.from(source).slice(0, 2).join("").toUpperCase();
}

export default function InternalUserMenu({
  user,
  canManageAccounts,
  onOpenSettings,
  onOpenAccountAdmin,
  onSignOut
}: InternalUserMenuProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: PointerEvent) {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  function run(action: () => void) {
    setOpen(false);
    action();
  }

  return (
    <div className="internal-user-menu" ref={menuRef}>
      <button
        className="internal-user-trigger"
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="internal-user-avatar" aria-hidden="true">
          {userInitials(user)}
        </span>
        <span className="internal-user-trigger-copy">
          <strong>{user.displayName || user.username}</strong>
          <small>{user.username}</small>
        </span>
        <ChevronDown className={open ? "open" : ""} size={16} aria-hidden="true" />
      </button>

      {open && (
        <div className="internal-user-popover" role="menu" aria-label="用户菜单">
          <div className="internal-user-summary">
            <span className="internal-user-avatar large" aria-hidden="true">
              {userInitials(user)}
            </span>
            <div>
              <strong>{user.displayName || user.username}</strong>
              <small>@{user.username}</small>
            </div>
          </div>

          <div className="internal-user-privilege">
            <ShieldCheck size={14} />
            <span>{user.privilegeSet || "未指定权限集"}</span>
          </div>

          <div className="internal-user-actions">
            <button type="button" role="menuitem" onClick={() => run(onOpenSettings)}>
              <Settings size={17} />
              <span>
                <strong>个人设置</strong>
                <small>外观、账号与会话</small>
              </span>
            </button>

            {canManageAccounts && onOpenAccountAdmin && (
              <button type="button" role="menuitem" onClick={() => run(onOpenAccountAdmin)}>
                <UserRound size={17} />
                <span>
                  <strong>账号与权限</strong>
                  <small>管理 StarRC 用户</small>
                </span>
              </button>
            )}
          </div>

          <div className="internal-user-signout">
            <button type="button" role="menuitem" onClick={() => run(onSignOut)}>
              <LogOut size={17} />
              <span>退出登录</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
