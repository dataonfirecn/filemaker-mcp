import { useSyncExternalStore } from "react";

/**
 * 简体 / 繁体中文显示。
 *
 * 只转换「界面文字」：标题、导航、按钮、标签、表头、提示等——也就是写在源码里的中文文案。
 * 从后端 / FileMaker 读出来的数据（客户名、零件名、订单内容）、用户输入的内容、输入框里的值，
 * 一律保持原样，不做任何转换，避免复制、搜索、回写时出现简繁不一致。
 *
 * 做法：构建时由 vite-plugins/uiStrings.ts 扫描源码，生成「界面文案清单」（virtual:ui-strings）；
 * 选择繁体后按需加载 OpenCC 字典和这份清单，只有内容与清单吻合的文字节点 / placeholder / title / aria-label / alt
 * 才会被转成繁体，并监听后续的 DOM 变化（React 重新渲染、表格滚动加载等）。
 * 模板字符串（如「共 ${n} 条」）只转换静态部分，变量部分原样保留。
 *
 * - 默认简体；偏好保存在 localStorage，URL 参数 `?lang=zh-Hant|zh-Hans` 优先（供 FileMaker WebViewer 指定）。
 * - 输入框 / 文本域里的内容不转换；加了 `translate="no"` 的元素及其子孙也不转换。
 * - 新增界面文案照常写简体字面量即可；数据不要写成字面量再显示。
 */

export type ChineseVariant = "zh-Hans" | "zh-Hant";

export const DEFAULT_CHINESE_VARIANT: ChineseVariant = "zh-Hans";

/**
 * 繁体字形：tw = 标准繁体字形（客戶、門戶、後臺……），只转字形，不改词汇。
 * 备选："hk" 香港字形（保留「户」等写法）、"twp" 连台湾用语一起换（软件→軟體）。
 */
const TRADITIONAL_LOCALE = "tw" as const;
const HTML_LANG: Record<ChineseVariant, string> = { "zh-Hans": "zh-CN", "zh-Hant": "zh-Hant" };

const STORAGE_KEY = "starrc-chinese-variant";
const URL_PARAM = "lang";
const CONVERTED_ATTRIBUTES = ["placeholder", "title", "aria-label", "alt"] as const;
// 这些元素里的文本节点不转换（输入框的 placeholder 属性仍会转换）
const SKIPPED_TEXT_TAGS = new Set(["SCRIPT", "STYLE", "TEXTAREA", "NOSCRIPT"]);
const HAN_PATTERN = /[㐀-鿿]/;
const CACHE_LIMIT = 20000;

function normalize(value: string | null | undefined): ChineseVariant | null {
  if (!value) return null;
  const lower = value.toLowerCase();
  if (lower === "zh-hant" || lower === "zh-tw" || lower === "zh-hk" || lower === "traditional") return "zh-Hant";
  if (lower === "zh-hans" || lower === "zh-cn" || lower === "simplified") return "zh-Hans";
  return null;
}

function readInitialVariant(): ChineseVariant {
  try {
    const fromUrl = normalize(new URLSearchParams(window.location.search).get(URL_PARAM));
    if (fromUrl) return fromUrl;
  } catch { /* 忽略：非浏览器环境或 URL 不可读 */ }
  try {
    const stored = normalize(window.localStorage.getItem(STORAGE_KEY));
    if (stored) return stored;
  } catch { /* 存储不可用时只在本次会话生效 */ }
  return DEFAULT_CHINESE_VARIANT;
}

// ───────────────────────── 状态 ─────────────────────────

let currentVariant: ChineseVariant = DEFAULT_CHINESE_VARIANT;
let started = false;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

export function getChineseVariant(): ChineseVariant {
  return currentVariant;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** React hook：读取当前简繁设置，并返回切换函数。 */
export function useChineseVariant(): [ChineseVariant, (variant: ChineseVariant) => void] {
  const variant = useSyncExternalStore(subscribe, getChineseVariant, () => DEFAULT_CHINESE_VARIANT);
  return [variant, setChineseVariant];
}

// ───────────────────────── 转换引擎 ─────────────────────────

type Convert = (text: string) => string;
type Conversion = { source: string; output: string };
type UiStrings = { exact: string[]; templates: string[][] };
type Engine = { convert: Convert; exact: Set<string>; templates: string[][] };

let engine: Engine | null = null;
let enginePromise: Promise<Engine> | null = null;
const cache = new Map<string, string>();
const textState = new WeakMap<Text, Conversion>();
const attrState = new WeakMap<Element, Map<string, Conversion>>();
let observer: MutationObserver | null = null;
let applyToken = 0;

function loadEngine(): Promise<Engine> {
  if (!enginePromise) {
    enginePromise = Promise.all([import("opencc-js/cn2t"), import("virtual:ui-strings")])
      .then(([OpenCC, ui]) => {
        const strings: UiStrings = ui.default;
        return {
          convert: OpenCC.Converter({ from: "cn", to: TRADITIONAL_LOCALE }),
          exact: new Set(strings.exact),
          templates: strings.templates
        };
      })
      .catch((error) => {
        enginePromise = null; // 加载失败允许下次重试
        throw error;
      });
  }
  return enginePromise;
}

/** 与 vite-plugins/uiStrings.ts 保持一致：去首尾空白，连续空白折成一个空格。 */
function normalizeKey(text: string): string {
  return text.trim().replace(/\s+/g, " ");
}

/** 文本是否形如模板 parts（静态片段 + 变量）；匹配则只转换静态片段，变量部分原样保留。 */
function convertByTemplate(active: Engine, text: string, parts: string[]): string | null {
  const first = parts[0];
  const last = parts[parts.length - 1];
  const end = text.length - last.length;
  if (!text.startsWith(first) || !text.endsWith(last) || end < first.length) return null;

  let output = active.convert(first);
  let position = first.length;
  for (let index = 1; index < parts.length - 1; index += 1) {
    const found = text.indexOf(parts[index], position);
    if (found < 0 || found + parts[index].length > end) return null;
    output += text.slice(position, found) + active.convert(parts[index]);
    position = found + parts[index].length;
  }
  return output + text.slice(position, end) + active.convert(last);
}

/** 只转换界面文案：整段文字命中清单，或符合某个模板；否则（数据、用户输入）原样返回。 */
function convert(text: string): string {
  const active = engine;
  if (!active || !HAN_PATTERN.test(text)) return text;
  const hit = cache.get(text);
  if (hit !== undefined) return hit;

  let output = text;
  const leading = text.length - text.trimStart().length;
  const trailing = text.length - text.trimEnd().length;
  const core = text.slice(leading, text.length - trailing);
  if (active.exact.has(normalizeKey(core))) {
    output = text.slice(0, leading) + active.convert(core) + text.slice(text.length - trailing);
  } else {
    for (const parts of active.templates) {
      const converted = convertByTemplate(active, text, parts);
      if (converted !== null) {
        output = converted;
        break;
      }
    }
  }

  if (cache.size >= CACHE_LIMIT) cache.clear();
  cache.set(text, output);
  return output;
}

function isTranslateOff(element: Element | null): boolean {
  for (let node = element; node; node = node.parentElement) {
    if (node.getAttribute("translate") === "no") return true;
  }
  return false;
}

function isSkippedText(element: Element | null): boolean {
  return (element !== null && SKIPPED_TEXT_TAGS.has(element.tagName)) || isTranslateOff(element);
}

function convertTextNode(node: Text) {
  const current = node.data;
  const state = textState.get(node);
  if (state && current === state.output) return; // 仍是我们写入的繁体，未被 React 改动
  if (isSkippedText(node.parentElement)) return;
  const output = convert(current);
  if (output === current) {
    textState.delete(node);
    return;
  }
  textState.set(node, { source: current, output });
  node.data = output;
}

function convertAttributes(element: Element, names: readonly string[] = CONVERTED_ATTRIBUTES) {
  if (isTranslateOff(element)) return;
  for (const name of names) {
    const current = element.getAttribute(name);
    if (current === null) continue;
    const states = attrState.get(element);
    const state = states?.get(name);
    if (state && current === state.output) continue;
    const output = convert(current);
    if (output === current) {
      states?.delete(name);
      continue;
    }
    const map = states ?? new Map<string, Conversion>();
    map.set(name, { source: current, output });
    attrState.set(element, map);
    element.setAttribute(name, output);
  }
}

function convertTree(root: Node) {
  if (root.nodeType === Node.TEXT_NODE) {
    convertTextNode(root as Text);
    return;
  }
  if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  if (root.nodeType === Node.ELEMENT_NODE) convertAttributes(root as Element);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeType === Node.TEXT_NODE) convertTextNode(node as Text);
    else convertAttributes(node as Element);
  }
}

function restoreTree(root: Node) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  for (let node: Node | null = walker.currentNode; node; node = walker.nextNode()) {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node as Text;
      const state = textState.get(text);
      if (state && text.data === state.output) text.data = state.source;
      textState.delete(text);
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      const element = node as Element;
      const states = attrState.get(element);
      if (states) {
        states.forEach((state, name) => {
          if (element.getAttribute(name) === state.output) element.setAttribute(name, state.source);
        });
        attrState.delete(element);
      }
    }
  }
}

function handleMutations(records: MutationRecord[]) {
  for (const record of records) {
    if (record.type === "characterData") {
      if (record.target.nodeType === Node.TEXT_NODE) convertTextNode(record.target as Text);
    } else if (record.type === "attributes") {
      if (record.attributeName) convertAttributes(record.target as Element, [record.attributeName]);
    } else {
      record.addedNodes.forEach((added) => convertTree(added));
    }
  }
  observer?.takeRecords(); // 丢弃我们自己写入产生的变更记录，避免空转
}

function startObserving() {
  if (observer) return;
  observer = new MutationObserver(handleMutations);
  observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: [...CONVERTED_ATTRIBUTES]
  });
}

function stopObserving() {
  observer?.disconnect();
  observer = null;
}

async function applyVariant(variant: ChineseVariant) {
  const token = ++applyToken;
  document.documentElement.lang = HTML_LANG[variant];
  if (variant === "zh-Hans") {
    stopObserving();
    engine = null;
    cache.clear();
    restoreTree(document.documentElement);
    return;
  }
  try {
    const loaded = await loadEngine();
    if (token !== applyToken) return; // 期间又切换了，以最新一次为准
    engine = loaded;
    startObserving();
    convertTree(document.documentElement);
    observer?.takeRecords();
  } catch (error) {
    if (token !== applyToken) return;
    console.error("繁体转换字典加载失败，暂时保持简体显示。", error);
  }
}

// ───────────────────────── 对外接口 ─────────────────────────

/** 应用启动时调用一次（main.tsx）。选了繁体时会等字典加载完再返回，避免先闪一下简体。 */
export async function initChineseVariant(): Promise<void> {
  if (started) return;
  started = true;
  currentVariant = readInitialVariant();
  await applyVariant(currentVariant);
}

export function setChineseVariant(variant: ChineseVariant): void {
  if (variant === currentVariant) return;
  currentVariant = variant;
  try { window.localStorage.setItem(STORAGE_KEY, variant); } catch { /* 存储不可用时只在本次会话生效 */ }
  emit();
  void applyVariant(variant);
}
