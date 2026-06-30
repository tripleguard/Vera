import { useCallback, useEffect, useRef, useState } from 'react';
import { SessionSidebar } from './SessionSidebar';
import {
  createSession,
  deleteSession,
  listSessions,
  updateSession,
  type SessionRecord,
} from '../services/sessionService';
import {
  ACTIVE_SESSION_EVENT,
  SESSIONS_REV_EVENT,
  bumpSessionsRevision,
  readActiveSessionId,
  writeActiveSessionId,
} from '../services/sessionSync';

type AuthFetch = (url: RequestInfo, options?: RequestInit) => Promise<Response>;

const EMPTY_WORKING_SESSION_IDS = new Set<string>();

interface SessionPanelWindowProps {
  veraFetch: AuthFetch;
  onSkills: () => void;
  onProjects: () => void;
  onNotes: () => void;
  onSessionOpen: () => void;
  activeSection: 'skills' | 'projects' | 'notes' | null;
}

export function SessionPanelWindow({
  veraFetch,
  onSkills,
  onProjects,
  onNotes,
  onSessionOpen,
  activeSection,
}: SessionPanelWindowProps) {
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() => readActiveSessionId());
  const [archiveMode, setArchiveMode] = useState(false);
  const mountedRef = useRef(true);
  const refreshTimerRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await listSessions(veraFetch, archiveMode);
      if (!mountedRef.current) return;
      setSessions(next);
    } catch (error) {
      console.error('Failed to refresh sessions panel', error);
    }
  }, [archiveMode, veraFetch]);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimerRef.current != null) return;
    refreshTimerRef.current = window.setTimeout(() => {
      refreshTimerRef.current = null;
      void refresh();
    }, 120);
  }, [refresh]);

  useEffect(() => {
    mountedRef.current = true;

    void refresh();
    const intervalId = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') {
        void refresh();
      }
    }, 10000);

    const onStorage = (event: StorageEvent) => {
      if (event.key === 'vera_active_session_id') {
        setActiveSessionId(readActiveSessionId());
      }
      if (event.key === 'vera_sessions_revision') {
        scheduleRefresh();
      }
    };
    const onActiveSession = () => setActiveSessionId(readActiveSessionId());

    window.addEventListener('storage', onStorage);
    window.addEventListener(ACTIVE_SESSION_EVENT, onActiveSession);
    window.addEventListener(SESSIONS_REV_EVENT, scheduleRefresh);
    return () => {
      mountedRef.current = false;
      window.clearInterval(intervalId);
      if (refreshTimerRef.current != null) {
        window.clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
      window.removeEventListener('storage', onStorage);
      window.removeEventListener(ACTIVE_SESSION_EVENT, onActiveSession);
      window.removeEventListener(SESSIONS_REV_EVENT, scheduleRefresh);
    };
  }, [refresh, scheduleRefresh]);

  const syncSessions = async () => {
    const next = await listSessions(veraFetch, archiveMode);
    setSessions(next);
    bumpSessionsRevision();
    return next;
  };

  const handleSelect = async (sessionId: string) => {
    onSessionOpen();
    setActiveSessionId(sessionId);
    writeActiveSessionId(sessionId);
    bumpSessionsRevision();
  };

  const handleNew = async () => {
    onSessionOpen();
    setArchiveMode(false);
    const created = await createSession(veraFetch);
    setActiveSessionId(created.id);
    writeActiveSessionId(created.id);
    setSessions(await listSessions(veraFetch, false));
    bumpSessionsRevision();
  };

  const handlePatch = async (
    session: SessionRecord,
    patch: Partial<Pick<SessionRecord, 'title' | 'archived' | 'pinned'>>,
  ) => {
    await updateSession(veraFetch, session.id, patch);
    await syncSessions();
  };

  const handleArchive = async (session: SessionRecord) => {
    await handlePatch(session, { archived: !archiveMode });
    if (!archiveMode && activeSessionId === session.id) {
      const remaining = (await listSessions(veraFetch, false))[0];
      const nextId = remaining?.id || null;
      setActiveSessionId(nextId);
      writeActiveSessionId(nextId);
      bumpSessionsRevision();
    }
  };

  const handleDelete = async (session: SessionRecord) => {
    if (!window.confirm(`Удалить сессию «${session.title}»?`)) return;
    await deleteSession(veraFetch, session.id);
    const next = await syncSessions();
    if (activeSessionId === session.id) {
      const nextId = next[0]?.id || null;
      setActiveSessionId(nextId);
      writeActiveSessionId(nextId);
      bumpSessionsRevision();
    }
  };

  return (
    <div className="session-window-shell">
      <SessionSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        workingSessionIds={EMPTY_WORKING_SESSION_IDS}
        onSelect={sessionId => { void handleSelect(sessionId); }}
        onNew={() => { void handleNew(); }}
        onRename={session => {
          const next = window.prompt('Название сессии', session.title)?.trim();
          if (next && next !== session.title) {
            void handlePatch(session, { title: next });
          }
        }}
        onPin={session => { void handlePatch(session, { pinned: !session.pinned }); }}
        onArchive={session => { void handleArchive(session); }}
        onDelete={session => { void handleDelete(session); }}
        archiveMode={archiveMode}
        onArchiveModeChange={setArchiveMode}
        onSkills={onSkills}
        onProjects={onProjects}
        onNotes={onNotes}
        activeSection={activeSection}
      />
    </div>
  );
}
