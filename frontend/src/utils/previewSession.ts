import type { SessionResponse } from "../types";

const PREVIEW_SESSION_WINDOW_PREFIX = "starrc-preview-session:";

function isSessionResponse(value: unknown): value is SessionResponse {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<SessionResponse>;
  return Boolean(
    typeof candidate.token === "string"
      && candidate.token
      && candidate.context
      && typeof candidate.context === "object"
      && candidate.context.operator
      && typeof candidate.context.operator.account === "string"
  );
}

export function openPreviewWindow(route: string, session: SessionResponse): boolean {
  const previewWindow = window.open("about:blank", "_blank");
  if (!previewWindow) return false;

  previewWindow.name = `${PREVIEW_SESSION_WINDOW_PREFIX}${encodeURIComponent(JSON.stringify(session))}`;
  previewWindow.location.replace(new URL(route, window.location.origin).toString());
  return true;
}

export function takePreviewSession(): SessionResponse | null {
  if (!window.name.startsWith(PREVIEW_SESSION_WINDOW_PREFIX)) return null;

  const encodedSession = window.name.slice(PREVIEW_SESSION_WINDOW_PREFIX.length);
  window.name = "";
  try {
    window.opener = null;
  } catch {
    // Some browser policies expose opener as read-only. The one-time payload has
    // already been removed, so the preview can continue without retaining it.
  }

  try {
    const parsed = JSON.parse(decodeURIComponent(encodedSession)) as unknown;
    return isSessionResponse(parsed) ? parsed : null;
  } catch {
    return null;
  }
}
