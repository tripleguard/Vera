export interface SessionRecord {
  id: string;
  title: string;
  preview: string;
  created_at: number;
  updated_at: number;
  archived: boolean;
  pinned: boolean;
  source: string;
  active_task_id?: string | null;
  last_error?: string | null;
}

export interface StoredMessage {
  id: number;
  session_id: string;
  role: string;
  content: string;
  created_at: number;
  kind: string;
  metadata?: Record<string, unknown>;
}

type AuthFetch = (url: RequestInfo, options?: RequestInit) => Promise<Response>;

async function expectJson<T>(request: Promise<Response>): Promise<T> {
  const response = await request;
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data?.error || `HTTP ${response.status}`);
  }
  return data as T;
}

export async function listSessions(fetcher: AuthFetch, archived = false, query = ''): Promise<SessionRecord[]> {
  const params = new URLSearchParams({
    archived: String(archived),
    limit: '200',
  });
  if (query.trim()) params.set('q', query.trim());
  const data = await expectJson<{ sessions: SessionRecord[] }>(
    fetcher(`http://127.0.0.1:8000/api/sessions?${params.toString()}`),
  );
  return data.sessions || [];
}

export async function getSession(fetcher: AuthFetch, sessionId: string): Promise<SessionRecord | null> {
  try {
    const data = await expectJson<{ session: SessionRecord }>(
      fetcher(`http://127.0.0.1:8000/api/sessions/${encodeURIComponent(sessionId)}`),
    );
    return data.session || null;
  } catch {
    return null;
  }
}

export async function createSession(fetcher: AuthFetch): Promise<SessionRecord> {
  const data = await expectJson<{ session: SessionRecord }>(
    fetcher('http://127.0.0.1:8000/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: 'chat' }),
    }),
  );
  return data.session;
}

export async function loadSessionMessages(fetcher: AuthFetch, sessionId: string): Promise<StoredMessage[]> {
  const data = await expectJson<{ messages: StoredMessage[] }>(
    fetcher(`http://127.0.0.1:8000/api/sessions/${encodeURIComponent(sessionId)}/messages`),
  );
  return data.messages || [];
}

export async function updateSession(
  fetcher: AuthFetch,
  sessionId: string,
  patch: Partial<Pick<SessionRecord, 'title' | 'archived' | 'pinned'>>,
): Promise<SessionRecord> {
  const data = await expectJson<{ session: SessionRecord }>(
    fetcher(`http://127.0.0.1:8000/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  );
  return data.session;
}

export async function deleteSession(fetcher: AuthFetch, sessionId: string): Promise<void> {
  await expectJson(
    fetcher(`http://127.0.0.1:8000/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    }),
  );
}
