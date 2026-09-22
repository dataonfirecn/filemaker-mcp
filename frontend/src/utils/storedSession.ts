import type { SessionResponse } from "../types";
import { isSessionResponse } from "./previewSession";

/**
 * Keeps a signed-in session across page reloads.
 *
 * Without this the token lives only in React state, so every refresh drops the
 * user back on the login form even though the server would still have honoured
 * the token for hours. The stored copy never outlives the token itself: the
 * server stamps an expiry into the payload, and everything here is bounded by
 * that same timestamp.
 */
const STORAGE_KEY = "starrc-session:v1";

/** Treat a token as gone slightly early, so a request can't race the expiry. */
const EXPIRY_SKEW_SECONDS = 60;

/**
 * Only password logins are persisted. A FileMaker WebViewer session comes from
 * a signed ctx/sig pair in the URL and is re-minted on load, and a preview
 * session is a deliberately one-shot handoff -- neither should be written to
 * disk behind the user's back.
 */
const PERSISTED_AUTHENTICATION_METHOD = "webPassword";

type SessionTokenPayload = {
  exp?: number;
  authenticationMethod?: string;
};

/** Read the unsigned half of the session token. */
function decodeTokenPayload(token: string): SessionTokenPayload | null {
  const encoded = token.split(".")[0];
  if (!encoded) return null;
  try {
    const base64 = encoded.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const binary = atob(padded);
    // The payload is UTF-8 JSON and may carry Chinese operator names, so it has
    // to go through TextDecoder rather than being read as a binary string.
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    const parsed = JSON.parse(new TextDecoder().decode(bytes)) as unknown;
    return parsed && typeof parsed === "object" ? (parsed as SessionTokenPayload) : null;
  } catch {
    // The signature is what actually protects this token; an unreadable
    // payload just means we cannot pre-empt the expiry locally.
    return null;
  }
}

/** Epoch seconds at which the server will stop accepting this token, or 0. */
export function sessionExpiresAt(token: string): number {
  const expiry = Number(decodeTokenPayload(token)?.exp ?? 0);
  return Number.isFinite(expiry) ? expiry : 0;
}

/**
 * Milliseconds until the token expires, or null when the payload carries no
 * readable expiry. Null means "ask the server" -- never "expired", so an
 * unreadable payload can't silently sign a working session out.
 */
export function millisecondsUntilExpiry(token: string, now = Date.now()): number | null {
  const expiresAt = sessionExpiresAt(token);
  if (!expiresAt) return null;
  return Math.max(0, (expiresAt - EXPIRY_SKEW_SECONDS) * 1000 - now);
}

export function canPersistSession(session: SessionResponse): boolean {
  return decodeTokenPayload(session.token)?.authenticationMethod === PERSISTED_AUTHENTICATION_METHOD;
}

export function storeSession(session: SessionResponse): void {
  if (!canPersistSession(session)) {
    clearStoredSession();
    return;
  }
  // Nothing is gained by writing a credential that is already spent.
  if (millisecondsUntilExpiry(session.token) === 0) {
    clearStoredSession();
    return;
  }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    // Ignore storage errors; the session simply will not survive a reload.
  }
}

export function clearStoredSession(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore storage errors.
  }
}

/**
 * Returns a stored session that has not expired. The caller still has to
 * confirm it against the server -- a token can be revoked, or the account
 * disabled, long before its expiry.
 */
export function loadStoredSession(): SessionResponse | null {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    clearStoredSession();
    return null;
  }
  if (!isSessionResponse(parsed)) {
    clearStoredSession();
    return null;
  }
  if (millisecondsUntilExpiry(parsed.token) === 0) {
    clearStoredSession();
    return null;
  }
  return parsed;
}
