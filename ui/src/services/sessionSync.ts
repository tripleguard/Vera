export const ACTIVE_SESSION_STORAGE_KEY = 'vera_active_session_id';
export const SESSIONS_REV_STORAGE_KEY = 'vera_sessions_revision';
export const ACTIVE_SESSION_EVENT = 'vera-active-session-change';
export const SESSIONS_REV_EVENT = 'vera-sessions-revision';

export function readActiveSessionId(): string | null {
  const value = localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
  return value && value.trim() ? value : null;
}

export function writeActiveSessionId(sessionId: string | null): void {
  if (sessionId && sessionId.trim()) {
    localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionId);
  } else {
    localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
  }
  window.dispatchEvent(new CustomEvent(ACTIVE_SESSION_EVENT, { detail: sessionId }));
}

export function bumpSessionsRevision(): void {
  localStorage.setItem(SESSIONS_REV_STORAGE_KEY, String(Date.now()));
  window.dispatchEvent(new Event(SESSIONS_REV_EVENT));
}
