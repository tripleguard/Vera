import { useEffect, useState, useRef, useCallback, useMemo, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Paperclip, X, Send, ExternalLink, FolderOpen, FileText, Mic, MicOff, Brain, ChevronDown, ChevronUp, Check, Pin, Trash2, Search, Database, Plus, Save } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { connectSocketWithReconnect } from './services/socketService';

import { Settings } from 'lucide-react';

const ipcRenderer = window.require ? window.require('electron').ipcRenderer : null;
const shell = window.require ? window.require('electron').shell : null;

const apiToken = ipcRenderer ? ipcRenderer.sendSync('get-api-token-sync') : '';

type VeraThemeId = 'obsidian' | 'daylight' | 'odyssey' | 'terminal' | 'sakura' | 'graphite';

const VERA_THEMES: Array<{
    id: VeraThemeId;
    name: string;
    description: string;
    mode: 'dark' | 'light';
    swatches: string[];
}> = [
        { id: 'obsidian', name: 'Обсидиан', description: 'Темное стекло', mode: 'dark', swatches: ['#101114', '#1c2430', '#67d4ff'] },
        { id: 'daylight', name: 'Дневной', description: 'Чистый фокус', mode: 'light', swatches: ['#f7f8fb', '#ffffff', '#2563eb'] },
        { id: 'odyssey', name: 'Одиссея', description: 'Мягкий неон', mode: 'dark', swatches: ['#0e1020', '#19223b', '#ff5ca8'] },
        { id: 'terminal', name: 'Терминал', description: 'Минимум шума', mode: 'dark', swatches: ['#020403', '#07110c', '#44ff8a'] },
        { id: 'sakura', name: 'Сакура', description: 'Теплый свет', mode: 'light', swatches: ['#fff7fa', '#ffffff', '#d9467f'] },
        { id: 'graphite', name: 'Графит', description: 'Спокойная сталь', mode: 'dark', swatches: ['#17191d', '#22272e', '#f59f5a'] },
    ];

const THEME_STORAGE_KEY = 'vera_theme';

function getThemeById(themeId: string | null | undefined) {
    return VERA_THEMES.find(theme => theme.id === themeId) || VERA_THEMES[0];
}

async function veraFetch(url: RequestInfo, options: RequestInit = {}): Promise<Response> {
    if (apiToken) {
        options.headers = {
            ...options.headers,
            'Authorization': `Bearer ${apiToken}`,
            'X-Vera-Token': apiToken
        };
    }
    return fetch(url, options);
}

function parseMessage(text: string): { cleanText: string; sources: string[], docPath: string | null } {
    const sources: string[] = [];
    let cleanText = text || '';
    let docPath: string | null = null;

    const docPathRe = /(Презентация создана|Документ сохранен|Документ сохранён|Файл создан):\s*([A-Z]:\\[^\r\n]+)/i;
    const docMatch = docPathRe.exec(cleanText);
    if (docMatch) {
        docPath = docMatch[2].trim();
    }

    const sourceBlockRe = /\s*\((?:источники?|sources?):\s*([^)]+)\)/gi;
    let blockMatch: RegExpExecArray | null = null;
    while ((blockMatch = sourceBlockRe.exec(cleanText)) !== null) {
        const urls = (blockMatch[1] || '').match(/https?:\/\/[^\s,)]+/g);
        if (urls) {
            for (const url of urls) {
                if (!sources.includes(url)) sources.push(url);
            }
        }
    }
    cleanText = cleanText.replace(sourceBlockRe, '');

    const standAloneUrls = cleanText.match(/https?:\/\/[^\s,)]+/g);
    if (standAloneUrls) {
        for (const url of standAloneUrls) {
            if (!sources.includes(url)) sources.push(url);
        }
        // Do not show raw URLs in assistant text; show them only as source buttons.
        cleanText = cleanText.replace(/https?:\/\/[^\s,)]+/g, '');
    }

    cleanText = cleanText
        .replace(/[ \t]{2,}/g, ' ')
        .replace(/\n{3,}/g, '\n\n')
        .trim();

    return { cleanText, sources, docPath };
}

function getDomain(url: string): string {
    try {
        return new URL(url).hostname.replace('www.', '');
    } catch {
        return url.slice(0, 30);
    }
}

function getSourcePath(url: string): string {
    try {
        const parsed = new URL(url);
        const path = parsed.pathname.replace(/\/$/, '');
        return path && path !== '/' ? path.split('/').filter(Boolean).slice(0, 2).join(' / ') : 'главная';
    } catch {
        return 'источник';
    }
}

function formatFactDate(timestamp: number | undefined): string {
    if (!timestamp) return '';
    try {
        return new Date(timestamp * 1000).toLocaleDateString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: '2-digit',
        });
    } catch {
        return '';
    }
}

function getFileExtension(fileName: string | undefined): string {
    if (!fileName) return 'ФАЙЛ';
    const parts = fileName.split('.');
    if (parts.length < 2) return 'ФАЙЛ';
    return parts[parts.length - 1].toUpperCase();
}

function formatFileSize(bytes: number | undefined): string {
    if (!bytes || bytes <= 0) return '';
    if (bytes < 1024) return `${bytes} Б`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} КБ`;
    return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} МБ`;
}

function getVoiceDisplayName(voiceName: string | undefined): string {
    const names: Record<string, string> = {
        Lily: 'Вера',
        F1: 'Алиса',
        F2: 'Мира',
        F3: 'София',
        F4: 'Ника',
        F5: 'Ева',
        M1: 'Максим',
        M2: 'Илья',
        M3: 'Даниил',
        M4: 'Кирилл',
        M5: 'Роман',
    };
    return names[voiceName || ''] || voiceName || 'Вера';
}

const CATEGORY_LABELS: Record<string, string> = {
    identity: 'Личность',
    contact: 'Контакты',
    preference: 'Предпочтения',
    project: 'Проекты',
    fact: 'Факты',
};

function getCategoryLabel(category: string): string {
    return CATEGORY_LABELS[category] || category;
}

function getMemorySourceLabel(source: string | undefined): string {
    const labels: Record<string, string> = {
        user: 'пользователь',
        legacy: 'старый файл',
        unknown: 'неизвестно',
        test: 'тест',
    };
    return labels[source || 'unknown'] || source || 'неизвестно';
}

interface MemoryFact {
    id: string;
    text: string;
    category: string;
    pinned: boolean;
    timestamp?: number;
    source?: string;
}

interface MemoryPayload {
    profile: Record<string, string>;
    facts: MemoryFact[];
    categories: string[];
}

function ThinkingBlock({ thoughts, isLightMode }: { thoughts: string, isLightMode: boolean }) {
    const [isExpanded, setIsExpanded] = useState(false);

    if (!thoughts) return null;

    return (
        <div className={`mb-4 rounded-xl border transition-all ${isLightMode ? 'bg-gray-50 border-gray-200' : 'bg-white/5 border-white/10'
            }`}>
            <button
                onClick={(e) => {
                    e.stopPropagation();
                    setIsExpanded(!isExpanded);
                }}
                className="w-full flex items-center justify-between px-4 py-2 text-xs font-medium opacity-60 hover:opacity-100 transition-opacity"
            >
                <div className="flex items-center gap-2">
                    <Brain size={14} className="text-purple-400" />
                    <span>Размышления модели</span>
                </div>
                {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {isExpanded && (
                <div className="px-4 pb-3 text-xs leading-relaxed opacity-70 whitespace-pre-wrap border-t border-white/5 pt-2 italic">
                    {thoughts}
                </div>
            )}
        </div>
    );
}

function CodeBlock({ code, language, isLightMode }: { code: string, language: string, isLightMode: boolean }) {
    const [copied, setCopied] = useState(false);

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(code);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1200);
        } catch {
            setCopied(false);
        }
    };

    return (
        <div className={`rounded-xl border overflow-hidden ${isLightMode ? 'border-gray-200 bg-gray-50' : 'border-white/10 bg-black/30'}`}>
            <div className={`flex items-center justify-between px-3 py-2 text-[11px] ${isLightMode ? 'bg-gray-100 text-gray-500' : 'bg-black/30 text-white/50'}`}>
                <span className="uppercase tracking-wide">{language}</span>
                <button
                    onClick={handleCopy}
                    className={`px-2 py-1 rounded-md transition-colors ${isLightMode
                        ? 'hover:bg-gray-200 text-gray-600'
                        : 'hover:bg-white/10 text-white/70'
                        }`}
                    title="Скопировать код"
                >
                    {copied ? 'Скопировано' : 'Копировать'}
                </button>
            </div>
            <pre className={`m-0 p-3 overflow-x-auto text-[13px] leading-relaxed ${isLightMode ? 'text-gray-800' : 'text-gray-100'}`}>
                <code>{code}</code>
            </pre>
        </div>
    );
}

function AssistantMessageText({ text, isLightMode }: { text: string, isLightMode: boolean }) {
    return (
        <div className="space-y-2">
            <ReactMarkdown
                components={{
                    pre: ({ children }) => <>{children}</>,
                    p: ({ children }) => <p className="whitespace-pre-wrap leading-relaxed mb-2 last:mb-0">{children}</p>,
                    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                    em: ({ children }) => <em className="italic">{children}</em>,
                    ul: ({ children }) => <ul className="list-disc pl-5 space-y-1 my-2">{children}</ul>,
                    ol: ({ children }) => <ol className="list-decimal pl-5 space-y-1 my-2">{children}</ol>,
                    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                    blockquote: ({ children }) => (
                        <blockquote className={`border-l-2 pl-3 italic my-2 ${isLightMode ? 'border-gray-300 text-gray-700' : 'border-white/20 text-white/70'}`}>
                            {children}
                        </blockquote>
                    ),
                    a: ({ href, children }) => (
                        <a
                            href={href}
                            onClick={(e) => {
                                if (href && shell) {
                                    e.preventDefault();
                                    shell.openExternal(href);
                                }
                            }}
                            className={`underline underline-offset-2 ${isLightMode ? 'text-blue-700 hover:text-blue-800' : 'text-blue-300 hover:text-blue-200'}`}
                        >
                            {children}
                        </a>
                    ),
                    code: ({ inline, className, children }: any) => {
                        const raw = String(children ?? '').replace(/\n$/, '');
                        if (inline) {
                            return (
                                <code className={`px-1 py-0.5 rounded text-[13px] ${isLightMode ? 'bg-gray-100 text-gray-800' : 'bg-white/10 text-gray-100'}`}>
                                    {raw}
                                </code>
                            );
                        }
                        const langMatch = /language-([a-zA-Z0-9_+.-]+)/.exec(className || '');
                        return (
                            <CodeBlock
                                code={raw}
                                language={langMatch?.[1] || 'text'}
                                isLightMode={isLightMode}
                            />
                        );
                    },
                }}
            >
                {text}
            </ReactMarkdown>
        </div>
    );
}

function SettingsModal({
    isOpen,
    onClose,
    currentThemeId,
    onThemeChange,
}: {
    isOpen: boolean;
    onClose: () => void;
    currentThemeId: VeraThemeId;
    onThemeChange: (themeId: VeraThemeId) => void;
}) {
    const [config, setConfig] = useState<any>(null);
    const [tasks, setTasks] = useState<any[]>([]);
    const [memory, setMemory] = useState<MemoryPayload | null>(null);
    const [profileDrafts, setProfileDrafts] = useState<Record<string, string>>({});
    const [memorySearch, setMemorySearch] = useState('');
    const [memoryCategory, setMemoryCategory] = useState('all');
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState('');

    useEffect(() => {
        if (isOpen) {
            setMessage('');
            Promise.all([
                veraFetch('http://127.0.0.1:8000/api/config').then(res => res.json()),
                veraFetch('http://127.0.0.1:8000/api/heartbeat-tasks').then(res => res.json()),
                veraFetch('http://127.0.0.1:8000/api/memory').then(res => res.json())
            ])
                .then(([cfgData, tasksData, memoryData]) => {
                    setConfig(cfgData);
                    setTasks(Array.isArray(tasksData) ? tasksData : []);
                    setMemory({
                        profile: memoryData?.profile || {},
                        facts: Array.isArray(memoryData?.facts) ? memoryData.facts : [],
                        categories: Array.isArray(memoryData?.categories) ? memoryData.categories : [],
                    });
                    setProfileDrafts(memoryData?.profile || {});
                })
                .catch(err => setMessage('Ошибка загрузки настроек: ' + err.message));
        }
    }, [isOpen]);

    if (!isOpen) return null;

    const handleSave = async () => {
        setLoading(true);
        try {
            await Promise.all([
                veraFetch('http://127.0.0.1:8000/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config)
                }),
                veraFetch('http://127.0.0.1:8000/api/heartbeat-tasks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tasks: tasks })
                })
            ]);
            setMessage("После сохранения приложение автоматически перезапустится...");

            setLoading(false);
            window.setTimeout(() => {
                onClose();
                if (ipcRenderer) {
                    ipcRenderer.send('restart-app');
                } else {
                    window.location.reload();
                }
            }, 400);

        } catch (err: any) {
            setMessage('Ошибка сохранения: ' + err.message);
            setLoading(false);
        }
    };

    const handleChange = (section: string, field: string, value: any, type: string) => {
        let val = value;
        if (type === 'number' || type === 'float') {
            val = type === 'number' ? parseInt(value) || 0 : parseFloat(value) || 0;
        } else if (type === 'boolean') {
            val = value === 'true' || value === true;
        }

        setConfig((prev: any) => {
            const newConfig = { ...prev };
            if (section) {
                newConfig[section] = { ...newConfig[section], [field]: val };
            } else {
                newConfig[field] = val;
            }
            return newConfig;
        });
    };

    const handleSiteChange = (oldKey: string, newKey: string, newValue: string, isKeyChange: boolean) => {
        setConfig((prev: any) => {
            const newConfig = { ...prev };
            const sites = { ...(newConfig.sites || {}) };

            if (isKeyChange && oldKey !== newKey) {
                delete sites[oldKey];
            }
            sites[newKey] = newValue;

            newConfig.sites = sites;
            return newConfig;
        });
    };

    const handleAddSite = () => {
        setConfig((prev: any) => {
            const newConfig = { ...prev };
            const sites = { ...(newConfig.sites || {}) };

            let count = 1;
            let newKey = `new_site_${count}`;
            while (sites[newKey] !== undefined) {
                count++;
                newKey = `new_site_${count}`;
            }
            sites[newKey] = '';

            newConfig.sites = sites;
            return newConfig;
        });
    };

    const handleRemoveSite = (key: string) => {
        setConfig((prev: any) => {
            const newConfig = { ...prev };
            const sites = { ...newConfig.sites };
            delete sites[key];
            newConfig.sites = sites;
            return newConfig;
        });
    };

    const handleAddTask = () => {
        const now = new Date();
        const pad = (n: number) => n.toString().padStart(2, '0');
        const created_at = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}-${pad(now.getHours())}-${pad(now.getMinutes())}`;

        setTasks(prev => [...prev, {
            task_text: "Новая задача",
            time: "12:00",
            recurring: "daily",
            created_at: created_at,
            last_run: null,
            enabled: true,
            target_date: null,
            interval_minutes: 0
        }]);
    };

    const handleTaskChange = (index: number, field: string, value: any) => {
        setTasks(prev => {
            const newTasks = [...prev];
            newTasks[index] = { ...newTasks[index], [field]: value };
            return newTasks;
        });
    };

    const handleRemoveTask = (index: number) => {
        setTasks(prev => prev.filter((_, i) => i !== index));
    };

    const handleToggleFactPin = async (fact: MemoryFact) => {
        const nextPinned = !fact.pinned;
        setMemory(prev => prev ? {
            ...prev,
            facts: prev.facts.map(item => item.id === fact.id ? { ...item, pinned: nextPinned } : item),
        } : prev);
        try {
            await veraFetch(`http://127.0.0.1:8000/api/memory/facts/${encodeURIComponent(fact.id)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pinned: nextPinned }),
            });
        } catch (err: any) {
            setMessage('Ошибка памяти: ' + err.message);
            setMemory(prev => prev ? {
                ...prev,
                facts: prev.facts.map(item => item.id === fact.id ? { ...item, pinned: fact.pinned } : item),
            } : prev);
        }
    };

    const handleDeleteFact = async (fact: MemoryFact) => {
        const previous = memory;
        setMemory(prev => prev ? {
            ...prev,
            facts: prev.facts.filter(item => item.id !== fact.id),
        } : prev);
        try {
            await veraFetch(`http://127.0.0.1:8000/api/memory/facts/${encodeURIComponent(fact.id)}`, {
                method: 'DELETE',
            });
        } catch (err: any) {
            setMessage('Ошибка памяти: ' + err.message);
            setMemory(previous);
        }
    };

    const filteredMemoryFacts = (memory?.facts || []).filter(fact => {
        const query = memorySearch.trim().toLowerCase();
        const matchesSearch = !query || fact.text.toLowerCase().includes(query) || fact.category.toLowerCase().includes(query) || getCategoryLabel(fact.category).toLowerCase().includes(query);
        const matchesCategory = memoryCategory === 'all' || fact.category === memoryCategory;
        return matchesSearch && matchesCategory;
    });

    const handleProfileDraftChange = (key: string, value: string) => {
        setProfileDrafts(prev => ({ ...prev, [key]: value }));
    };

    const handleSaveProfileField = async (key: string) => {
        const value = (profileDrafts[key] || '').trim();
        if (!value) {
            setMessage('Поле профиля не может быть пустым.');
            return;
        }

        const previousProfile = memory?.profile || {};
        setMemory(prev => prev ? {
            ...prev,
            profile: { ...prev.profile, [key]: value },
        } : prev);

        try {
            await veraFetch(`http://127.0.0.1:8000/api/memory/profile/${encodeURIComponent(key)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value }),
            });
        } catch (err: any) {
            setMessage('Ошибка профиля: ' + err.message);
            setMemory(prev => prev ? { ...prev, profile: previousProfile } : prev);
            setProfileDrafts(previousProfile);
        }
    };

    const handleDeleteProfileField = async (key: string) => {
        const previousProfile = memory?.profile || {};
        setMemory(prev => {
            if (!prev) return prev;
            const nextProfile = { ...prev.profile };
            delete nextProfile[key];
            return { ...prev, profile: nextProfile };
        });
        setProfileDrafts(prev => {
            const next = { ...prev };
            delete next[key];
            return next;
        });

        try {
            await veraFetch(`http://127.0.0.1:8000/api/memory/profile/${encodeURIComponent(key)}`, {
                method: 'DELETE',
            });
        } catch (err: any) {
            setMessage('Ошибка профиля: ' + err.message);
            setMemory(prev => prev ? { ...prev, profile: previousProfile } : prev);
            setProfileDrafts(previousProfile);
        }
    };

    const profileEntries = Object.entries(memory?.profile || {});



    return (
        <div className="settings-overlay absolute inset-0 z-50 flex items-center justify-center bg-black/55 p-4 text-[var(--vera-text)]">
            <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                className="vera-settings w-full max-w-3xl max-h-[90vh] rounded-2xl border shadow-2xl flex flex-col overflow-hidden"
            >
                {/* Header */}
                <div className="settings-header flex items-center justify-between p-4 border-b no-drag-region">
                    <h2 className="text-lg font-medium flex items-center gap-2">
                        <Settings size={20} />
                        Настройки
                    </h2>
                    <button onClick={onClose} className="p-1.5 opacity-60 hover:opacity-100 hover:bg-white/10 rounded-lg transition-all">
                        <X size={20} />
                    </button>
                </div>

                {/* Body (Scrollable fields) */}
                <div className="flex-1 overflow-y-auto p-6 space-y-8 no-drag-region">
                    {!config ? (
                        <div className="flex h-32 items-center justify-center opacity-50">
                            Загрузка...
                        </div>
                    ) : (
                        <div className="space-y-6">
                            <div className="settings-intro">
                                <div className="settings-intro-card">
                                    <span className="settings-intro-label">Тема</span>
                                    <strong>{getThemeById(currentThemeId).name}</strong>
                                </div>
                                <div className="settings-intro-card">
                                    <span className="settings-intro-label">Контекст</span>
                                    <strong>{config.model?.ctx_size || 0}</strong>
                                </div>
                                <div className="settings-intro-card">
                                    <span className="settings-intro-label">Голос</span>
                                    <strong>{getVoiceDisplayName(config.tts?.voice_name)}</strong>
                                </div>
                            </div>
                            <section>
                                <h3 className="settings-section-title">Оформление</h3>
                                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                                    {VERA_THEMES.map(theme => (
                                        <button
                                            key={theme.id}
                                            type="button"
                                            onClick={() => onThemeChange(theme.id)}
                                            className={`theme-option ${currentThemeId === theme.id ? 'active' : ''}`}
                                        >
                                            <div className="flex items-center justify-between gap-2">
                                                <span className="font-medium">{theme.name}</span>
                                                {currentThemeId === theme.id && <Check size={14} />}
                                            </div>
                                            <div className="mt-2 flex gap-1.5">
                                                {theme.swatches.map(color => (
                                                    <span
                                                        key={color}
                                                        className="h-4 flex-1 rounded"
                                                        style={{ backgroundColor: color }}
                                                    />
                                                ))}
                                            </div>
                                            <div className="mt-2 text-[11px] opacity-60">{theme.description}</div>
                                        </button>
                                    ))}
                                </div>
                            </section>

                            <div className="settings-separator" />

                            <section>
                                <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                                    <h3 className="settings-section-title mb-0 flex items-center gap-2">
                                        <Database size={14} />
                                        Память
                                    </h3>
                                    <div className="flex items-center gap-2 text-[12px] opacity-70">
                                        <span>{memory?.facts?.length || 0} фактов</span>
                                        <span>{profileEntries.length} полей профиля</span>
                                    </div>
                                </div>
                                {profileEntries.length > 0 && (
                                    <div className="memory-profile-grid">
                                        {profileEntries.map(([key, value]) => (
                                            <div key={key} className="memory-profile-item">
                                                <span>{key}</span>
                                                <div className="memory-profile-edit-row">
                                                    <input
                                                        type="text"
                                                        value={profileDrafts[key] ?? value}
                                                        onChange={e => handleProfileDraftChange(key, e.target.value)}
                                                        className="memory-profile-input"
                                                    />
                                                    <button
                                                        type="button"
                                                        onClick={() => handleSaveProfileField(key)}
                                                        className="memory-icon-button"
                                                        title="Сохранить поле"
                                                    >
                                                        <Save size={14} />
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => handleDeleteProfileField(key)}
                                                        className="memory-icon-button danger"
                                                        title="Удалить поле"
                                                    >
                                                        <Trash2 size={14} />
                                                    </button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                                <div className="memory-toolbar">
                                    <div className="memory-search">
                                        <Search size={14} />
                                        <input
                                            type="text"
                                            value={memorySearch}
                                            onChange={e => setMemorySearch(e.target.value)}
                                            placeholder="Поиск по фактам"
                                            className="bg-transparent border-none px-2 py-1.5 text-sm focus:outline-none flex-1"
                                        />
                                    </div>
                                    <select
                                        value={memoryCategory}
                                        onChange={e => setMemoryCategory(e.target.value)}
                                        className="memory-category-select"
                                    >
                                        <option value="all">Все категории</option>
                                        {(memory?.categories || []).map(category => (
                                            <option key={category} value={category}>{getCategoryLabel(category)}</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="memory-facts-list">
                                    {!memory ? (
                                        <div className="memory-empty">Загрузка памяти...</div>
                                    ) : filteredMemoryFacts.length === 0 ? (
                                        <div className="memory-empty">Факты не найдены</div>
                                    ) : (
                                        filteredMemoryFacts.map(fact => (
                                            <div key={fact.id} className={`memory-fact ${fact.pinned ? 'pinned' : ''}`}>
                                                <div className="min-w-0 flex-1">
                                                    <div className="flex flex-wrap items-center gap-2 mb-1">
                                                        <span className="memory-category">{getCategoryLabel(fact.category)}</span>
                                                        {fact.pinned && <span className="memory-pinned">закреплено</span>}
                                                        {fact.source && <span className="memory-meta">источник: {getMemorySourceLabel(fact.source)}</span>}
                                                        {fact.timestamp && <span className="memory-meta">{formatFactDate(fact.timestamp)}</span>}
                                                    </div>
                                                    <div className="text-sm leading-relaxed">{fact.text}</div>
                                                </div>
                                                <div className="flex items-center gap-1">
                                                    <button
                                                        type="button"
                                                        onClick={() => handleToggleFactPin(fact)}
                                                        className="memory-icon-button"
                                                        title={fact.pinned ? 'Открепить' : 'Закрепить'}
                                                    >
                                                        <Pin size={14} />
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => handleDeleteFact(fact)}
                                                        className="memory-icon-button danger"
                                                        title="Удалить"
                                                    >
                                                        <Trash2 size={14} />
                                                    </button>
                                                </div>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </section>

                            <div className="settings-separator" />
                            {/* General */}
                            <section>
                                <h3 className="text-sm font-semibold opacity-50 uppercase tracking-widest mb-4">Общие</h3>
                                <div className="space-y-4">
                                    <div>
                                        <label className="block text-sm opacity-80 mb-1">Активационное слово</label>
                                        <input
                                            type="text"
                                            value={config.activation_word || ''}
                                            onChange={e => handleChange('', 'activation_word', e.target.value, 'string')}
                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm opacity-80 mb-1">Таймаут тишины (сек)</label>
                                        <input
                                            type="number"
                                            value={config.silence_timeout || 0}
                                            onChange={e => handleChange('', 'silence_timeout', e.target.value, 'number')}
                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                        />
                                    </div>
                                </div>
                            </section>

                            <div className="h-px bg-white/5 w-full" />

                            {/* LLM Model */}
                            <section>
                                <h3 className="text-sm font-semibold opacity-50 uppercase tracking-widest mb-4">Модель (LLM)</h3>
                                <div className="space-y-4">
                                    <div>
                                        <label className="block text-sm opacity-80 mb-1">Размер контекста</label>
                                        <input
                                            type="number"
                                            value={config.model?.ctx_size || 0}
                                            onChange={e => handleChange('model', 'ctx_size', e.target.value, 'number')}
                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                        />
                                    </div>
                                    <div className="grid grid-cols-2 gap-4">
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">Temperature</label>
                                            <input
                                                type="number" step="0.1"
                                                value={config.model?.temperature || 0}
                                                onChange={e => handleChange('model', 'temperature', e.target.value, 'float')}
                                                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                            />
                                        </div>
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">Top_p</label>
                                            <input
                                                type="number" step="0.05"
                                                value={config.model?.top_p || 0}
                                                onChange={e => handleChange('model', 'top_p', e.target.value, 'float')}
                                                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                            />
                                        </div>
                                    </div>
                                    <div className="space-y-3 pt-1 border-t border-white/5">
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">
                                                Лимит размышления (reasoning_budget)
                                            </label>
                                            <div className="flex items-center gap-2">
                                                <input
                                                    type="range"
                                                    min="0"
                                                    max="4096"
                                                    step="64"
                                                    value={Math.max(0, config.model?.reasoning_budget ?? 1024)}
                                                    onChange={e => handleChange('model', 'reasoning_budget', e.target.value, 'number')}
                                                    className="flex-1 accent-blue-500"
                                                />
                                                <input
                                                    type="number"
                                                    min="-1"
                                                    max="32768"
                                                    value={config.model?.reasoning_budget ?? 1024}
                                                    onChange={e => handleChange('model', 'reasoning_budget', e.target.value, 'number')}
                                                    className="w-24 bg-black/30 border border-white/10 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-white/30"
                                                />
                                            </div>
                                            <p className="text-[10px] opacity-40 mt-1">`-1` = без ограничений, `0` = без размышления</p>
                                        </div>

                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">
                                                Лимит отображения мыслей (max_thought_chars)
                                            </label>
                                            <div className="flex items-center gap-2">
                                                <input
                                                    type="range"
                                                    min="500"
                                                    max="10000"
                                                    step="100"
                                                    value={config.model?.max_thought_chars ?? 4000}
                                                    onChange={e => handleChange('model', 'max_thought_chars', e.target.value, 'number')}
                                                    className="flex-1 accent-blue-500"
                                                />
                                                <input
                                                    type="number"
                                                    min="100"
                                                    max="50000"
                                                    value={config.model?.max_thought_chars ?? 4000}
                                                    onChange={e => handleChange('model', 'max_thought_chars', e.target.value, 'number')}
                                                    className="w-24 bg-black/30 border border-white/10 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-white/30"
                                                />
                                            </div>
                                            <p className="text-[10px] opacity-40 mt-1">Ограничивает объем блока «Размышления модели» в чате</p>
                                        </div>
                                    </div>
                                    <div className="pt-2 border-t border-white/5 space-y-4">
                                        <div className="flex items-center justify-between">
                                            <label className="text-sm opacity-80 cursor-pointer flex items-center gap-2">
                                                <input
                                                    type="checkbox"
                                                    checked={config.model?.use_external_server || false}
                                                    onChange={e => handleChange('model', 'use_external_server', e.target.checked, 'boolean')}
                                                    className="rounded bg-black/30 border-white/10"
                                                />
                                                Внешний LLM-сервер (Ollama/LM Studio)
                                            </label>
                                        </div>
                                        {config.model?.use_external_server && (
                                            <div>
                                                <label className="block text-sm opacity-50 mb-1">API Base URL</label>
                                                <input
                                                    type="text"
                                                    value={config.model?.external_api_url || ''}
                                                    onChange={e => handleChange('model', 'external_api_url', e.target.value, 'string')}
                                                    placeholder="http://127.0.0.1:11434/v1"
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                                />
                                                <p className="text-[10px] opacity-40 mt-1">
                                                    Например: http://localhost:11434/v1 (Ollama) или http://localhost:1234/v1 (LM Studio)
                                                </p>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </section>

                            <div className="h-px bg-white/5 w-full" />

                            <section>
                                <h3 className="text-sm font-semibold opacity-50 uppercase tracking-widest mb-4">Озвучивание (TTS)</h3>
                                <div className="space-y-4">
                                    <div className="grid grid-cols-2 gap-4">
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">Скорость речи (speed)</label>
                                            <input
                                                type="number" step="0.05"
                                                value={config.tts?.speed || 1.15}
                                                onChange={e => handleChange('tts', 'speed', e.target.value, 'float')}
                                                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                            />
                                        </div>
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">Громкость (0.0 - 1.0)</label>
                                            <input
                                                type="number" step="0.1"
                                                value={config.tts?.volume || 0.8}
                                                onChange={e => handleChange('tts', 'volume', e.target.value, 'float')}
                                                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                            />
                                        </div>
                                    </div>
                                    <div className="grid grid-cols-2 gap-4">
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">Голос</label>
                                            <select
                                                value={config.tts?.voice_name || 'Lily'}
                                                onChange={e => handleChange('tts', 'voice_name', e.target.value, 'string')}
                                                className="w-full bg-[#161616] border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30 text-white"
                                            >
                                                <option value="Lily">Вера (женский, рекомендуется)</option>
                                                <option value="F1">Алиса (женский)</option>
                                                <option value="F2">Мира (женский)</option>
                                                <option value="F3">София (женский)</option>
                                                <option value="F4">Ника (женский)</option>
                                                <option value="F5">Ева (женский)</option>
                                                <option value="M1">Максим (мужской)</option>
                                                <option value="M2">Илья (мужской)</option>
                                                <option value="M3">Даниил (мужской)</option>
                                                <option value="M4">Кирилл (мужской)</option>
                                                <option value="M5">Роман (мужской)</option>
                                            </select>
                                        </div>
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">Шаги синтеза (total_steps)</label>
                                            <input
                                                type="number" min="1" max="10"
                                                value={config.tts?.total_steps || 4}
                                                onChange={e => handleChange('tts', 'total_steps', e.target.value, 'number')}
                                                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                            />
                                        </div>
                                    </div>
                                </div>
                            </section>

                            <div className="h-px bg-white/5 w-full" />

                            {/* Web Search */}
                            <section>
                                <h3 className="text-sm font-semibold opacity-50 uppercase tracking-widest mb-4">Web Search</h3>
                                <div className="space-y-4">
                                    <div>
                                        <label className="block text-sm opacity-80 mb-1">Лимит контекста поиска</label>
                                        <input
                                            type="number"
                                            value={config.web_search?.total_context_limit || 0}
                                            onChange={e => handleChange('web_search', 'total_context_limit', e.target.value, 'number')}
                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                        />
                                    </div>
                                </div>
                            </section>

                            <div className="h-px bg-white/5 w-full" />

                            {/* Sites */}
                            <section>
                                <div className="flex items-center justify-between mb-4">
                                    <h3 className="text-sm font-semibold opacity-50 uppercase tracking-widest">Сайты</h3>
                                    <button
                                        onClick={handleAddSite}
                                        className="settings-add-button"
                                    >
                                        <Plus size={13} />
                                        Добавить
                                    </button>
                                </div>
                                <div className="space-y-3">
                                    {Object.entries(config.sites || {}).map(([key, value], idx) => (
                                        <div key={idx} className="flex gap-2 items-center">
                                            <input
                                                type="text"
                                                value={key}
                                                placeholder="Активационное слово"
                                                onChange={e => handleSiteChange(key, e.target.value, value as string, true)}
                                                className="w-1/3 bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                            />
                                            <input
                                                type="text"
                                                value={value as string}
                                                placeholder="https://..."
                                                onChange={e => handleSiteChange(key, key, e.target.value, false)}
                                                className="flex-1 bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                            />
                                            <button
                                                onClick={() => handleRemoveSite(key)}
                                                className="p-2 opacity-50 hover:opacity-100 hover:bg-red-500/20 text-red-400 rounded-lg transition-all"
                                            >
                                                <X size={16} />
                                            </button>
                                        </div>
                                    ))}
                                    {Object.keys(config.sites || {}).length === 0 && (
                                        <div className="text-sm opacity-50 px-2 py-4 border border-dashed border-white/10 rounded-lg text-center">
                                            Нет добавленных сайтов
                                        </div>
                                    )}
                                </div>
                            </section>

                            <div className="h-px bg-white/5 w-full" />

                            {/* Periodic Tasks */}
                            <section>
                                <div className="flex items-center justify-between mb-4">
                                    <h3 className="text-sm font-semibold opacity-50 uppercase tracking-widest">Периодические задачи</h3>
                                    <button
                                        onClick={handleAddTask}
                                        className="settings-add-button"
                                    >
                                        <Plus size={13} />
                                        Добавить задачу
                                    </button>
                                </div>
                                <div className="space-y-4">
                                    {tasks.map((task, idx) => (
                                        <div key={idx} className="flex flex-col gap-2 p-3 bg-white/5 rounded-lg border border-white/5">
                                            <div className="flex items-center justify-between gap-2">
                                                <input
                                                    type="text"
                                                    value={task.task_text}
                                                    onChange={e => handleTaskChange(idx, 'task_text', e.target.value)}
                                                    className="flex-1 bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                                    placeholder="Текст задачи (например, выпей воду)"
                                                />
                                                <div className="flex items-center gap-2">
                                                    <label className="text-sm flex items-center gap-1 cursor-pointer">
                                                        <input
                                                            type="checkbox"
                                                            checked={task.enabled}
                                                            onChange={e => handleTaskChange(idx, 'enabled', e.target.checked)}
                                                            className="rounded bg-black/30 border-white/10"
                                                        />
                                                        <span className="opacity-80">Вкл</span>
                                                    </label>
                                                    <button
                                                        onClick={() => handleRemoveTask(idx)}
                                                        className="p-1.5 opacity-50 hover:opacity-100 hover:bg-red-500/20 text-red-400 rounded-lg transition-all"
                                                        title="Удалить задачу"
                                                    >
                                                        <X size={16} />
                                                    </button>
                                                </div>
                                            </div>
                                            <div className="flex flex-wrap gap-2">
                                                <select
                                                    value={task.recurring}
                                                    onChange={e => handleTaskChange(idx, 'recurring', e.target.value)}
                                                    className="bg-black/30 border border-white/10 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-white/30"
                                                >
                                                    <option value="once">Один раз</option>
                                                    <option value="daily">Ежедневно</option>
                                                    <option value="weekdays">По будням</option>
                                                    <option value="weekends">По выходным</option>
                                                    <option value="interval">С интервалом</option>
                                                </select>

                                                {task.recurring !== 'interval' && (
                                                    <input
                                                        type="time"
                                                        value={task.time ? task.time.split(':').map((p: string) => p.padStart(2, '0')).join(':') : ''}
                                                        onChange={e => handleTaskChange(idx, 'time', e.target.value)}
                                                        className="bg-black/30 border border-white/10 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-white/30"
                                                    />
                                                )}

                                                {task.recurring === 'once' && (
                                                    <input
                                                        type="date"
                                                        value={task.target_date || ''}
                                                        onChange={e => handleTaskChange(idx, 'target_date', e.target.value)}
                                                        className="bg-black/30 border border-white/10 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-white/30"
                                                    />
                                                )}

                                                {task.recurring === 'interval' && (
                                                    <div className="flex items-center gap-2 bg-black/30 border border-white/10 rounded-lg px-2 py-1.5">
                                                        <input
                                                            type="number"
                                                            min="1"
                                                            value={task.interval_minutes}
                                                            onChange={e => handleTaskChange(idx, 'interval_minutes', parseInt(e.target.value) || 0)}
                                                            className="w-16 bg-transparent text-sm focus:outline-none text-right"
                                                        />
                                                        <span className="text-sm opacity-50">минут</span>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                    {tasks.length === 0 && (
                                        <div className="text-sm opacity-50 px-2 py-4 border border-dashed border-white/10 rounded-lg text-center">
                                            Нет активных задач
                                        </div>
                                    )}
                                </div>
                            </section>


                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="p-4 border-t border-white/10 bg-white/5 flex items-center justify-between no-drag-region">
                    <div className="text-sm text-green-400 font-medium px-2">
                        {message}
                    </div>
                    <div className="flex gap-2">
                        <button onClick={onClose} className="px-4 py-2 text-sm font-medium opacity-80 hover:bg-white/10 rounded-lg transition-all">
                            Отмена
                        </button>
                        <button
                            onClick={handleSave}
                            disabled={loading || !config}
                            className="px-5 py-2 text-sm font-medium bg-white text-black hover:bg-white/90 rounded-lg transition-all disabled:opacity-50"
                        >
                            {loading ? 'Сохранение...' : 'Сохранить'}
                        </button>
                    </div>
                </div>
            </motion.div>
        </div>
    );
}

export default function App() {
    const [route, setRoute] = useState(window.location.hash || '#/chat');
    const [currentThemeId, setCurrentThemeId] = useState<VeraThemeId>(() => {
        const saved = localStorage.getItem(THEME_STORAGE_KEY);
        return getThemeById(saved).id;
    });
    const skipNextThemeBroadcastRef = useRef(false);

    const currentTheme = getThemeById(currentThemeId);
    const isLightMode = currentTheme.mode === 'light';

    useEffect(() => {
        localStorage.setItem(THEME_STORAGE_KEY, currentThemeId);
        document.documentElement.dataset.veraTheme = currentThemeId;
        document.body.classList.toggle('light-mode', isLightMode);
        if (skipNextThemeBroadcastRef.current) {
            skipNextThemeBroadcastRef.current = false;
            return;
        }
        if (ipcRenderer) {
            ipcRenderer.send('theme-updated', currentThemeId);
        }
    }, [currentThemeId, isLightMode]);

    useEffect(() => {
        const handleHashChange = () => setRoute(window.location.hash);
        window.addEventListener('hashchange', handleHashChange);
        return () => window.removeEventListener('hashchange', handleHashChange);
    }, []);

    useEffect(() => {
        const handleStorage = (event: StorageEvent) => {
            if (event.key !== THEME_STORAGE_KEY) {
                return;
            }
            const nextThemeId = getThemeById(event.newValue).id;
            setCurrentThemeId(prev => (prev === nextThemeId ? prev : nextThemeId));
        };

        window.addEventListener('storage', handleStorage);
        return () => window.removeEventListener('storage', handleStorage);
    }, []);

    useEffect(() => {
        if (!ipcRenderer) {
            return;
        }

        const onThemeChanged = (_event: unknown, themeId: VeraThemeId) => {
            const nextThemeId = getThemeById(themeId).id;
            skipNextThemeBroadcastRef.current = true;
            setCurrentThemeId(prev => (prev === nextThemeId ? prev : nextThemeId));
        };

        ipcRenderer.on('theme-changed', onThemeChanged);
        return () => {
            ipcRenderer.removeListener('theme-changed', onThemeChanged);
        };
    }, []);

    if (route === '#/widget') return <WidgetView isLightMode={isLightMode} />;
    return (
        <ChatView
            currentThemeId={currentThemeId}
            onThemeChange={setCurrentThemeId}
            isLightMode={isLightMode}
        />
    );
}

const SOUNDWAVE_BASE_HEIGHTS = [8, 14, 20, 26, 32, 26, 20, 14, 8];

function SoundWave({ isSpeaking, isThinking, isLightMode }: { isSpeaking: boolean; isThinking: boolean; isLightMode: boolean }) {
    const barsCount = 9;
    const [isAfk, setIsAfk] = useState(false);

    useEffect(() => {
        setIsAfk(false);
        if (isSpeaking || isThinking) {
            return;
        }
        
        // Таймер бездействия на 25 секунд
        const timer = setTimeout(() => {
            setIsAfk(true);
        }, 25000);

        return () => clearTimeout(timer);
    }, [isSpeaking, isThinking]);

    return (
        <motion.div 
            className="relative w-[43px] h-10 flex items-center justify-center cursor-pointer no-drag-region"
            animate={isAfk ? { rotate: 360 } : { rotate: 0 }}
            transition={isAfk ? { repeat: Infinity, duration: 3.5, ease: "linear" } : { duration: 0.5 }}
        >
            {Array.from({ length: barsCount }).map((_, i) => {
                const baseHeight = SOUNDWAVE_BASE_HEIGHTS[i];
                
                // Анимация высоты полос
                let heightAnimate: any = 3; // По умолчанию (listening) - плоские точки (3px)
                let transition: any = { duration: 0.3 };

                if (isSpeaking && !isAfk) {
                    const peak = baseHeight;
                    const valley = 3;
                    
                    // Симуляция речи: псевдослучайные флуктуации (слоги и интонации)
                    heightAnimate = [
                        valley,
                        peak * 0.4,
                        peak * 0.9,
                        valley * 1.5,
                        peak * 0.6,
                        peak * 1.0,
                        valley,
                        peak * 0.5,
                        peak * 0.8,
                        valley
                    ];
                    
                    transition = {
                        duration: 1.4,
                        repeat: Infinity,
                        repeatType: "loop",
                        ease: "easeInOut",
                        delay: Math.abs(4 - i) * 0.07, // расходится от центра к краям симметрично
                    };
                } else if (isThinking && !isAfk) {
                    // Медленная, плавная пульсация от центра к краям в режиме размышления
                    heightAnimate = [3, baseHeight * 0.4, 3];
                    transition = {
                        duration: 2.0,
                        repeat: Infinity,
                        repeatType: "mirror",
                        ease: "easeInOut",
                        delay: Math.abs(4 - i) * 0.15,
                    };
                }

                // Расчет координат x и y в зависимости от режима AFK (радиус увеличен до 13)
                const angle = (i * 40 * Math.PI) / 180;
                const targetX = isAfk ? 13 * Math.cos(angle) : (i - 4) * 5;
                const targetY = isAfk ? 13 * Math.sin(angle) : 0;

                // Цвета, прозрачность и свечение
                let colorStyle = isLightMode ? "rgba(17, 24, 39, 0.38)" : "rgba(255, 255, 255, 0.35)";
                let dropShadow = "none";

                if (isSpeaking && !isAfk) {
                    colorStyle = isLightMode ? "#111827" : "#ffffff";
                    dropShadow = isLightMode
                        ? "drop-shadow(0 0 3px rgba(17, 24, 39, 0.12))"
                        : "drop-shadow(0 0 4px rgba(255, 255, 255, 0.75))";
                } else if (isThinking && !isAfk) {
                    colorStyle = isLightMode ? "rgba(55, 65, 81, 0.92)" : "rgba(255, 255, 255, 0.85)";
                    dropShadow = isLightMode
                        ? "drop-shadow(0 0 3px rgba(55, 65, 81, 0.12))"
                        : "drop-shadow(0 0 3px rgba(255, 255, 255, 0.45))";
                } else if (isAfk) {
                    const opacity = 0.2 + (i / 8) * 0.8;
                    colorStyle = isLightMode
                        ? `rgba(55, 65, 81, ${Math.min(0.85, opacity)})`
                        : `rgba(255, 255, 255, ${opacity})`;
                    dropShadow = isLightMode
                        ? `drop-shadow(0 0 2px rgba(55, 65, 81, ${opacity * 0.18}))`
                        : `drop-shadow(0 0 3px rgba(255, 255, 255, ${opacity * 0.5}))`;
                }

                return (
                    <motion.div
                        key={i}
                        className="absolute w-[3px] rounded-full transition-colors duration-300"
                        style={{
                            height: 3,
                            backgroundColor: colorStyle,
                            filter: dropShadow,
                        }}
                        animate={{
                            height: heightAnimate,
                            x: targetX,
                            y: targetY,
                        }}
                        transition={{
                            height: isAfk ? { type: "tween", ease: "easeInOut", duration: 1.5 } : transition,
                            // Медленный плавный переход координат при морфинге (1.5 сек)
                            x: { type: "tween", ease: "easeInOut", duration: 1.5 },
                            y: { type: "tween", ease: "easeInOut", duration: 1.5 }
                        }}
                    />
                );
            })}
        </motion.div>
    );
}

function WidgetView({ isLightMode }: { isLightMode: boolean }) {
    const [status, setStatus] = useState('listening');

    const [timerDeadline, setTimerDeadline] = useState(() => {
        const saved = localStorage.getItem('vera_timer_deadline');
        if (!saved) return null;
        const v = parseFloat(saved);
        return (!isNaN(v) && v > Date.now() / 1000) ? v : null;
    });
    const [timerDisplay, setTimerDisplay] = useState('');
    const timerDeadlineRef = useRef(null);

    useEffect(() => {
        timerDeadlineRef.current = timerDeadline as any;
    }, [timerDeadline]);

    useEffect(() => {
        if (!timerDeadline) {
            setTimerDisplay('');
            return;
        }
        const tick = () => {
            const rem = (timerDeadlineRef.current ?? 0) - Date.now() / 1000;
            if (rem <= 0) {
                setTimerDeadline(null);
                localStorage.removeItem('vera_timer_deadline');
                setTimerDisplay('');
                return;
            }
            const h = Math.floor(rem / 3600);
            const m = Math.floor((rem % 3600) / 60);
            const s = Math.floor(rem % 60);
            setTimerDisplay(
                `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
            );
        };
        tick();
        const timerId = setInterval(tick, 1000);
        return () => clearInterval(timerId);
    }, [timerDeadline]);

    useEffect(() => {
        const onMessage = (event: MessageEvent) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'timer_delete') {
                    setTimerDeadline(null);
                    localStorage.removeItem('vera_timer_deadline');
                    setTimerDisplay('');
                }
            } catch (e) { }
        };
        window.addEventListener('message', onMessage);
        return () => window.removeEventListener('message', onMessage);
    }, []);

    useEffect(() => {
        const wsUrl = apiToken ? `ws://127.0.0.1:8000/ws?token=${apiToken}` : 'ws://127.0.0.1:8000/ws';
        return connectSocketWithReconnect(
            wsUrl,
            {
                onMessage: (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.type === 'state') {
                            setStatus(prev => (prev === data.value ? prev : data.value));
                        } else if (data.type === 'timer_start' && typeof data.deadline === 'number') {
                            setTimerDeadline(data.deadline);
                            localStorage.setItem('vera_timer_deadline', String(data.deadline));
                        } else if (data.type === 'timer_done') {
                            setTimerDeadline(null);
                            localStorage.removeItem('vera_timer_deadline');
                            setTimerDisplay('');
                        }
                    } catch (e) { }
                },
            },
            2000,
        );
    }, []);

    const handleClick = () => {
        if (ipcRenderer) ipcRenderer.send('toggle-chat');
    };

    const isSpeaking = status === 'speaking';
    const isThinking = status === 'thinking';
    const showTimer = !!timerDeadline && !!timerDisplay;

    return (
        <div className="vera-widget w-full h-full flex items-center justify-center rounded-2xl shadow-2xl drag-region select-none overflow-hidden transition-colors">
            {showTimer ? (
                <div
                    className="flex flex-col items-center justify-center cursor-pointer no-drag-region"
                    onClick={handleClick}
                    title="Timer active"
                >
                    {timerDisplay.split(':').map((part, i) => (
                        <div
                            key={i}
                            style={{
                                fontFamily: '"JetBrains Mono", "Fira Mono", "Courier New", monospace',
                                fontSize: '15px',
                                fontWeight: 700,
                                letterSpacing: '0.06em',
                                color: isLightMode
                                    ? (i === 0 ? 'rgba(55,65,81,0.55)' : '#111827')
                                    : (i === 0 ? 'rgba(255,255,255,0.5)' : '#ffffff'),
                                lineHeight: 1.05,
                                textShadow: isLightMode ? 'none' : '0 0 10px rgba(255,255,255,0.25)',
                            }}
                        >
                            {part}
                        </div>
                    ))}
                </div>
            ) : (
                <div className="relative flex items-center justify-center w-12 h-12 cursor-pointer no-drag-region" onClick={handleClick}>
                    <SoundWave isSpeaking={isSpeaking} isThinking={isThinking} isLightMode={isLightMode} />
                </div>
            )}
        </div>
    );
}

interface Message {
    role: string;
    text: string;
    thoughts?: string;
    file?: string;
    fileSize?: number;
    streaming?: boolean;
}

function SourceChips({ sources }: { sources: string[] }) {
    if (!sources.length) return null;

    return (
        <div className="source-chip-wrap">
            {sources.map((url, i) => (
                <button
                    key={url}
                    onClick={() => shell?.openExternal(url)}
                    className="source-chip"
                    title={url}
                    type="button"
                >
                    <span className="source-chip-index">{i + 1}</span>
                    <span className="source-chip-text">
                        <span className="source-chip-domain">{getDomain(url)}</span>
                        <span className="source-chip-path">{getSourcePath(url)}</span>
                    </span>
                    <ExternalLink size={12} className="source-chip-icon" />
                </button>
            ))}
        </div>
    );
}

const MessageBubble = memo(function MessageBubble({
    msg,
    isLightMode,
}: {
    msg: Message;
    isLightMode: boolean;
}) {
    return (
        <div
            className={`message-bubble role-${msg.role} max-w-[85%] rounded-2xl px-4 py-3 text-[15px] leading-relaxed relative select-text cursor-text ${msg.role === 'user'
                ? (isLightMode ? 'bg-[#e5e7eb] text-gray-900 font-medium shadow-sm border border-gray-300' : 'bg-white/10 text-white font-medium border border-white/10')
                : msg.role === 'system'
                    ? (isLightMode ? 'bg-black/5 text-gray-500 text-sm border border-gray-200 indent-0 italic' : 'bg-white/5 text-white/50 text-sm border border-white/5 italic')
                    : (isLightMode ? 'bg-[#ffffff] text-gray-800 border border-gray-200 shadow-sm' : 'bg-white/5 text-gray-200 border border-white/10')
                }`}
        >
            {msg.role === 'user' || msg.role === 'system' ? (
                <>
                    {msg.text && <div>{msg.text}</div>}
                    {msg.file && (
                        <div className={`attachment-card attachment-card-inline mt-3 ${isLightMode ? 'light' : ''}`}>
                            <div className="attachment-icon">
                                <FileText size={16} className="flex-shrink-0" />
                            </div>
                            <div className="attachment-body">
                                <div className="attachment-name truncate">{msg.file}</div>
                                <div className="attachment-meta-line">
                                    <span className="attachment-badge">{getFileExtension(msg.file)}</span>
                                    {msg.fileSize ? <span>{formatFileSize(msg.fileSize)}</span> : null}
                                </div>
                            </div>
                        </div>
                    )}
                </>
            ) : (() => {
                const { cleanText, sources, docPath } = parseMessage(msg.text);
                return (
                    <>
                        {msg.thoughts && <ThinkingBlock thoughts={msg.thoughts} isLightMode={isLightMode} />}
                        <AssistantMessageText text={cleanText} isLightMode={isLightMode} />
                        {sources.length > 0 && (
                            <div className={`mt-3 pt-2 border-t ${isLightMode ? 'border-gray-200' : 'border-white/5'}`}>
                                <SourceChips sources={sources} />
                            </div>
                        )}
                        {docPath && (
                            <div className={`flex flex-wrap gap-1.5 mt-2 pt-2 border-t ${isLightMode ? 'border-gray-200' : 'border-white/5'}`}>
                                <button
                                    onClick={() => shell?.showItemInFolder(docPath)}
                                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] border rounded-lg transition-all cursor-pointer font-medium ${isLightMode
                                        ? 'bg-blue-50 hover:bg-blue-100 border-blue-200 text-blue-700 hover:text-blue-800'
                                        : 'bg-blue-500/20 hover:bg-blue-500/30 border-blue-500/30 text-blue-200 hover:text-white'
                                        }`}
                                    title={docPath}
                                >
                                    <FolderOpen size={12} />
                                    Открыть папку с файлом
                                </button>
                            </div>
                        )}
                    </>
                );
            })()}
        </div>
    );
});

function ChatView({
    currentThemeId,
    onThemeChange,
    isLightMode,
}: {
    currentThemeId: VeraThemeId;
    onThemeChange: (themeId: VeraThemeId) => void;
    isLightMode: boolean;
}) {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [status, setStatus] = useState('listening');
    const [isSettingsOpen, setIsSettingsOpen] = useState(false);
    const [isConnected, setIsConnected] = useState(false);
    const [thinkingEnabled, setThinkingEnabled] = useState(() => {
        const saved = localStorage.getItem('vera_thinking_enabled');
        return saved === null ? true : saved === 'true';
    });
    const [reasoningBudget, setReasoningBudget] = useState(() => {
        const parsed = Number.parseInt(localStorage.getItem('vera_reasoning_budget') || '1024', 10);
        return Number.isFinite(parsed) ? parsed : 1024;
    });

    const wsRef = useRef<WebSocket | null>(null);
    const messagesEndRef = useRef<HTMLDivElement | null>(null);
    const pendingUserMsgs = useRef<Set<string>>(new Set()); // РўСЂРµРєРµСЂ РѕРїС‚РёРјРёСЃС‚РёС‡РЅС‹С… СЃРѕРѕР±С‰РµРЅРёР№
    const fileInputRef = useRef<HTMLInputElement | null>(null);
    const [attachedFile, setAttachedFile] = useState<File | null>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [isMuted, setIsMuted] = useState(false);
    const [renderWindow, setRenderWindow] = useState(120);
    const thinkingEnabledRef = useRef(thinkingEnabled);
    const reasoningBudgetRef = useRef(reasoningBudget);
    const pendingChunksRef = useRef<any[]>([]);
    const chunkFlushRafRef = useRef<number | null>(null);
    const ignoreLateChunksRef = useRef(false);

    const findLastStreamingAssistantIndex = useCallback((arr: Message[]): number => {
        for (let i = arr.length - 1; i >= 0; i--) {
            const msg = arr[i];
            if (msg.role === 'assistant' && msg.streaming) return i;
        }
        return -1;
    }, []);

    const reduceMotion = useMemo(() => {
        if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
            return false;
        }
        return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }, []);

    const visibleMessages = useMemo(() => {
        if (messages.length <= renderWindow) return messages;
        return messages.slice(-renderWindow);
    }, [messages, renderWindow]);
    const pushSystemMessage = useCallback((text: string) => {
        setMessages(prev => [...prev, { role: 'system', text }]);
    }, []);

    const flushChunkBatch = useCallback(() => {
        chunkFlushRafRef.current = null;
        const batch = pendingChunksRef.current;
        pendingChunksRef.current = [];
        if (batch.length === 0) return;

        setMessages(prev => {
            let next = [...prev];
            for (const chunk of batch) {
                const streamIdx = findLastStreamingAssistantIndex(next);
                if (streamIdx !== -1) {
                    const updated = { ...next[streamIdx] };
                    if (chunk.type === 'chat_chunk') {
                        updated.text += String(chunk.text || '');
                    } else {
                        updated.thoughts = (updated.thoughts || '') + String(chunk.text || '');
                    }
                    next = [...next.slice(0, streamIdx), updated, ...next.slice(streamIdx + 1)];
                } else {
                    next = [
                        ...next,
                        {
                            role: 'assistant',
                            text: chunk.type === 'chat_chunk' ? String(chunk.text || '') : '',
                            thoughts: chunk.type === 'thought_chunk' ? String(chunk.text || '') : '',
                            streaming: true,
                        },
                    ];
                }
            }
            return next;
        });
    }, [findLastStreamingAssistantIndex]);

    const enqueueChunk = useCallback((chunk: any) => {
        if (ignoreLateChunksRef.current) {
            return;
        }
        pendingChunksRef.current.push(chunk);
        if (chunkFlushRafRef.current == null) {
            chunkFlushRafRef.current = window.requestAnimationFrame(flushChunkBatch);
        }
    }, [flushChunkBatch]);

    useEffect(() => {
        const wsUrl = apiToken ? `ws://127.0.0.1:8000/ws?token=${apiToken}` : 'ws://127.0.0.1:8000/ws';
        return connectSocketWithReconnect(
            wsUrl,
            {
                onOpen: (ws) => {
                    wsRef.current = ws;
                    setIsConnected(prev => (prev ? prev : true));
                    ws.send(JSON.stringify({
                        type: 'set_thinking_mode',
                        enabled: thinkingEnabledRef.current,
                        reasoning_budget: reasoningBudgetRef.current,
                    }));
                    ws.send(JSON.stringify({ type: 'get_thinking_mode' }));
                },
                onError: () => setIsConnected(prev => (prev ? false : prev)),
                onClose: () => setIsConnected(prev => (prev ? false : prev)),
                onMessage: (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.type === 'state') {
                            setStatus(prev => (prev === data.value ? prev : data.value));
                            return;
                        }
                        if (data.type === 'thinking_mode') {
                            if (typeof data.enabled === 'boolean') {
                                setThinkingEnabled(prev => (prev === data.enabled ? prev : data.enabled));
                            }
                            if (typeof data.reasoning_budget === 'number') {
                                setReasoningBudget(prev => (prev === data.reasoning_budget ? prev : data.reasoning_budget));
                            }
                            return;
                        }
                        if (data.type === 'task_status') {
                            if (data.state === 'queued' || data.state === 'running') {
                                ignoreLateChunksRef.current = false;
                            }
                            if (data.state === 'failed' && data.reason) {
                                pushSystemMessage(`Задача завершилась с ошибкой: ${data.reason}`);
                            }
                            return;
                        }
                        if (data.type === 'action_explain') {
                            // Keep explain events internal (audit/debug), do not show in chat UI.
                            return;
                        }

                        if (data.type === 'chat') {
                            if (data.role === 'user' && pendingUserMsgs.current.has(data.text)) {
                                pendingUserMsgs.current.delete(data.text);
                                return;
                            }
                            if (data.role === 'assistant') {
                                ignoreLateChunksRef.current = true;
                                pendingChunksRef.current = [];
                                if (chunkFlushRafRef.current != null) {
                                    window.cancelAnimationFrame(chunkFlushRafRef.current);
                                    chunkFlushRafRef.current = null;
                                }
                                setMessages(prev => {
                                    const streamIdx = findLastStreamingAssistantIndex(prev);
                                    if (streamIdx !== -1) {
                                        const streamMsg = prev[streamIdx];
                                        const finalized = { ...streamMsg, text: data.text, streaming: false };
                                        const withoutStream = [...prev.slice(0, streamIdx), ...prev.slice(streamIdx + 1)];
                                        return [...withoutStream, finalized];
                                    }
                                    return [...prev, { role: data.role, text: data.text }];
                                });
                            } else {
                                setMessages(prev => [...prev, { role: data.role, text: data.text }]);
                            }
                            return;
                        }
                        if (data.type === 'chat_chunk' || data.type === 'thought_chunk') {
                            enqueueChunk(data);
                            return;
                        }
                        if (data.type === 'tool_call') {
                            pushSystemMessage(`Использую инструмент: ${data.name}...`);
                        }
                    } catch (e) { }
                },
            },
            2000,
        );
    }, [enqueueChunk, findLastStreamingAssistantIndex, pushSystemMessage]);
    useEffect(() => {
        if (!ipcRenderer) {
            return;
        }

        const onBackendStatus = (_event: unknown, payload: any) => {
            if (!payload || typeof payload !== 'object') {
                return;
            }

            if (payload.type === 'restarting') {
                const delayMs = Number(payload.delayMs) || 1000;
                const seconds = Math.max(1, Math.round(delayMs / 1000));
                const attempt = Number(payload.attempt) || 1;
                const maxAttempts = Number(payload.maxAttempts) || 5;
                setMessages(prev => [...prev, {
                    role: 'system',
                    text: `Проблема с сервером, перезапуск через ${seconds} сек (попытка ${attempt}/${maxAttempts}).`,
                }]);
                return;
            }

            if (payload.type === 'restart_failed') {
                const maxAttempts = Number(payload.maxAttempts) || 5;
                setMessages(prev => [...prev, {
                    role: 'system',
                    text: `Не удалось восстановить сервер после ${maxAttempts} попыток перезапуска.`,
                }]);
                return;
            }

            if (payload.type === 'network_issue') {
                setMessages(prev => [...prev, {
                    role: 'system',
                    text: 'Обнаружены неполадки сети. Некоторые функции могут временно не работать.',
                }]);
            }
        };

        ipcRenderer.on('backend-status', onBackendStatus);
        return () => {
            ipcRenderer.removeListener('backend-status', onBackendStatus);
        };
    }, []);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth' });
    }, [messages, reduceMotion]);

    useEffect(() => {
        localStorage.setItem('vera_thinking_enabled', thinkingEnabled.toString());
        thinkingEnabledRef.current = thinkingEnabled;
    }, [thinkingEnabled]);

    useEffect(() => {
        localStorage.setItem('vera_reasoning_budget', reasoningBudget.toString());
        reasoningBudgetRef.current = reasoningBudget;
    }, [reasoningBudget]);

    useEffect(() => {
        setRenderWindow(120);
    }, []);

    useEffect(() => {
        return () => {
            if (chunkFlushRafRef.current != null) {
                window.cancelAnimationFrame(chunkFlushRafRef.current);
                chunkFlushRafRef.current = null;
            }
            pendingChunksRef.current = [];
        };
    }, []);

    const handleClose = () => {
        if (ipcRenderer) ipcRenderer.send('close-chat');
    };

    const handleSend = useCallback(async (e: React.FormEvent) => {
        e.preventDefault();
        if ((!input.trim() && !attachedFile) || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
        ignoreLateChunksRef.current = false;
        pendingChunksRef.current = [];
        if (chunkFlushRafRef.current != null) {
            window.cancelAnimationFrame(chunkFlushRafRef.current);
            chunkFlushRafRef.current = null;
        }
        // Р—Р°РєСЂС‹РІР°РµРј РІРѕР·РјРѕР¶РЅС‹Р№ РЅРµР·Р°РІРµСЂС€С‘РЅРЅС‹Р№ СЃС‚СЂРёРј РѕС‚ РїСЂРѕС€Р»РѕРіРѕ Р·Р°РїСЂРѕСЃР°
        setMessages(prev => prev.map(msg => (msg.streaming ? { ...msg, streaming: false } : msg)));

        let fullText = input.trim();
        let fileContextStr = '';

        // РћРїС‚РёРјРёСЃС‚РёС‡РЅРѕРµ РѕС‚РѕР±СЂР°Р¶РµРЅРёРµ СЃРѕРѕР±С‰РµРЅРёСЏ
        const userMsg: Message = { role: 'user', text: fullText };
        if (attachedFile) {
            userMsg.file = attachedFile.name;
            userMsg.fileSize = attachedFile.size;
        }
        setMessages(prev => [...prev, userMsg]);
        pendingUserMsgs.current.add(fullText || (attachedFile ? attachedFile.name : ''));

        // Р•СЃР»Рё РµСЃС‚СЊ С„Р°Р№Р» вЂ” Р·Р°РіСЂСѓР¶Р°РµРј Рё РёР·РІР»РµРєР°РµРј С‚РµРєСЃС‚
        if (attachedFile) {
            setIsUploading(true);
            try {
                const formData = new FormData();
                formData.append('file', attachedFile);
                const res = await veraFetch('http://127.0.0.1:8000/api/upload', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                fileContextStr = data.text || '';
            } catch (err) {
                fileContextStr = `[Ошибка загрузки файла: ${attachedFile.name}]`;
            } finally {
                setIsUploading(false);
                setAttachedFile(null);
                if (fileInputRef.current) fileInputRef.current.value = '';
            }
        }

        const payload = {
            type: 'command',
            text: fullText,
            file_name: attachedFile ? attachedFile.name : null,
            file_context: fileContextStr,
            task_id: `ui-${Date.now()}-${Math.floor(Math.random() * 100000)}`,
        };

        wsRef.current.send(JSON.stringify(payload));
        setInput('');
    }, [input, attachedFile]);

    const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) setAttachedFile(file);
    }, []);

    const handleRemoveFile = useCallback(() => {
        setAttachedFile(null);
        if (fileInputRef.current) fileInputRef.current.value = '';
    }, []);

    const toggleMute = useCallback(() => {
        if (!wsRef.current) return;
        const newMutedState = !isMuted;
        setIsMuted(newMutedState);
        const command = newMutedState ? '/mute' : '/unmute';
        const payload = {
            type: 'command',
            text: command,
            file_name: null,
            file_context: ''
        };
        wsRef.current.send(JSON.stringify(payload));
    }, [isMuted]);

    const toggleThinking = useCallback(() => {
        const next = !thinkingEnabled;
        setThinkingEnabled(next);
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
        wsRef.current.send(JSON.stringify({
            type: 'set_thinking_mode',
            enabled: next,
            reasoning_budget: reasoningBudget
        }));
    }, [thinkingEnabled, reasoningBudget]);

    return (
        <div className="vera-shell relative w-full h-full flex flex-col rounded-xl overflow-hidden shadow-2xl transition-colors">
            <AnimatePresence>
                <SettingsModal
                    isOpen={isSettingsOpen}
                    onClose={() => setIsSettingsOpen(false)}
                    currentThemeId={currentThemeId}
                    onThemeChange={onThemeChange}
                />
            </AnimatePresence>

            {/* РЁР°РїРєР° (Drag Region) */}
            <div className={`flex items-center justify-between px-4 py-3 border-b drag-region transition-colors ${isLightMode ? 'bg-[#ffffff]/50 border-gray-200/50' : 'bg-white/5 border-white/10'
                }`}>
                <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full bg-slate-400 relative">
                        {isConnected && status === 'speaking' && <div className={`absolute inset-0 w-full h-full rounded-full animate-pulse ${isLightMode ? 'bg-blue-500' : 'bg-white'}`} />}
                        {isConnected && status === 'thinking' && <div className={`absolute inset-0 w-full h-full rounded-full animate-pulse ${isLightMode ? 'bg-slate-500' : 'bg-slate-300'}`} />}
                        {!isConnected && <div className="absolute inset-0 w-full h-full rounded-full animate-pulse bg-red-500" />}
                    </div>
                    <span className={`text-sm font-medium tracking-wide select-none flex items-center ${isLightMode ? 'opacity-90' : 'opacity-80'}`}>
                        Vera
                        {!isConnected && <span className="text-[11px] font-normal tracking-normal ml-2 text-red-500/90 whitespace-nowrap">(ожидание)</span>}
                    </span>
                </div>
                <div className="flex items-center gap-2 no-drag-region">
                    <button
                        onClick={() => isConnected && setIsSettingsOpen(true)}
                        disabled={!isConnected}
                        className={`p-1.5 rounded-md transition-all ${!isConnected
                            ? 'opacity-30 cursor-not-allowed text-gray-400'
                            : (isLightMode
                                ? 'text-gray-600 hover:bg-black/5 hover:text-gray-900'
                                : 'text-white opacity-50 hover:opacity-100 hover:bg-white/10')
                            }`}>
                        <Settings size={16} />
                    </button>
                    <button onClick={handleClose} className={`p-1 rounded-md transition-all ${isLightMode
                        ? 'text-gray-600 hover:bg-red-50 hover:text-red-500'
                        : 'text-white opacity-50 hover:opacity-100 hover:bg-red-500/20 hover:text-red-400'
                        }`}>
                        <X size={16} />
                    </button>
                </div>
            </div>

            {/* РЎРѕРѕР±С‰РµРЅРёСЏ */}
            <div className="flex-1 overflow-y-auto p-4 space-y-6 no-drag-region">
                {messages.length === 0 && (
                    <div className={`h-full flex items-center justify-center text-sm ${isLightMode ? 'text-gray-400' : 'opacity-30'}`}>
                        Скажите команду или напишите ниже...
                    </div>
                )}

                {messages.length > visibleMessages.length && (
                    <div className="flex justify-center">
                        <button
                            onClick={() => setRenderWindow(prev => Math.min(messages.length, prev + 120))}
                            className={`text-[12px] px-3 py-1 rounded-md border ${isLightMode
                                ? 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
                                : 'bg-white/5 border-white/15 text-white/70 hover:bg-white/10'
                                }`}
                        >
                            Показать ещё ({messages.length - visibleMessages.length})
                        </button>
                    </div>
                )}

                <AnimatePresence initial={false}>
                    {visibleMessages.map((msg, idx) => {
                        const absoluteIdx = messages.length - visibleMessages.length + idx;
                        return (
                            <motion.div
                                key={`${absoluteIdx}-${msg.role}`}
                                initial={reduceMotion ? false : { opacity: 0, y: 8 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ duration: reduceMotion ? 0.12 : 0.2 }}
                                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                            >
                                <MessageBubble msg={msg} isLightMode={isLightMode} />
                            </motion.div>
                        );
                    })}
                    {status === 'thinking' && (
                        <motion.div initial={reduceMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start">
                            <div className={`px-4 py-3 text-sm italic flex items-center gap-2 ${isLightMode ? 'text-gray-500' : 'text-white/40'}`}>
                                <div className={`w-1 h-1 rounded-full ${reduceMotion ? '' : 'animate-bounce'} ${isLightMode ? 'bg-gray-400' : 'bg-white/40'}`} />
                                <div className={`w-1 h-1 rounded-full ${reduceMotion ? '' : 'animate-bounce'} ${isLightMode ? 'bg-gray-400' : 'bg-white/40'}`} style={{ animationDelay: '0.2s' }} />
                                <div className={`w-1 h-1 rounded-full ${reduceMotion ? '' : 'animate-bounce'} ${isLightMode ? 'bg-gray-400' : 'bg-white/40'}`} style={{ animationDelay: '0.4s' }} />
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
                <div ref={messagesEndRef} />
            </div>

            {/* РџР°РЅРµР»СЊ РІРІРѕРґР° */}
            <div className={`p-4 ${isLightMode ? 'bg-[#ffffff]/50 border-t border-gray-200/50' : 'bg-transparent'}`}>
                {/* Р§РёРї РїСЂРёРєСЂРµРїР»С‘РЅРЅРѕРіРѕ С„Р°Р№Р»Р° */}
                {attachedFile && (
                    <div className="mb-3 max-w-3xl mx-auto">
                        <div className={`attachment-card ${isLightMode ? 'light' : ''}`}>
                            <div className="attachment-icon">
                                <FileText size={18} />
                            </div>
                            <div className="attachment-body">
                                <div className="attachment-name" title={attachedFile.name}>{attachedFile.name}</div>
                                <div className="attachment-meta-line">
                                    <span className="attachment-badge">{getFileExtension(attachedFile.name)}</span>
                                    <span>{formatFileSize(attachedFile.size)}</span>
                                    <span>будет добавлен в запрос</span>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={handleRemoveFile}
                                className="attachment-remove"
                                title="Убрать файл"
                            >
                                <X size={14} />
                            </button>
                        </div>
                    </div>
                )}

                {/* Hidden file input */}
                <input
                    ref={fileInputRef}
                    type="file"
                    accept=".docx,.doc,.txt,.md,.py,.pdf,.xlsx,.xls,.pptx,.json,.csv,.xml,.html,.css,.js,.log"
                    onChange={handleFileSelect}
                    className="hidden"
                />

                <form onSubmit={handleSend} className={`relative flex items-center w-full max-w-3xl mx-auto rounded-xl border overflow-hidden transition-all ${!isConnected ? 'opacity-50 pointer-events-none grayscale' : ''
                    } ${isLightMode
                        ? 'bg-white border-gray-300 focus-within:border-blue-500 focus-within:shadow-[0_0_0_1px_rgba(59,130,246,0.5)]'
                        : 'bg-white/10 border-white/15 focus-within:border-white/30 focus-within:bg-white/15'
                    }`}>
                    <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        className={`pl-4 pr-1 transition-all cursor-pointer ${isLightMode
                            ? (attachedFile ? 'text-blue-500' : 'text-gray-400 hover:text-gray-600')
                            : (attachedFile ? 'text-white' : 'opacity-50 hover:opacity-80')
                            }`}
                        title="Прикрепить файл"
                    >
                        <Paperclip size={18} />
                    </button>
                    <button
                        type="button"
                        onClick={toggleMute}
                        className={`pr-2 pl-1 transition-all cursor-pointer ${isLightMode
                            ? (isMuted ? 'text-red-500 hover:text-red-600' : 'text-gray-400 hover:text-gray-600')
                            : (isMuted ? 'text-red-400 hover:text-red-300' : 'opacity-50 hover:opacity-80')
                            }`}
                        title={isMuted ? "Включить микрофон" : "Выключить микрофон"}
                    >
                        {isMuted ? <MicOff size={18} /> : <Mic size={18} />}
                    </button>
                    <button
                        type="button"
                        onClick={toggleThinking}
                        className={`pr-2 pl-1 transition-all cursor-pointer ${isLightMode
                            ? (thinkingEnabled ? 'text-blue-600 hover:text-blue-700' : 'text-gray-400 hover:text-gray-600')
                            : (thinkingEnabled ? 'text-cyan-300 hover:text-cyan-200' : 'opacity-50 hover:opacity-80')
                            }`}
                        title={thinkingEnabled ? "Режим размышления включен" : "Режим размышления выключен"}
                    >
                        <Brain size={18} />
                    </button>
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder={attachedFile ? "Задайте вопрос по файлу..." : "Спросите или попросите о чем-либо..."}
                        className={`flex-1 bg-transparent border-none py-3.5 px-2 text-[15px] focus:outline-none focus:ring-0 ${isLightMode
                            ? 'text-gray-900 placeholder:text-gray-400'
                            : 'text-white placeholder:text-white/30'
                            }`}
                    />
                    <button
                        type="submit"
                        disabled={(!input.trim() && !attachedFile) || isUploading}
                        className={`pr-4 pl-2 transition-all ${isLightMode
                            ? 'text-blue-500 hover:text-blue-600 disabled:opacity-50 disabled:text-gray-400 disabled:hover:text-gray-400'
                            : 'text-white/50 hover:text-white disabled:opacity-30 disabled:hover:text-white/50'
                            }`}
                    >
                        {isUploading ? (
                            <div className={`w-4 h-4 border-2 rounded-full animate-spin ${isLightMode ? 'border-blue-300 border-t-blue-600' : 'border-white/20 border-t-white'
                                }`} />
                        ) : (
                            <Send size={18} />
                        )}
                    </button>
                </form>
            </div>

        </div>
    );
}

