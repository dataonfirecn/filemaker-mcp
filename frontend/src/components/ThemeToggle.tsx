import { Moon, Sun } from "lucide-react";
import type { ThemeMode } from "../types";

export type ThemeToggleProps = {
  theme: ThemeMode;
  onToggle: () => void;
  className?: string;
};

export default function ThemeToggle({ theme, onToggle, className = "" }: ThemeToggleProps) {
  const isDark = theme === "dark";
  const Icon = isDark ? Sun : Moon;
  const label = isDark ? "切换到浅色模式" : "切换到深色模式";

  return (
    <button
      className={["theme-toggle", className].filter(Boolean).join(" ")}
      type="button"
      onClick={onToggle}
      aria-label={label}
      title={label}
    >
      <Icon size={18} />
    </button>
  );
}
