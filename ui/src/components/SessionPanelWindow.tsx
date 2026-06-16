import { useEffect, useState } from 'react';
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

interface SessionPanelWindowProps {
  veraFetch: AuthFetch;
  onSkills: () => void;
  onProjects: () => void;
  onSessionOpen: () => void;
  activeSection: 'skills' | 'projects' | null;
}

export function SessionPanelWindow({
  veraFetch,
  onSkills,
  onProjects,
  onSessionOpen,
  activeSection,
}: SessionPanelWindowProps) {
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() => readActiveSessionId());

  useEffect(() => {
    let mounted = true;

    const refresh = async () => {
      try {
        const next = await listSessions(veraFetch);
        if (!mounted) return;
        setSessions(next);
        const selectedId = readActiveSessionId();
        if (!selectedId && next[0]) {
          setActiveSessionId(next[0].id);
          writeActiveSessionId(next[0].id);
        }
      } catch (error) {
        console.error('Failed to refresh sessions panel', error);
      }
    };

    refresh();
    const intervalId = window.setInterval(refresh, 10000);

    const onStorage = (event: StorageEvent) => {
      if (event.key === 'vera_active_session_id') {
        setActiveSessionId(readActiveSessionId());
      }
      if (event.key === 'vera_sessions_revision') {
        refresh();
      }
    };
    const onActiveSession = () => setActiveSessionId(readActiveSessionId());

    window.addEventListener('storage', onStorage);
    window.addEventListener(ACTIVE_SESSION_EVENT, onActiveSession);
    window.addEventListener(SESSIONS_REV_EVENT, refresh);
    return () => {
      mounted = false;
      window.clearInterval(intervalId);
      window.removeEventListener('storage', onStorage);
      window.removeEventListener(ACTIVE_SESSION_EVENT, onActiveSession);
      window.removeEventListener(SESSIONS_REV_EVENT, refresh);
    };
  }, [veraFetch]);

  const syncSessions = async () => {
    const next = await listSessions(veraFetch);
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
    const created = await createSession(veraFetch);
    setActiveSessionId(created.id);
    writeActiveSessionId(created.id);
    await syncSessions();
  };

  const handlePatch = async (
    session: SessionRecord,
    patch: Partial<Pick<SessionRecord, 'title' | 'archived' | 'pinned'>>,
  ) => {
    await updateSession(veraFetch, session.id, patch);
    await syncSessions();
  };

  const handleArchive = async (session: SessionRecord) => {
    await handlePatch(session, { archived: true });
    if (activeSessionId === session.id) {
      const remaining = (await listSessions(veraFetch))[0];
      const nextId = remaining?.id || null;
      setActiveSessionId(nextId);
      writeActiveSessionId(nextId);
      bumpSessionsRevision();
    }
  };

  const handleDelete = async (session: SessionRecord) => {
    if (!window.confirm(`Удалить сессию «${session.title}»?`)) return;
    await deleteSession(veraFetch, session.id);
    let next = await syncSessions();
    if (activeSessionId === session.id) {
      if (!next[0]) {
        await createSession(veraFetch);
        next = await syncSessions();
      }
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
        workingSessionIds={new Set()}
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
        onSkills={onSkills}
        onProjects={onProjects}
        activeSection={activeSection}
      />
    </div>
  );
}
