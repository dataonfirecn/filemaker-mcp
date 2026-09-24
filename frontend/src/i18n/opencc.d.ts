// tsconfig 使用 moduleResolution: Node，不会读取 opencc-js 的 exports 子路径，这里补一份最小类型声明。
declare module "opencc-js/cn2t" {
  export type ToLocale = "t" | "tw" | "twp" | "hk" | "jp";
  export function Converter(options: { from: "cn"; to: ToLocale }): (text: string) => string;
}

// 由 vite-plugins/uiStrings.ts 在构建时生成：源码里写死的界面中文文案清单。
declare module "virtual:ui-strings" {
  const uiStrings: { exact: string[]; templates: string[][] };
  export default uiStrings;
}
