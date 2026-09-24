import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import ts from "typescript";
import type { Plugin } from "vite";

/**
 * 生成虚拟模块 `virtual:ui-strings`：扫描 src 下所有 .ts/.tsx，收集源码里写死的中文文案，
 * 供「简繁切换」使用——只有源码里写死的界面文字才会被转成繁体；
 * 从后端 / FileMaker 读出来的数据（客户名、零件名、订单内容等）不在名单里，永远保持原样。
 *
 * 收集三类：
 * 1. exact：字符串字面量、JSX 文本（整个文本节点等于它才转换）
 * 2. templates：模板字符串 / 字符串拼接里的静态片段，形如 ["共 ", " 条"]（只转换静态片段，中间的变量原样保留）
 */

const VIRTUAL_ID = "virtual:ui-strings";
const RESOLVED_ID = "\0" + VIRTUAL_ID;
const HAN = /[㐀-鿿]/;

export type UiStrings = { exact: string[]; templates: string[][] };

/** 与运行时保持一致：去首尾空白，连续空白折成一个空格（JSX 多行文本会被这样折叠）。 */
function norm(text: string): string {
  return text.trim().replace(/\s+/g, " ");
}

// 原型页的演示数据（产品名、零件名等）不是界面文案，不参与收集。
const EXCLUDED_FILES = new Set(["part-prototype-data.ts"]);

function walk(dir: string, out: string[]) {
  for (const name of readdirSync(dir)) {
    if (name.startsWith(".")) continue; // .pm-backup-* 等备份目录不参与
    const full = join(dir, name);
    const info = statSync(full);
    if (info.isDirectory()) walk(full, out);
    else if (/\.(ts|tsx)$/.test(name) && !name.endsWith(".d.ts") && !EXCLUDED_FILES.has(name)) out.push(full);
  }
}

function isPlusChain(node: ts.Node): node is ts.BinaryExpression {
  return ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken;
}

function flattenPlus(node: ts.Expression, out: ts.Expression[]) {
  let current: ts.Expression = node;
  while (ts.isParenthesizedExpression(current)) current = current.expression;
  if (isPlusChain(current)) {
    flattenPlus(current.left, out);
    flattenPlus(current.right, out);
  } else {
    out.push(current);
  }
}

export function collectUiStrings(srcDir: string): UiStrings {
  const files: string[] = [];
  walk(srcDir, files);
  const exact = new Set<string>();
  const templates = new Map<string, string[]>();

  const addExact = (text: string) => {
    if (!HAN.test(text)) return;
    const value = norm(text);
    if (value) exact.add(value);
  };
  const addTemplate = (parts: string[]) => {
    const normalized = parts.map((part) => part.replace(/\s+/g, " "));
    const hanCount = normalized.join("").split("").filter((ch) => HAN.test(ch)).length;
    if (hanCount < 2) return; // 静态片段太短（如单个「的」）容易误伤数据
    templates.set(JSON.stringify(normalized), normalized);
  };

  for (const file of files) {
    const source = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const visit = (node: ts.Node) => {
      if (ts.isJsxText(node)) {
        addExact(node.text);
      } else if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
        addExact(node.text);
      } else if (ts.isTemplateExpression(node)) {
        addTemplate([node.head.text, ...node.templateSpans.map((span) => span.literal.text)]);
      } else if (isPlusChain(node) && !(node.parent && isPlusChain(node.parent))) {
        const operands: ts.Expression[] = [];
        flattenPlus(node, operands);
        const parts: string[] = [""];
        let dynamic = false;
        for (const operand of operands) {
          if (ts.isStringLiteral(operand) || ts.isNoSubstitutionTemplateLiteral(operand)) {
            parts[parts.length - 1] += operand.text;
          } else {
            dynamic = true;
            parts.push("");
          }
        }
        if (dynamic && parts.some((part) => HAN.test(part))) addTemplate(parts);
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }

  return { exact: [...exact].sort(), templates: [...templates.values()].sort((a, b) => a[0].localeCompare(b[0])) };
}

export function uiStringsPlugin(): Plugin {
  let srcDir = resolve(process.cwd(), "src");
  return {
    name: "starrc-ui-strings",
    configResolved(config) {
      srcDir = resolve(config.root, "src");
    },
    resolveId(id) {
      return id === VIRTUAL_ID ? RESOLVED_ID : null;
    },
    load(id) {
      if (id !== RESOLVED_ID) return null;
      return `export default ${JSON.stringify(collectUiStrings(srcDir))};`;
    },
    handleHotUpdate({ file, server }) {
      if (!/\.(ts|tsx)$/.test(file) || !file.startsWith(srcDir)) return;
      const mod = server.moduleGraph.getModuleById(RESOLVED_ID);
      if (mod) server.moduleGraph.invalidateModule(mod);
    }
  };
}
