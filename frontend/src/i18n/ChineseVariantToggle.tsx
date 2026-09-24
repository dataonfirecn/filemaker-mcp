import { useChineseVariant, type ChineseVariant } from "./chineseVariant";
import "./ChineseVariantToggle.css";

// 选项文字自带各自字形，并用 translate="no" 保证不被转换：切到繁体后「简体」仍显示为简体。
const OPTIONS: { value: ChineseVariant; label: string; lang: string }[] = [
  { value: "zh-Hans", label: "简体", lang: "zh-Hans" },
  { value: "zh-Hant", label: "繁體", lang: "zh-Hant" }
];

/** 简体 / 繁体分段切换（用户菜单、登录页）。 */
export function ChineseVariantToggle({ className = "" }: { className?: string }) {
  const [variant, setVariant] = useChineseVariant();

  return (
    <div className={["cv-toggle", className].filter(Boolean).join(" ")} role="group" aria-label="中文字形" translate="no">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          lang={option.lang}
          aria-pressed={variant === option.value}
          onClick={() => setVariant(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** 单个紧凑按钮：显示「切换到」的那种字形（WebViewer 顶栏用，占位小）。 */
export function ChineseVariantSwitchButton({ className = "" }: { className?: string }) {
  const [variant, setVariant] = useChineseVariant();
  const toTraditional = variant === "zh-Hans";
  const label = toTraditional ? "繁體" : "简体";
  const title = toTraditional ? "切換為繁體中文" : "切换为简体中文";

  return (
    <button
      type="button"
      className={["cv-switch", className].filter(Boolean).join(" ")}
      lang={toTraditional ? "zh-Hant" : "zh-Hans"}
      title={title}
      aria-label={title}
      translate="no"
      onClick={() => setVariant(toTraditional ? "zh-Hant" : "zh-Hans")}
    >
      {label}
    </button>
  );
}
