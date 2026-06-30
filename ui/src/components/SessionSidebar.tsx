import { useMemo, useState } from 'react';
import { Archive, Bot, Boxes, FileStack, MoreHorizontal, Pin, Search, StickyNote, Trash2 } from 'lucide-react';
import type { SessionRecord } from '../services/sessionService';

interface SessionSidebarProps {
  sessions: SessionRecord[];
  activeSessionId: string | null;
  workingSessionIds: Set<string>;
  onSelect: (sessionId: string) => void;
  onNew: () => void;
  onRename: (session: SessionRecord) => void;
  onPin: (session: SessionRecord) => void;
  onArchive: (session: SessionRecord) => void;
  onDelete: (session: SessionRecord) => void;
  archiveMode: boolean;
  onArchiveModeChange: (archiveMode: boolean) => void;
  onSkills: () => void;
  onProjects: () => void;
  onNotes: () => void;
  activeSection: 'skills' | 'projects' | 'notes' | null;
}

function formatAge(timestamp: number): string {
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - timestamp));
  if (seconds < 60) return 'сейчас';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}м`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}ч`;
  return `${Math.floor(seconds / 86400)}д`;
}

export function SessionSidebar({
  sessions,
  activeSessionId,
  workingSessionIds,
  onSelect,
  onNew,
  onRename,
  onPin,
  onArchive,
  onDelete,
  archiveMode,
  onArchiveModeChange,
  onSkills,
  onProjects,
  onNotes,
  activeSection,
}: SessionSidebarProps) {
  const [query, setQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [menuId, setMenuId] = useState<string | null>(null);
  const visibleSessions = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return sessions;
    return sessions.filter(session =>
      session.title.toLowerCase().includes(normalized)
      || session.preview.toLowerCase().includes(normalized)
    );
  }, [query, sessions]);
  const pinnedSessions = useMemo(
    () => visibleSessions.filter(session => session.pinned),
    [visibleSessions],
  );
  const regularSessions = useMemo(
    () => visibleSessions.filter(session => !session.pinned),
    [visibleSessions],
  );

  const renderRows = (items: SessionRecord[]) => items.map(session => {
    const active = session.id === activeSessionId;
    const working = workingSessionIds.has(session.id) || Boolean(session.active_task_id);
    return (
      <div
        key={session.id}
        className={`session-row ${active ? 'active' : ''}`}
      >
        <button className="session-row-main" onClick={() => onSelect(session.id)}>
          <span className={`session-status-dot ${working ? 'working' : session.last_error ? 'error' : ''}`} />
          <span className="session-row-copy">
            <span className="session-row-title">
              {session.pinned && <Pin size={11} />}
              {session.title}
            </span>
            <span className="session-row-preview">{session.preview || 'Пустая сессия'}</span>
          </span>
          <span className="session-row-age">{formatAge(session.updated_at)}</span>
        </button>
        <button
          className="session-row-menu"
          onClick={() => setMenuId(current => current === session.id ? null : session.id)}
          title="Действия с сессией"
        >
          <MoreHorizontal size={15} />
        </button>
        {menuId === session.id && (
          <div className="session-context-menu">
            <button onClick={() => { setMenuId(null); onRename(session); }}>Переименовать</button>
            <button onClick={() => { setMenuId(null); onPin(session); }}>
              <Pin size={13} /> {session.pinned ? 'Открепить' : 'Закрепить'}
            </button>
            <button onClick={() => { setMenuId(null); onArchive(session); }}>
              <Archive size={13} /> {archiveMode ? 'Вернуть' : 'В архив'}
            </button>
            <button className="danger" onClick={() => { setMenuId(null); onDelete(session); }}>
              <Trash2 size={13} /> Удалить
            </button>
          </div>
        )}
      </div>
    );
  });

  return (
    <aside className="session-sidebar no-drag-region">
      <div className="session-sidebar-top">
        <button className="session-icon-button" onClick={() => setSearchOpen(value => !value)} title="Поиск сессий">
          <Search size={16} />
        </button>
      </div>

      <button className="session-nav-item session-new-button" onClick={onNew}>
        <Bot size={17} />
        Новая сессия
      </button>
      <button
        className={`session-nav-item ${archiveMode ? 'active' : ''}`}
        type="button"
        onClick={() => onArchiveModeChange(!archiveMode)}
      >
        <Archive size={17} /> {archiveMode ? 'Активные' : 'Архив'}
      </button>

      <button
        className={`session-nav-item ${activeSection === 'skills' ? 'active' : ''}`}
        type="button"
        onClick={onSkills}
      >
        <Boxes size={17} /> Skills
      </button>
      <button
        className={`session-nav-item ${activeSection === 'projects' ? 'active' : ''}`}
        type="button"
        onClick={onProjects}
      >
        <FileStack size={17} /> Проекты
      </button>
      <button
        className={`session-nav-item ${activeSection === 'notes' ? 'active' : ''}`}
        type="button"
        onClick={onNotes}
      >
        <StickyNote size={17} /> Заметки
      </button>

      <div className="session-list">
        {!archiveMode && (
          <>
            <div className="session-section-label">Закрепленные</div>
            {pinnedSessions.length > 0
              ? renderRows(pinnedSessions)
              : <div className="session-pin-hint"><Pin size={12} /> Закрепляйте важные сессии</div>}
          </>
        )}
        <div className="session-section-label">
          {archiveMode ? 'Архив' : 'Сессии'} <span>{archiveMode ? visibleSessions.length : regularSessions.length}</span>
        </div>
        {searchOpen && (
          <label className="session-search">
            <Search size={13} />
            <input autoFocus value={query} onChange={event => setQuery(event.target.value)} placeholder="Поиск сессий" />
          </label>
        )}
        {renderRows(archiveMode ? visibleSessions : regularSessions)}
        {visibleSessions.length === 0 && (
          <div className="session-empty">Сессии не найдены</div>
        )}
      </div>
    </aside>
  );
}
