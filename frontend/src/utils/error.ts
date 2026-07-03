export function parseError(error: unknown): string {
  if (error instanceof Error) {
    return parseErrorText(error.message);
  }
  return parseErrorText(String(error));
}

function localize(raw: string): string {
  const text = raw.trim();
  if (text === "" || text === "Failed to fetch") {
    return "无法连接到后端服务，请检查网络或 API 是否正常运行。";
  }
  if (text.toLowerCase().includes("not found")) {
    return "请求的接口不存在，请检查后端服务是否已启动。";
  }
  return text;
}

function parseErrorText(text: string): string {
  const trimmed = text.trim();

  // FastAPI default error shape: {"detail":"..."}
  if (trimmed.startsWith("{\"detail\"") || trimmed.startsWith("{\"detail\"")) {
    try {
      const parsed = JSON.parse(trimmed) as { detail?: string | { msg?: string; type?: string }[] };
      if (parsed.detail) {
        if (Array.isArray(parsed.detail)) {
          return localize(parsed.detail.map((item) => item.msg).filter(Boolean).join("；")) || "请求参数校验失败。";
        }
        return localize(String(parsed.detail));
      }
    } catch {
      // fall through
    }
  }

  return localize(trimmed);
}
