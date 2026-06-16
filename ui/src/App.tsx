import { useEffect, useState, useRef, useCallback, useMemo, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Paperclip, X, ExternalLink, FolderOpen, FileText, FileStack, Mic, MicOff, Brain, ChevronDown, ChevronUp, ChevronRight, Pin, Trash2, Search, Database, Plus, Save, PanelRight, PanelLeft, Palette, Cpu, Volume2, Globe2, Clock3, SlidersHorizontal, Minus, Maximize2, Minimize2, TerminalSquare, UploadCloud, Folder, File as FileIcon, RefreshCw, Boxes, Wrench } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { connectSocketWithReconnect } from './services/socketService';
import { SessionPanelWindow } from './components/SessionPanelWindow';
import {
    createSession,
    listSessions,
    loadSessionMessages,
} from './services/sessionService';
import { ACTIVE_SESSION_EVENT, ACTIVE_SESSION_STORAGE_KEY, SESSIONS_REV_EVENT, SESSIONS_REV_STORAGE_KEY, bumpSessionsRevision, readActiveSessionId, writeActiveSessionId } from './services/sessionSync';

import { Settings } from 'lucide-react';

const ipcRenderer = window.veraDesktop || null;

const apiToken = ipcRenderer ? ipcRenderer.getApiToken() : '';

type VeraThemeId = 'obsidian' | 'daylight' | 'terminal' | 'sakura' | 'graphite' | 'aurora';

const VERA_THEMES: Array<{
    id: VeraThemeId;
    name: string;
    description: string;
    mode: 'dark' | 'light';
    swatches: string[];
}> = [
        { id: 'obsidian', name: 'Обсидиан', description: 'Темное стекло', mode: 'dark', swatches: ['#101114', '#1c2430', '#67d4ff'] },
        { id: 'daylight', name: 'Дневной', description: 'Чистый фокус', mode: 'light', swatches: ['#f7f8fb', '#ffffff', '#2563eb'] },
        { id: 'terminal', name: 'Терминал', description: 'Минимум шума', mode: 'dark', swatches: ['#020403', '#07110c', '#44ff8a'] },
        { id: 'sakura', name: 'Сакура', description: 'Теплый свет', mode: 'light', swatches: ['#fff7fa', '#ffffff', '#d9467f'] },
        { id: 'graphite', name: 'Графит', description: 'Спокойная сталь', mode: 'dark', swatches: ['#17191d', '#22272e', '#f59f5a'] },
        { id: 'aurora', name: 'Аврора', description: 'Холодное сияние', mode: 'dark', swatches: ['#08151a', '#12343d', '#5eead4'] },
    ];

const THEME_STORAGE_KEY = 'vera_theme';
const RUNTIME_MODEL_STORAGE_KEY = 'vera_runtime_model_name';
const WORKSPACE_DIRECTORY_STORAGE_KEY = 'vera_workspace_directory';
const WORKSPACE_FILE_DRAG_TYPE = 'application/x-vera-workspace-file';

type WorkspacePanelMode = 'files' | 'terminal';

type WorkspaceEntry = {
    name: string;
    path: string;
    isDirectory: boolean;
    size: number;
};

type ProjectEntry = {
    name: string;
    path: string;
    size: number;
    updatedAt: number;
};

type SkillEntry = {
    name: string;
    title: string;
    description: string;
    allowed_tools: string[];
    source: 'builtin' | 'user';
    activation: string;
    model_profile: string;
};

const TOOL_ACTIVITY_LABELS: Record<string, string> = {
    web_search: 'Ищет в интернете',
    create_presentation: 'Создаёт презентацию',
    create_document: 'Создаёт документ',
    code_interpreter: 'Выполняет код',
    read_document: 'Читает документ',
    telegram: 'Работает с Telegram',
    open_app: 'Открывает приложение',
    close_app: 'Закрывает приложение',
    manage_files: 'Работает с файлами',
};

function getToolActivityLabel(toolName: string): string {
    return TOOL_ACTIVITY_LABELS[toolName] || `Выполняет: ${toolName.replace(/_/g, ' ')}`;
}

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

    const docPathRe = /(Презентация создана|Документ сохранен|Документ сохранён|Файл создан):\s*([A-Z]:\\.*?\.(?:pptx|docx|xlsx|pdf|txt|md|csv|json))/i;
    const docMatch = docPathRe.exec(cleanText)
        || /(?:Markdown создан|Документ Word создан|Excel таблица создана):\s*([A-Z]:\\.*?\.(?:docx|xlsx|txt|md))/i.exec(cleanText);
    if (docMatch) {
        docPath = (docMatch[2] || docMatch[1]).trim();
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

function getImageMimeType(fileName: string): string {
    const extension = fileName.split('.').pop()?.toLowerCase();
    const imageTypes: Record<string, string> = {
        avif: 'image/avif',
        bmp: 'image/bmp',
        gif: 'image/gif',
        heic: 'image/heic',
        heif: 'image/heif',
        jpeg: 'image/jpeg',
        jpg: 'image/jpeg',
        png: 'image/png',
        svg: 'image/svg+xml',
        webp: 'image/webp',
    };
    return extension ? imageTypes[extension] || '' : '';
}

function isImageFile(file: File): boolean {
    return file.type.startsWith('image/') || Boolean(getImageMimeType(file.name));
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
                                if (href && ipcRenderer) {
                                    e.preventDefault();
                                    void ipcRenderer.openExternal(href);
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

function ThinkingBlock({ thoughts, isLightMode }: { thoughts: string; isLightMode: boolean }) {
    const [isExpanded, setIsExpanded] = useState(false);
    const cleanThoughts = thoughts.trim();
    if (!cleanThoughts) return null;

    return (
        <div className={`thinking-card ${isLightMode ? 'light' : ''}`}>
            <button
                type="button"
                onClick={(e) => {
                    e.stopPropagation();
                    setIsExpanded(!isExpanded);
                }}
                className="thinking-card-toggle"
                aria-expanded={isExpanded}
            >
                <span className="thinking-card-icon">
                    <Brain size={13} />
                </span>
                <span className="thinking-card-title">Ход мысли</span>
                {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {isExpanded && (
                <div className="thinking-card-content">
                    {cleanThoughts}
                </div>
            )}
        </div>
    );
}

function SettingsToggle({
    checked,
    onChange,
    label,
    description,
}: {
    checked: boolean;
    onChange: (checked: boolean) => void;
    label: string;
    description?: string;
}) {
    return (
        <button
            type="button"
            role="switch"
            aria-checked={checked}
            onClick={() => onChange(!checked)}
            className={`settings-toggle-row ${checked ? 'active' : ''}`}
        >
            <span className="settings-toggle-copy">
                <strong>{label}</strong>
                {description && <span>{description}</span>}
            </span>
            <span className="settings-switch" aria-hidden="true">
                <span className="settings-switch-thumb" />
            </span>
        </button>
    );
}

function SettingsModal({
    isOpen,
    onClose,
    currentThemeId,
    onThemeChange,
    initialSection,
}: {
    isOpen: boolean;
    onClose: () => void;
    currentThemeId: VeraThemeId;
    onThemeChange: (themeId: VeraThemeId) => void;
    initialSection?: string;
}) {
    const [config, setConfig] = useState<any>(null);
    const [tasks, setTasks] = useState<any[]>([]);
    const [memory, setMemory] = useState<MemoryPayload | null>(null);
    const [profileDrafts, setProfileDrafts] = useState<Record<string, string>>({});
    const [memorySearch, setMemorySearch] = useState('');
    const [memoryCategory, setMemoryCategory] = useState('all');
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState('');
    const [activeSettingsSection, setActiveSettingsSection] = useState('appearance');

    const settingsSections = [
        { id: 'appearance', label: 'Оформление', icon: Palette },
        { id: 'memory', label: 'Память', icon: Database },
        { id: 'general', label: 'Общие', icon: SlidersHorizontal },
        { id: 'model', label: 'Модель', icon: Cpu },
        { id: 'voice', label: 'Голос', icon: Volume2 },
        { id: 'web', label: 'Веб-поиск', icon: Globe2 },
        { id: 'automation', label: 'Автоматизация', icon: Clock3 },
    ];

    const goToSettingsSection = (sectionId: string) => {
        setActiveSettingsSection(sectionId);
        document.getElementById(`settings-${sectionId}`)?.scrollIntoView({
            behavior: 'smooth',
            block: 'start',
        });
    };

    useEffect(() => {
        if (isOpen) {
            setActiveSettingsSection(initialSection || 'appearance');
            setMessage('');
            Promise.all([
                veraFetch('http://127.0.0.1:8000/api/config').then(res => res.json()),
                veraFetch('http://127.0.0.1:8000/api/heartbeat-tasks').then(res => res.json()),
                veraFetch('http://127.0.0.1:8000/api/memory').then(res => res.json())
            ])
                .then(([cfgData, tasksData, memoryData]) => {
                    const normalizedConfig = {
                        ...cfgData,
                        model: {
                            ...(cfgData?.model || {}),
                            thinking_budget_tokens: Math.max(
                                0,
                                Math.min(32768, Number(cfgData?.model?.thinking_budget_tokens ?? 1024)),
                            ),
                        },
                    };
                    setConfig(normalizedConfig);
                    setTasks(Array.isArray(tasksData) ? tasksData : []);
                    setMemory({
                        profile: memoryData?.profile || {},
                        facts: Array.isArray(memoryData?.facts) ? memoryData.facts : [],
                        categories: Array.isArray(memoryData?.categories) ? memoryData.categories : [],
                    });
                    setProfileDrafts(memoryData?.profile || {});
                })
                .catch(err => setMessage('Ошибка загрузки настроек: ' + err.message));
            window.setTimeout(() => {
                document.getElementById(`settings-${initialSection || 'appearance'}`)?.scrollIntoView({
                    block: 'start',
                });
            }, 0);
        }
    }, [initialSection, isOpen]);

    if (!isOpen) return null;

    const handleSave = async () => {
        const numericDrafts = [
            config?.silence_timeout,
            config?.model?.ctx_size,
            config?.model?.temperature,
            config?.model?.top_p,
            config?.model?.thinking_budget_tokens,
            config?.tts?.volume,
            config?.tts?.speed,
            config?.tts?.total_steps,
            config?.web_search?.total_context_limit,
        ];
        if (numericDrafts.includes('')) {
            setMessage('Заполните очищенные числовые поля.');
            return;
        }
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
            if (value === '') {
                val = '';
            } else {
                const parsed = type === 'number' ? Number.parseInt(value, 10) : Number.parseFloat(value);
                val = Number.isFinite(parsed) ? parsed : value;
            }
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
    const ttsVolumePercent = Math.round(
        Math.max(0, Math.min(100, Number(config?.tts?.volume ?? 50))),
    );

    const handleTtsVolumePercent = (value: number) => {
        const percent = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
        handleChange('tts', 'volume', Math.round(percent), 'number');
        handleChange('tts', 'volume_scale', 'percent_v2', 'string');
    };



    return (
        <div className="settings-overlay absolute inset-0 z-50 flex items-center justify-center bg-black/55 p-4 text-[var(--vera-text)]">
            <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                className="vera-settings w-full max-w-5xl max-h-[92vh] rounded-2xl border shadow-2xl flex flex-col overflow-hidden"
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

                <div className="settings-layout min-h-0 flex-1 no-drag-region">
                    <aside className="settings-nav">
                        <div className="settings-nav-label">Настройки Vera</div>
                        {settingsSections.map(({ id, label, icon: Icon }) => (
                            <button
                                key={id}
                                type="button"
                                onClick={() => goToSettingsSection(id)}
                                className={`settings-nav-item ${activeSettingsSection === id ? 'active' : ''}`}
                            >
                                <Icon size={16} />
                                <span>{label}</span>
                            </button>
                        ))}
                    </aside>

                    {/* Body (Scrollable fields) */}
                    <div className="settings-content flex-1 overflow-y-auto p-6 space-y-8">
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
                            <section id="settings-appearance" className="settings-anchor">
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
                                                {currentThemeId === theme.id && (
                                                    <span className="theme-selected-label">Выбрано</span>
                                                )}
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

                            <section id="settings-memory" className="settings-anchor">
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
                                    <div className="settings-select-shell">
                                        <select
                                            value={memoryCategory}
                                            onChange={e => setMemoryCategory(e.target.value)}
                                            className="memory-category-select"
                                            aria-label="Категория памяти"
                                        >
                                            <option value="all">Все категории</option>
                                            {(memory?.categories || []).map(category => (
                                                <option key={category} value={category}>{getCategoryLabel(category)}</option>
                                            ))}
                                        </select>
                                    </div>
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
                            <section id="settings-general" className="settings-anchor">
                                <h3 className="settings-section-title">Общие</h3>
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
                                            value={config.silence_timeout ?? 0}
                                            onChange={e => handleChange('', 'silence_timeout', e.target.value, 'number')}
                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                        />
                                    </div>
                                </div>
                            </section>

                            <div className="h-px bg-white/5 w-full" />

                            {/* LLM Model */}
                            <section id="settings-model" className="settings-anchor">
                                <h3 className="settings-section-title">Модель (LLM)</h3>
                                <div className="space-y-4">
                                    <div>
                                        <label className="block text-sm opacity-80 mb-1">Размер контекста</label>
                                        <input
                                            type="number"
                                            value={config.model?.ctx_size ?? 0}
                                            onChange={e => handleChange('model', 'ctx_size', e.target.value, 'number')}
                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                        />
                                    </div>
                                    <div className="grid grid-cols-2 gap-4">
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">Temperature</label>
                                            <input
                                                type="number" step="0.1"
                                                value={config.model?.temperature ?? 0}
                                                onChange={e => handleChange('model', 'temperature', e.target.value, 'float')}
                                                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                            />
                                        </div>
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">Top_p</label>
                                            <input
                                                type="number" step="0.05"
                                                value={config.model?.top_p ?? 0}
                                                onChange={e => handleChange('model', 'top_p', e.target.value, 'float')}
                                                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                            />
                                        </div>
                                    </div>
                                    <div className="space-y-3 pt-1 border-t border-white/5">
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">
                                                Бюджет размышления
                                            </label>
                                            <div className="flex items-center gap-2">
                                                <input
                                                    type="range"
                                                    min="0"
                                                    max="32768"
                                                    step="64"
                                                    value={Math.max(0, config.model?.thinking_budget_tokens ?? 1024)}
                                                    onChange={e => handleChange('model', 'thinking_budget_tokens', e.target.value, 'number')}
                                                    className="flex-1 accent-blue-500"
                                                />
                                                <input
                                                    type="number"
                                                    min="0"
                                                    max="32768"
                                                    value={Math.max(0, config.model?.thinking_budget_tokens ?? 1024)}
                                                    onChange={e => handleChange('model', 'thinking_budget_tokens', e.target.value, 'number')}
                                                    className="w-24 bg-black/30 border border-white/10 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-white/30"
                                                />
                                            </div>
                                            <p className="text-[10px] opacity-40 mt-1">
                                                От 0 до 32 768 токенов. 0 отключает размышление.
                                            </p>
                                        </div>

                                    </div>
                                    <div className="pt-2 border-t border-white/5 space-y-4">
                                        <SettingsToggle
                                            checked={config.model?.use_external_server || false}
                                            onChange={checked => handleChange('model', 'use_external_server', checked, 'boolean')}
                                            label="Внешний LLM-сервер"
                                            description="Ollama, LM Studio или другой OpenAI-совместимый API"
                                        />
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

                            <section id="settings-voice" className="settings-anchor">
                                <h3 className="settings-section-title">Озвучивание</h3>
                                <div className="space-y-4">
                                    <div className="tts-volume-card">
                                        <div className="tts-volume-header">
                                            <div>
                                                <strong>Громкость голоса</strong>
                                                <span>Уровень озвучивания ответов Веры</span>
                                            </div>
                                            <div className="tts-volume-value">
                                                <input
                                                    type="number"
                                                    min="0"
                                                    max="100"
                                                    step="1"
                                                    value={ttsVolumePercent}
                                                    onChange={e => handleTtsVolumePercent(Number(e.target.value))}
                                                    aria-label="Громкость голоса в процентах"
                                                />
                                                <span>%</span>
                                            </div>
                                        </div>
                                        <div className="tts-volume-slider-row">
                                            <Volume2 size={18} />
                                            <input
                                                type="range"
                                                min="0"
                                                max="100"
                                                step="1"
                                                value={ttsVolumePercent}
                                                onChange={e => handleTtsVolumePercent(Number(e.target.value))}
                                                className="tts-volume-slider"
                                                style={{ '--tts-volume': `${ttsVolumePercent}%` } as React.CSSProperties}
                                            />
                                        </div>
                                        <div className="tts-volume-presets">
                                            {[
                                                { label: 'Тихо', value: 25 },
                                                { label: 'Обычно', value: 50 },
                                                { label: 'Громко', value: 70 },
                                            ].map(preset => (
                                                <button
                                                    key={preset.value}
                                                    type="button"
                                                    onClick={() => handleTtsVolumePercent(preset.value)}
                                                    className={Math.abs(ttsVolumePercent - preset.value) <= 2 ? 'active' : ''}
                                                >
                                                    {preset.label}
                                                </button>
                                            ))}
                                        </div>
                                        <p className="tts-volume-note">
                                            Рекомендуемый уровень: 40–60%. Даже на 100% защита от перегруза остаётся включённой.
                                        </p>
                                    </div>
                                    <div className="grid grid-cols-2 gap-4">
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">Скорость речи</label>
                                            <input
                                                type="number" min="0.5" max="2" step="0.05"
                                                value={config.tts?.speed ?? 1.15}
                                                onChange={e => handleChange('tts', 'speed', e.target.value, 'float')}
                                                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                            />
                                        </div>
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">Голос</label>
                                            <div className="settings-select-shell">
                                                <select
                                                    value={config.tts?.voice_name || 'Lily'}
                                                    onChange={e => handleChange('tts', 'voice_name', e.target.value, 'string')}
                                                    className="settings-select-control"
                                                >
                                                    <option value="Lily">Вера · рекомендуется</option>
                                                    <option value="F1">Алиса · женский</option>
                                                    <option value="F2">Мира · женский</option>
                                                    <option value="F3">София · женский</option>
                                                    <option value="F4">Ника · женский</option>
                                                    <option value="F5">Ева · женский</option>
                                                    <option value="M1">Максим · мужской</option>
                                                    <option value="M2">Илья · мужской</option>
                                                    <option value="M3">Даниил · мужской</option>
                                                    <option value="M4">Кирилл · мужской</option>
                                                    <option value="M5">Роман · мужской</option>
                                                </select>
                                            </div>
                                        </div>
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">Качество синтеза</label>
                                            <input
                                                type="number" min="1" max="10"
                                                value={config.tts?.total_steps ?? 4}
                                                onChange={e => handleChange('tts', 'total_steps', e.target.value, 'number')}
                                                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                            />
                                        </div>
                                    </div>
                                </div>
                            </section>

                            <div className="h-px bg-white/5 w-full" />

                            {/* Web Search */}
                            <section id="settings-web" className="settings-anchor">
                                <h3 className="settings-section-title">Веб-поиск</h3>
                                <div className="space-y-4">
                                    <div>
                                        <label className="block text-sm opacity-80 mb-1">Лимит контекста поиска</label>
                                        <input
                                            type="number"
                                            value={config.web_search?.total_context_limit ?? 0}
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
                                    <h3 className="settings-section-title mb-0">Сайты</h3>
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
                                        <div key={idx} className="settings-site-row">
                                            <input
                                                type="text"
                                                value={key}
                                                placeholder="Активационное слово"
                                                onChange={e => handleSiteChange(key, e.target.value, value as string, true)}
                                                className="settings-site-name"
                                            />
                                            <input
                                                type="text"
                                                value={value as string}
                                                placeholder="https://..."
                                                onChange={e => handleSiteChange(key, key, e.target.value, false)}
                                                className="settings-site-url"
                                            />
                                            <button
                                                type="button"
                                                onClick={() => handleRemoveSite(key)}
                                                className="settings-site-remove"
                                                aria-label={`Удалить сайт ${key}`}
                                                title="Удалить сайт"
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
                            <section id="settings-automation" className="settings-anchor">
                                <div className="flex items-center justify-between mb-4">
                                    <h3 className="settings-section-title mb-0">Периодические задачи</h3>
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
                                        <div key={idx} className={`settings-task-card ${task.enabled ? 'active' : ''}`}>
                                            <div className="flex items-center justify-between gap-2">
                                                <input
                                                    type="text"
                                                    value={task.task_text}
                                                    onChange={e => handleTaskChange(idx, 'task_text', e.target.value)}
                                                    className="flex-1 bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                                    placeholder="Текст задачи (например, выпей воду)"
                                                />
                                                <div className="flex items-center gap-2">
                                                    <button
                                                        type="button"
                                                        role="switch"
                                                        aria-checked={task.enabled}
                                                        onClick={() => handleTaskChange(idx, 'enabled', !task.enabled)}
                                                        className={`settings-switch compact ${task.enabled ? 'active' : ''}`}
                                                        title={task.enabled ? 'Отключить задачу' : 'Включить задачу'}
                                                    >
                                                        <span className="settings-switch-thumb" />
                                                    </button>
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
                                                <div className="settings-select-shell compact">
                                                    <select
                                                        value={task.recurring}
                                                        onChange={e => handleTaskChange(idx, 'recurring', e.target.value)}
                                                        className="settings-select-control"
                                                    >
                                                        <option value="once">Один раз</option>
                                                        <option value="daily">Ежедневно</option>
                                                        <option value="weekdays">По будням</option>
                                                        <option value="weekends">По выходным</option>
                                                        <option value="interval">С интервалом</option>
                                                    </select>
                                                </div>

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
                </div>

                {/* Footer */}
                <div className="settings-footer no-drag-region">
                    <div className="text-sm text-green-400 font-medium px-2">
                        {message}
                    </div>
                    <div className="flex gap-2">
                        <button onClick={onClose} className="settings-footer-button secondary">
                            Отмена
                        </button>
                        <button
                            onClick={handleSave}
                            disabled={loading || !config}
                            className="settings-footer-button primary"
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
    imagePreview?: string;
    streaming?: boolean;
}

interface LogEntry {
    id: number;
    time: string;
    level: 'info' | 'success' | 'error';
    text: string;
    detail?: string;
}

interface RuntimeInfo {
    version: string;
    model_name: string;
    model_path?: string;
}

function SourceChips({ sources }: { sources: string[] }) {
    if (!sources.length) return null;

    return (
        <div className="source-chip-wrap">
            {sources.map((url, i) => (
                <button
                    key={url}
                    onClick={() => void ipcRenderer?.openExternal(url)}
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

function EmptyChatStage({ isLightMode }: { isLightMode: boolean }) {
    return (
        <div className={`chat-empty-stage ${isLightMode ? 'light' : ''}`}>
            <div className="chat-empty-copy">
                <h1>VERA AGENT</h1>
                <p>Отправьте задачу, файл или идею. Vera будет работать с вашим компьютером и локальными инструментами.</p>
            </div>
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
    if (msg.role === 'user') {
        return (
            <div className="user-message-stack">
                {msg.imagePreview && (
                    <img
                        src={msg.imagePreview}
                        alt={msg.file || 'Прикреплённое изображение'}
                        className="user-message-image"
                    />
                )}
                {msg.file && !msg.imagePreview && (
                    <div className={`user-message-file ${isLightMode ? 'light' : ''}`}>
                        <div className="user-message-file-icon">
                            <FileText size={18} />
                        </div>
                        <div className="attachment-body">
                            <div className="attachment-name" title={msg.file}>{msg.file}</div>
                            <div className="attachment-meta-line">
                                <span className="attachment-badge">{getFileExtension(msg.file)}</span>
                                {msg.fileSize ? <span>{formatFileSize(msg.fileSize)}</span> : null}
                            </div>
                        </div>
                    </div>
                )}
                {msg.text && (
                    <div className={`user-message-text ${isLightMode ? 'light' : ''}`}>
                        {msg.text}
                    </div>
                )}
            </div>
        );
    }

    return (
        <div
            className={`message-bubble role-${msg.role} max-w-[85%] rounded-2xl px-4 py-3 text-[15px] leading-relaxed relative select-text cursor-text ${msg.role === 'user'
                ? (isLightMode ? 'bg-[#e5e7eb] text-gray-900 font-medium shadow-sm border border-gray-300' : 'bg-white/10 text-white font-medium border border-white/10')
                : msg.role === 'system'
                    ? (isLightMode ? 'bg-black/5 text-gray-500 text-sm border border-gray-200 indent-0 italic' : 'bg-white/5 text-white/50 text-sm border border-white/5 italic')
                    : (isLightMode ? 'bg-[#ffffff] text-gray-800 border border-gray-200 shadow-sm' : 'bg-white/5 text-gray-200 border border-white/10')
                }`}
        >
            {msg.role === 'system' ? (
                <>
                    {msg.text && <div>{msg.text}</div>}
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
                                    onClick={async () => {
                                        try {
                                            if (!ipcRenderer) throw new Error('Electron IPC unavailable');
                                            await ipcRenderer.invoke('workspace-reveal-item', docPath);
                                        } catch (error) {
                                            window.alert(
                                                `Не удалось открыть папку: ${
                                                    error instanceof Error ? error.message : String(error)
                                                }`,
                                            );
                                        }
                                    }}
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

function WorkspaceTreeRow({
    entry,
    depth,
    expandedPaths,
    directoryChildren,
    loadingPaths,
    onToggleDirectory,
    onOpenFile,
}: {
    entry: WorkspaceEntry;
    depth: number;
    expandedPaths: Set<string>;
    directoryChildren: Record<string, WorkspaceEntry[]>;
    loadingPaths: Set<string>;
    onToggleDirectory: (entry: WorkspaceEntry) => void;
    onOpenFile: (entry: WorkspaceEntry) => void;
}) {
    const isExpanded = entry.isDirectory && expandedPaths.has(entry.path);
    const isLoading = loadingPaths.has(entry.path);

    const handleDragStart = (event: React.DragEvent<HTMLButtonElement>) => {
        if (entry.isDirectory) {
            event.preventDefault();
            return;
        }
        event.dataTransfer.effectAllowed = 'copy';
        event.dataTransfer.setData(WORKSPACE_FILE_DRAG_TYPE, entry.path);
        event.dataTransfer.setData('text/plain', entry.path);
    };

    return (
        <>
            <button
                type="button"
                className={`workspace-tree-row ${entry.isDirectory ? 'is-directory' : 'is-file'}`}
                style={{ paddingLeft: `${8 + depth * 15}px` }}
                draggable={!entry.isDirectory}
                onDragStart={handleDragStart}
                onClick={() => entry.isDirectory && onToggleDirectory(entry)}
                onDoubleClick={() => !entry.isDirectory && onOpenFile(entry)}
                title={entry.path}
            >
                <span className="workspace-tree-chevron">
                    {entry.isDirectory && (
                        isLoading
                            ? <RefreshCw size={12} className="workspace-spin" />
                            : isExpanded
                                ? <ChevronDown size={12} />
                                : <ChevronRight size={12} />
                    )}
                </span>
                {entry.isDirectory ? <Folder size={14} /> : <FileIcon size={14} />}
                <span className="workspace-tree-name">{entry.name}</span>
            </button>
            {isExpanded && (directoryChildren[entry.path] || []).map(child => (
                <WorkspaceTreeRow
                    key={child.path}
                    entry={child}
                    depth={depth + 1}
                    expandedPaths={expandedPaths}
                    directoryChildren={directoryChildren}
                    loadingPaths={loadingPaths}
                    onToggleDirectory={onToggleDirectory}
                    onOpenFile={onOpenFile}
                />
            ))}
        </>
    );
}

function WorkspacePanel({
    mode,
    onModeChange,
}: {
    mode: WorkspacePanelMode;
    onModeChange: (mode: WorkspacePanelMode) => void;
}) {
    const [rootPath, setRootPath] = useState(() => localStorage.getItem(WORKSPACE_DIRECTORY_STORAGE_KEY) || '');
    const [rootEntries, setRootEntries] = useState<WorkspaceEntry[]>([]);
    const [directoryChildren, setDirectoryChildren] = useState<Record<string, WorkspaceEntry[]>>({});
    const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
    const [loadingPaths, setLoadingPaths] = useState<Set<string>>(new Set());
    const [fileError, setFileError] = useState('');
    const [terminalOutput, setTerminalOutput] = useState('');
    const [terminalInput, setTerminalInput] = useState('');
    const [terminalRunning, setTerminalRunning] = useState(false);
    const terminalEndRef = useRef<HTMLDivElement | null>(null);
    const terminalInputRef = useRef<HTMLInputElement | null>(null);
    const terminalStartedRef = useRef(false);

    const loadDirectory = useCallback(async (directoryPath: string) => {
        if (!ipcRenderer || !directoryPath) return [];
        return await ipcRenderer.invoke('workspace-list-directory', directoryPath) as WorkspaceEntry[];
    }, []);

    const refreshRoot = useCallback(async () => {
        if (!rootPath) return;
        setFileError('');
        setLoadingPaths(previous => new Set(previous).add(rootPath));
        try {
            const entries = await loadDirectory(rootPath);
            setRootEntries(entries);
            setDirectoryChildren({});
            setExpandedPaths(new Set());
        } catch (error) {
            setFileError(error instanceof Error ? error.message : 'Не удалось прочитать папку');
        } finally {
            setLoadingPaths(previous => {
                const next = new Set(previous);
                next.delete(rootPath);
                return next;
            });
        }
    }, [loadDirectory, rootPath]);

    useEffect(() => {
        if (rootPath) {
            refreshRoot();
        }
    }, [refreshRoot, rootPath]);

    useEffect(() => {
        if (!ipcRenderer) return;
        const handleOutput = (_event: unknown, chunk: string) => {
            setTerminalOutput(previous => `${previous}${chunk}`.slice(-100000));
        };
        const handleExit = (_event: unknown, payload: { code?: number }) => {
            setTerminalRunning(false);
            setTerminalOutput(previous => `${previous}\r\n[CMD завершён: ${payload?.code ?? 0}]\r\n`);
        };
        ipcRenderer.on('terminal-output', handleOutput);
        ipcRenderer.on('terminal-exit', handleExit);
        return () => {
            ipcRenderer.removeListener('terminal-output', handleOutput);
            ipcRenderer.removeListener('terminal-exit', handleExit);
            ipcRenderer.send('terminal-stop');
        };
    }, []);

    useEffect(() => {
        if (mode !== 'terminal' || !ipcRenderer || terminalRunning || terminalStartedRef.current) return;
        terminalStartedRef.current = true;
        ipcRenderer.invoke<{ cwd?: string }>('terminal-start')
            .then(result => {
                setTerminalRunning(true);
                setTerminalOutput(previous => previous || `CMD · ${result?.cwd || ''}\r\n`);
            })
            .catch((error: Error) => {
                terminalStartedRef.current = false;
                setTerminalOutput(previous => `${previous}[Не удалось запустить CMD] ${error.message}\r\n`);
            });
    }, [mode, terminalRunning]);

    useEffect(() => {
        terminalEndRef.current?.scrollIntoView({ block: 'end' });
    }, [terminalOutput]);

    useEffect(() => {
        if (mode === 'terminal') {
            window.setTimeout(() => terminalInputRef.current?.focus(), 0);
        }
    }, [mode]);

    const chooseDirectory = async () => {
        if (!ipcRenderer) return;
        const selectedPath = await ipcRenderer.invoke('workspace-select-directory') as string | null;
        if (!selectedPath) return;
        localStorage.setItem(WORKSPACE_DIRECTORY_STORAGE_KEY, selectedPath);
        setRootPath(selectedPath);
    };

    const toggleDirectory = async (entry: WorkspaceEntry) => {
        if (expandedPaths.has(entry.path)) {
            setExpandedPaths(previous => {
                const next = new Set(previous);
                next.delete(entry.path);
                return next;
            });
            return;
        }
        if (!directoryChildren[entry.path]) {
            setLoadingPaths(previous => new Set(previous).add(entry.path));
            try {
                const entries = await loadDirectory(entry.path);
                setDirectoryChildren(previous => ({ ...previous, [entry.path]: entries }));
            } catch (error) {
                setFileError(error instanceof Error ? error.message : 'Не удалось прочитать папку');
                return;
            } finally {
                setLoadingPaths(previous => {
                    const next = new Set(previous);
                    next.delete(entry.path);
                    return next;
                });
            }
        }
        setExpandedPaths(previous => new Set(previous).add(entry.path));
    };

    const openFile = async (entry: WorkspaceEntry) => {
        if (!ipcRenderer) return;
        try {
            await ipcRenderer.invoke('workspace-open-file', entry.path);
        } catch (error) {
            setFileError(error instanceof Error ? error.message : 'Не удалось открыть файл');
        }
    };

    const submitTerminalCommand = () => {
        const command = terminalInput.trim();
        if (!command || !ipcRenderer) return;
        setTerminalOutput(previous => `${previous}> ${command}\r\n`);
        ipcRenderer.send('terminal-input', `${command}\r\n`);
        setTerminalInput('');
    };

    const rootName = rootPath.split(/[\\/]/).filter(Boolean).pop() || rootPath;

    return (
        <aside className="workspace-panel no-drag-region">
            <div className="workspace-panel-tabs">
                <button type="button" className={mode === 'files' ? 'active' : ''} onClick={() => onModeChange('files')} title="Файлы">
                    <FolderOpen size={16} />
                </button>
                <button type="button" className={mode === 'terminal' ? 'active' : ''} onClick={() => onModeChange('terminal')} title="CMD">
                    <TerminalSquare size={16} />
                </button>
            </div>

            {mode === 'files' ? (
                <div className="workspace-files-view">
                    <div className="workspace-panel-heading">
                        <div>
                            <span className="workspace-heading-mark">▦</span>
                            <strong>{rootName || 'ФАЙЛЫ'}</strong>
                        </div>
                        <div className="workspace-heading-actions">
                            {rootPath && (
                                <>
                                    <button type="button" onClick={refreshRoot} title="Обновить">
                                        <RefreshCw size={14} />
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => ipcRenderer?.invoke('workspace-open-file', rootPath)}
                                        title="Открыть в проводнике"
                                    >
                                        <ExternalLink size={14} />
                                    </button>
                                </>
                            )}
                            <button type="button" onClick={chooseDirectory} title="Выбрать папку">
                                <FolderOpen size={14} />
                            </button>
                        </div>
                    </div>
                    {!rootPath && (
                        <button type="button" className="workspace-select-directory" onClick={chooseDirectory}>
                            <FolderOpen size={18} />
                            <span>Выбрать папку</span>
                        </button>
                    )}
                    {fileError && <div className="workspace-panel-error">{fileError}</div>}
                    <div className="workspace-tree">
                        {rootEntries.map(entry => (
                            <WorkspaceTreeRow
                                key={entry.path}
                                entry={entry}
                                depth={0}
                                expandedPaths={expandedPaths}
                                directoryChildren={directoryChildren}
                                loadingPaths={loadingPaths}
                                onToggleDirectory={toggleDirectory}
                                onOpenFile={openFile}
                            />
                        ))}
                    </div>
                    {rootPath && <div className="workspace-files-hint">Перетащите файл в чат или откройте двойным щелчком</div>}
                </div>
            ) : (
                <div className="workspace-terminal-view">
                    <div className="workspace-panel-heading">
                        <div>
                            <span className="workspace-heading-mark">▦</span>
                            <strong>CMD</strong>
                        </div>
                        <button type="button" onClick={() => setTerminalOutput('')} title="Очистить">Очистить</button>
                    </div>
                    <div
                        className="workspace-terminal-output"
                        onClick={() => terminalInputRef.current?.focus()}
                        role="textbox"
                        tabIndex={0}
                        aria-label="Терминал CMD"
                    >
                        <pre>{terminalOutput || 'Запуск CMD...'}</pre>
                        <div className="workspace-terminal-live-prompt">
                            <span>&gt;</span>
                            <span>{terminalInput}</span>
                            <i />
                        </div>
                        <input
                            ref={terminalInputRef}
                            className="workspace-terminal-capture"
                            value={terminalInput}
                            onChange={event => setTerminalInput(event.target.value)}
                            onKeyDown={event => {
                                if (event.key === 'Enter') {
                                    event.preventDefault();
                                    submitTerminalCommand();
                                }
                                if (event.key.toLowerCase() === 'c' && event.ctrlKey && ipcRenderer) {
                                    event.preventDefault();
                                    ipcRenderer.send('terminal-input', '\u0003');
                                }
                            }}
                            autoComplete="off"
                            spellCheck={false}
                            aria-label="Ввод команды"
                        />
                        <div ref={terminalEndRef} />
                    </div>
                </div>
            )}
        </aside>
    );
}

function ProjectsView({ onClose }: { onClose: () => void }) {
    const [projects, setProjects] = useState<ProjectEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [deletingPath, setDeletingPath] = useState<string | null>(null);

    const refresh = useCallback(async () => {
        if (!ipcRenderer) return;
        setLoading(true);
        setError('');
        try {
            setProjects(await ipcRenderer.invoke('projects-list') as ProjectEntry[]);
        } catch (loadError) {
            setError(loadError instanceof Error ? loadError.message : 'Не удалось загрузить проекты');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        refresh();
    }, [refresh]);

    const trashProject = useCallback(async (project: ProjectEntry) => {
        if (!ipcRenderer || !window.confirm(`Переместить «${project.name}» в корзину?`)) return;
        setDeletingPath(project.path);
        setError('');
        try {
            await ipcRenderer.invoke('projects-trash', project.path);
            setProjects(current => current.filter(item => item.path !== project.path));
        } catch (deleteError) {
            setError(deleteError instanceof Error ? deleteError.message : 'Не удалось удалить проект');
        } finally {
            setDeletingPath(null);
        }
    }, []);

    return (
        <section className="projects-view no-drag-region">
            <div className="projects-header">
                <div>
                    <h2>Проекты</h2>
                    <span>Созданные презентации</span>
                </div>
                <div className="projects-header-actions">
                    <button type="button" onClick={refresh} title="Обновить"><RefreshCw size={15} /></button>
                    <button type="button" onClick={onClose} title="Закрыть"><X size={16} /></button>
                </div>
            </div>
            {error && <div className="workspace-panel-error">{error}</div>}
            {loading ? (
                <div className="projects-empty">Загрузка проектов...</div>
            ) : projects.length === 0 ? (
                <div className="projects-empty">
                    <FileStack size={28} />
                    <strong>Проектов пока нет</strong>
                    <span>Созданные презентации появятся здесь автоматически.</span>
                </div>
            ) : (
                <div className="projects-grid">
                    {projects.map(project => (
                        <article className="project-card" key={project.path}>
                            <div className="project-card-icon"><FileStack size={20} /></div>
                            <div className="project-card-copy">
                                <strong title={project.name}>{project.name.replace(/\.pptx$/i, '')}</strong>
                                <span>{formatFileSize(project.size)} · {new Date(project.updatedAt).toLocaleString('ru-RU')}</span>
                            </div>
                            <div className="project-card-actions">
                                <button type="button" onClick={() => ipcRenderer?.invoke('workspace-open-file', project.path)}>
                                    Открыть
                                </button>
                                <button type="button" onClick={() => ipcRenderer?.invoke('workspace-reveal-item', project.path)}>
                                    В проводнике
                                </button>
                                <button
                                    type="button"
                                    className="danger"
                                    disabled={deletingPath === project.path}
                                    onClick={() => void trashProject(project)}
                                >
                                    <Trash2 size={12} />
                                    {deletingPath === project.path ? 'Удаление...' : 'Удалить'}
                                </button>
                            </div>
                        </article>
                    ))}
                </div>
            )}
        </section>
    );
}

function SkillsView({ onClose }: { onClose: () => void }) {
    const [skills, setSkills] = useState<SkillEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const refresh = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const response = await veraFetch('http://127.0.0.1:8000/api/skills');
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload?.error || `HTTP ${response.status}`);
            }
            setSkills(Array.isArray(payload?.skills) ? payload.skills : []);
        } catch (loadError) {
            setError(loadError instanceof Error ? loadError.message : 'Не удалось загрузить skills');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void refresh();
    }, [refresh]);

    return (
        <section className="skills-view no-drag-region">
            <div className="skills-header">
                <div>
                    <h2>Skills</h2>
                    <span>{loading ? 'Загрузка...' : `${skills.length} установлено`}</span>
                </div>
                <div className="skills-header-actions">
                    <button type="button" onClick={() => void refresh()} title="Обновить"><RefreshCw size={15} /></button>
                    <button type="button" onClick={onClose} title="Закрыть"><X size={16} /></button>
                </div>
            </div>
            {error && <div className="workspace-panel-error">{error}</div>}
            {loading ? (
                <div className="skills-empty">Загрузка skills...</div>
            ) : skills.length === 0 ? (
                <div className="skills-empty">
                    <Boxes size={28} />
                    <strong>Установленных skills пока нет</strong>
                    <span>Добавьте навык в папку Vera/skills, чтобы он появился здесь.</span>
                </div>
            ) : (
                <div className="skills-grid">
                    {skills.map(skill => (
                        <article className="skill-card" key={skill.name}>
                            <div className="skill-card-heading">
                                <div className="skill-card-icon"><Boxes size={20} /></div>
                                <div className="skill-card-title">
                                    <strong>{skill.title}</strong>
                                    <code>{skill.name}</code>
                                </div>
                                <span className={`skill-source ${skill.source}`}>
                                    {skill.source === 'user' ? 'Пользовательский' : 'Встроенный'}
                                </span>
                            </div>
                            <p>{skill.description || 'Описание навыка не указано.'}</p>
                            <div className="skill-card-meta">
                                {skill.model_profile && <span>Модель: {skill.model_profile}</span>}
                                {skill.activation && <span>Активация: {skill.activation}</span>}
                            </div>
                            {skill.allowed_tools.length > 0 && (
                                <div className="skill-tools">
                                    <span className="skill-tools-label"><Wrench size={12} /> Инструменты</span>
                                    {skill.allowed_tools.map(tool => <code key={tool}>{tool}</code>)}
                                </div>
                            )}
                        </article>
                    ))}
                </div>
            )}
        </section>
    );
}

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
    const [activeSessionId, setActiveSessionId] = useState<string | null>(() => readActiveSessionId());
    const [sessionsPanelOpen, setSessionsPanelOpen] = useState(true);
    const [workspacePanelOpen, setWorkspacePanelOpen] = useState(false);
    const [workspacePanelMode, setWorkspacePanelMode] = useState<WorkspacePanelMode>('files');
    const [projectsOpen, setProjectsOpen] = useState(false);
    const [skillsOpen, setSkillsOpen] = useState(false);
    const [input, setInput] = useState('');
    const [status, setStatus] = useState('listening');
    const [isSettingsOpen, setIsSettingsOpen] = useState(false);
    const [isConnected, setIsConnected] = useState(false);
    const [isAgentReady, setIsAgentReady] = useState(false);
    const [isBackendStarting, setIsBackendStarting] = useState(true);
    const [isMaximized, setIsMaximized] = useState(false);
    const [logsOpen, setLogsOpen] = useState(false);
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const [settingsInitialSection, setSettingsInitialSection] = useState('appearance');
    const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo>(() => ({
        version: '1.1.1',
        model_name: localStorage.getItem(RUNTIME_MODEL_STORAGE_KEY) || 'Загрузка модели...',
    }));
    const [isDraggingFile, setIsDraggingFile] = useState(false);
    const [activityLabel, setActivityLabel] = useState<string | null>(null);

    useEffect(() => {
        if (!ipcRenderer) return;
        const handleWindowState = (_event: any, state: { isMaximized: boolean; isFullScreen: boolean }) => {
            setIsMaximized(state.isMaximized || state.isFullScreen);
        };
        ipcRenderer.on('window-state-changed', handleWindowState);
        return () => {
            ipcRenderer.removeListener('window-state-changed', handleWindowState);
        };
    }, []);
    const [thinkingEnabled, setThinkingEnabled] = useState(() => {
        const saved = localStorage.getItem('vera_thinking_enabled');
        return saved === null ? true : saved === 'true';
    });
    const wsRef = useRef<WebSocket | null>(null);
    const activeSessionIdRef = useRef<string | null>(null);
    const sessionsInitializedRef = useRef(false);
    const messagesEndRef = useRef<HTMLDivElement | null>(null);
    const pendingUserMsgs = useRef<Set<string>>(new Set()); // РўСЂРµРєРµСЂ РѕРїС‚РёРјРёСЃС‚РёС‡РЅС‹С… СЃРѕРѕР±С‰РµРЅРёР№
    const fileInputRef = useRef<HTMLInputElement | null>(null);
    const [attachedFile, setAttachedFile] = useState<File | null>(null);
    const attachmentPreviewUrl = useMemo(
        () => attachedFile && isImageFile(attachedFile) ? URL.createObjectURL(attachedFile) : null,
        [attachedFile],
    );
    const [isMuted, setIsMuted] = useState(false);
    const [renderWindow, setRenderWindow] = useState(120);
    const thinkingEnabledRef = useRef(thinkingEnabled);
    const pendingChunksRef = useRef<any[]>([]);
    const chunkFlushRafRef = useRef<number | null>(null);
    const ignoreLateChunksRef = useRef(false);
    const logSequenceRef = useRef(0);
    const logsEndRef = useRef<HTMLDivElement | null>(null);
    const dragDepthRef = useRef(0);
    const agentReadyRef = useRef(false);

    useEffect(() => {
        return () => {
            if (attachmentPreviewUrl) URL.revokeObjectURL(attachmentPreviewUrl);
        };
    }, [attachmentPreviewUrl]);

    const appendLog = useCallback((
        text: string,
        level: LogEntry['level'] = 'info',
        detail?: string,
    ) => {
        const entry: LogEntry = {
            id: ++logSequenceRef.current,
            time: new Date().toLocaleTimeString('ru-RU', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
            }),
            level,
            text,
            detail,
        };
        setLogs(prev => [...prev.slice(-299), entry]);
    }, []);

    useEffect(() => {
        if (logsOpen) {
            logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }
    }, [logs, logsOpen]);

    useEffect(() => {
        if (!isConnected) return;
        let cancelled = false;
        let retryTimer: number | null = null;
        let attempt = 0;
        const retryDelays = [0, 500, 1500, 3000, 6000, 10000];

        const loadRuntimeInfo = async () => {
            try {
                const response = await veraFetch('http://127.0.0.1:8000/api/runtime-info');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                const modelName = String(data?.model_name || '').trim();
                if (!modelName || modelName === 'Unknown model') {
                    throw new Error('Model name is not ready');
                }
                if (cancelled) return;
                localStorage.setItem(RUNTIME_MODEL_STORAGE_KEY, modelName);
                setRuntimeInfo({
                    version: String(data.version || '1.1.1'),
                    model_name: modelName,
                    model_path: typeof data.model_path === 'string' ? data.model_path : undefined,
                });
            } catch {
                attempt += 1;
                if (!cancelled && attempt < retryDelays.length) {
                    retryTimer = window.setTimeout(loadRuntimeInfo, retryDelays[attempt]);
                }
            }
        };

        loadRuntimeInfo();
        return () => {
            cancelled = true;
            if (retryTimer != null) window.clearTimeout(retryTimer);
        };
    }, [isConnected]);

    useEffect(() => {
        activeSessionIdRef.current = activeSessionId;
        writeActiveSessionId(activeSessionId);
    }, [activeSessionId]);

    const handleMinimize = useCallback(() => {
        if (ipcRenderer) {
            ipcRenderer.send('minimize-chat');
        }
    }, []);

    const handleToggleFullscreen = useCallback(() => {
        if (ipcRenderer) {
            ipcRenderer.send('toggle-chat-fullscreen');
        }
    }, []);

    const handleQuitApp = useCallback(() => {
        if (ipcRenderer) {
            ipcRenderer.send('quit-app');
            return;
        }
        window.close();
    }, []);

    const openSettingsSection = useCallback((section: string) => {
        if (!agentReadyRef.current) return;
        setSettingsInitialSection(section);
        setIsSettingsOpen(true);
    }, []);

    useEffect(() => {
        if (!isAgentReady) {
            setIsSettingsOpen(false);
        }
    }, [isAgentReady]);

    const attachWorkspaceFile = useCallback(async (filePath: string) => {
        if (!ipcRenderer || !filePath) return;
        try {
            const result = await ipcRenderer.invoke('workspace-read-file', filePath) as {
                name: string;
                size: number;
                data: Uint8Array | { data: number[] };
            };
            const source = result.data instanceof Uint8Array
                ? result.data
                : new Uint8Array(result.data.data);
            const bytes = new Uint8Array(source.byteLength);
            bytes.set(source);
            const file = new File([bytes.buffer], result.name, {
                type: getImageMimeType(result.name) || 'application/octet-stream',
                lastModified: Date.now(),
            });
            setAttachedFile(file);
            appendLog('Файл прикреплён', 'success', result.name);
        } catch (error) {
            appendLog(
                'Не удалось прикрепить файл',
                'error',
                error instanceof Error ? error.message : String(error),
            );
        }
    }, [appendLog]);

    const handleDragEnter = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        event.stopPropagation();
        const dragTypes = Array.from(event.dataTransfer.types);
        if (!dragTypes.includes('Files') && !dragTypes.includes(WORKSPACE_FILE_DRAG_TYPE)) return;
        dragDepthRef.current += 1;
        setIsDraggingFile(true);
    }, []);

    const handleDragOver = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        event.stopPropagation();
        const dragTypes = Array.from(event.dataTransfer.types);
        if (dragTypes.includes('Files') || dragTypes.includes(WORKSPACE_FILE_DRAG_TYPE)) {
            event.dataTransfer.dropEffect = 'copy';
        }
    }, []);

    const handleDragLeave = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        event.stopPropagation();
        dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
        if (dragDepthRef.current === 0) {
            setIsDraggingFile(false);
        }
    }, []);

    const handleFileDrop = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        event.stopPropagation();
        dragDepthRef.current = 0;
        setIsDraggingFile(false);
        const workspaceFilePath = event.dataTransfer.getData(WORKSPACE_FILE_DRAG_TYPE);
        if (workspaceFilePath) {
            attachWorkspaceFile(workspaceFilePath);
            return;
        }
        const file = event.dataTransfer.files?.[0];
        if (!file) return;
        setAttachedFile(file);
        appendLog('Файл прикреплён', 'success', file.name);
    }, [appendLog, attachWorkspaceFile]);

    const pushSystemMessage = useCallback((text: string) => {
        setMessages(prev => [...prev, { role: 'system', text }]);
    }, []);

    const refreshSessions = useCallback(async () => {
        const next = await listSessions(veraFetch);
        return next;
    }, []);

    const selectSession = useCallback(async (sessionId: string) => {
        setProjectsOpen(false);
        setSkillsOpen(false);
        ignoreLateChunksRef.current = true;
        pendingChunksRef.current = [];
        if (chunkFlushRafRef.current != null) {
            window.cancelAnimationFrame(chunkFlushRafRef.current);
            chunkFlushRafRef.current = null;
        }
        const stored = await loadSessionMessages(veraFetch, sessionId);
        activeSessionIdRef.current = sessionId;
        setActiveSessionId(sessionId);
        bumpSessionsRevision();
        setMessages(stored.map(item => ({
            role: item.role,
            text: item.metadata?.has_user_text === false ? '' : item.content,
            file: typeof item.metadata?.file_name === 'string' ? item.metadata.file_name : undefined,
            fileSize: typeof item.metadata?.file_size === 'number' ? item.metadata.file_size : undefined,
            imagePreview: typeof item.metadata?.image_preview_data_url === 'string'
                ? item.metadata.image_preview_data_url
                : undefined,
        })));
        setRenderWindow(120);
    }, []);

    const startNewSession = useCallback(async () => {
        setProjectsOpen(false);
        setSkillsOpen(false);
        const created = await createSession(veraFetch);
        activeSessionIdRef.current = created.id;
        setActiveSessionId(created.id);
        bumpSessionsRevision();
        setMessages([]);
        setInput('');
        setAttachedFile(null);
        setRenderWindow(120);
        return created;
    }, []);

    const reconcileActiveSession = useCallback(async () => {
        const items = await refreshSessions();
        const currentId = activeSessionIdRef.current;
        if (currentId && items.some(item => item.id === currentId)) {
            return;
        }

        ignoreLateChunksRef.current = true;
        pendingChunksRef.current = [];
        if (chunkFlushRafRef.current != null) {
            window.cancelAnimationFrame(chunkFlushRafRef.current);
            chunkFlushRafRef.current = null;
        }

        if (items[0]) {
            await selectSession(items[0].id);
        } else {
            await startNewSession();
        }
    }, [refreshSessions, selectSession, startNewSession]);

    useEffect(() => {
        const onPaste = (event: ClipboardEvent) => {
            const clipboard = event.clipboardData;
            if (!clipboard) return;

            let pastedFile: File | null = clipboard.files?.[0] || null;
            if (!pastedFile) {
                for (const item of Array.from(clipboard.items || [])) {
                    if (item.kind !== 'file') continue;
                    pastedFile = item.getAsFile();
                    if (pastedFile) break;
                }
            }
            if (!pastedFile) return;

            event.preventDefault();
            const isClipboardImage = isImageFile(pastedFile);
            const file = isClipboardImage && (!pastedFile.name || pastedFile.name === 'image.png')
                ? new File(
                    [pastedFile],
                    `clipboard-${new Date().toISOString().replace(/[:.]/g, '-')}.png`,
                    { type: pastedFile.type || 'image/png', lastModified: Date.now() },
                )
                : pastedFile;
            setAttachedFile(file);
            appendLog(
                isClipboardImage ? 'Изображение вставлено из буфера' : 'Файл вставлен из буфера',
                'success',
                file.name,
            );
        };

        window.addEventListener('paste', onPaste);
        return () => window.removeEventListener('paste', onPaste);
    }, [appendLog]);

    useEffect(() => {
        if (sessionsInitializedRef.current) return;
        sessionsInitializedRef.current = true;
        refreshSessions()
            .then(async items => {
                const preferredSessionId = readActiveSessionId();
                const preferred = preferredSessionId
                    ? items.find(item => item.id === preferredSessionId)
                    : null;
                if (preferred) {
                    await selectSession(preferred.id);
                } else if (items.length > 0) {
                    await selectSession(items[0].id);
                } else {
                    await startNewSession();
                }
            })
            .catch(error => {
                sessionsInitializedRef.current = false;
                console.error('Не удалось загрузить сессии', error);
            });
    }, [pushSystemMessage, refreshSessions, selectSession, startNewSession]);

    useEffect(() => {
        const onStorage = (event: StorageEvent) => {
            if (event.key === ACTIVE_SESSION_STORAGE_KEY) {
                const nextId = readActiveSessionId();
                if (nextId && nextId !== activeSessionIdRef.current) {
                    selectSession(nextId).catch(error => {
                        pushSystemMessage(`Ошибка переключения сессии: ${error.message}`);
                    });
                } else if (!nextId && activeSessionIdRef.current) {
                    reconcileActiveSession().catch(error => {
                        pushSystemMessage(`Ошибка обновления сессии: ${error.message}`);
                    });
                }
            }
            if (event.key === SESSIONS_REV_STORAGE_KEY) {
                reconcileActiveSession().catch(() => undefined);
            }
        };
        const onActiveSession = (event: Event) => {
            const nextId = (event as CustomEvent<string | null>).detail;
            if (nextId && nextId !== activeSessionIdRef.current) {
                selectSession(nextId).catch(error => {
                    pushSystemMessage(`Ошибка переключения сессии: ${error.message}`);
                });
            } else if (!nextId && activeSessionIdRef.current) {
                reconcileActiveSession().catch(error => {
                    pushSystemMessage(`Ошибка обновления сессии: ${error.message}`);
                });
            }
        };
        const onSessionsRevision = () => {
            reconcileActiveSession().catch(() => undefined);
        };

        window.addEventListener('storage', onStorage);
        window.addEventListener(ACTIVE_SESSION_EVENT, onActiveSession);
        window.addEventListener(SESSIONS_REV_EVENT, onSessionsRevision);
        return () => {
            window.removeEventListener('storage', onStorage);
            window.removeEventListener(ACTIVE_SESSION_EVENT, onActiveSession);
            window.removeEventListener(SESSIONS_REV_EVENT, onSessionsRevision);
        };
    }, [pushSystemMessage, reconcileActiveSession, selectSession]);

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
    const hasActiveStreamingMessage = useMemo(
        () => visibleMessages.some(message => message.role === 'assistant' && message.streaming),
        [visibleMessages],
    );
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
                    if (chunk.type === 'thought_chunk') {
                        updated.thoughts = (updated.thoughts || '') + String(chunk.text || '');
                    } else {
                        updated.text += String(chunk.text || '');
                    }
                    next = [...next.slice(0, streamIdx), updated, ...next.slice(streamIdx + 1)];
                } else {
                    next = [
                        ...next,
                        {
                            role: 'assistant',
                            text: chunk.type === 'thought_chunk' ? '' : String(chunk.text || ''),
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
                    setIsBackendStarting(true);
                    agentReadyRef.current = false;
                    setIsAgentReady(false);
                    appendLog('Соединение с Vera установлено', 'success');
                    ws.send(JSON.stringify({
                        type: 'set_thinking_mode',
                        enabled: thinkingEnabledRef.current,
                    }));
                    ws.send(JSON.stringify({ type: 'get_thinking_mode' }));
                    ws.send(JSON.stringify({ type: 'get_runtime_info' }));
                    ws.send(JSON.stringify({ type: 'get_agent_status' }));
                },
                onError: () => {
                    setIsConnected(prev => (prev ? false : prev));
                    setIsBackendStarting(true);
                    agentReadyRef.current = false;
                    setIsAgentReady(false);
                    appendLog('Ошибка соединения с сервером', 'error');
                },
                onClose: () => {
                    setIsConnected(prev => (prev ? false : prev));
                    setIsBackendStarting(true);
                    agentReadyRef.current = false;
                    setIsAgentReady(false);
                    appendLog('Соединение потеряно. Переподключаюсь...', 'error');
                },
                onMessage: (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.type === 'task_status' && data.session_id) {
                            if (data.state === 'completed' || data.state === 'failed') {
                                refreshSessions().then(() => bumpSessionsRevision()).catch(() => undefined);
                            }
                        }
                        if (data.session_id && data.session_id !== activeSessionIdRef.current) {
                            return;
                        }
                        if (data.type === 'state') {
                            setStatus(prev => (prev === data.value ? prev : data.value));
                            if (data.value !== 'thinking') {
                                setActivityLabel(null);
                            }
                            const stateLabels: Record<string, string> = {
                                thinking: 'Думает',
                                speaking: 'Озвучивает ответ',
                                listening: 'Готова к следующей задаче',
                                idle: 'Ожидает задачу',
                            };
                            appendLog(stateLabels[data.value] || `Состояние: ${data.value}`);
                            return;
                        }
                        if (data.type === 'agent_status') {
                            const ready = Boolean(data.ready);
                            const becameReady = ready && !agentReadyRef.current;
                            agentReadyRef.current = ready;
                            setIsAgentReady(ready);
                            setIsBackendStarting(!ready);
                            if (becameReady) {
                                appendLog('Vera полностью запущена и готова', 'success');
                            }
                            return;
                        }
                        if (data.type === 'thinking_mode') {
                            if (typeof data.enabled === 'boolean') {
                                setThinkingEnabled(prev => (prev === data.enabled ? prev : data.enabled));
                            }
                            return;
                        }
                        if (data.type === 'runtime_info') {
                            const modelName = String(data.model_name || '').trim();
                            if (modelName && modelName !== 'Unknown model') {
                                localStorage.setItem(RUNTIME_MODEL_STORAGE_KEY, modelName);
                                setRuntimeInfo({
                                    version: String(data.version || '1.1.1'),
                                    model_name: modelName,
                                    model_path: typeof data.model_path === 'string' ? data.model_path : undefined,
                                });
                            }
                            return;
                        }
                        if (data.type === 'task_status') {
                            if (data.state === 'queued' || data.state === 'running') {
                                ignoreLateChunksRef.current = false;
                            }
                            const taskLabels: Record<string, string> = {
                                queued: 'Задача добавлена в очередь',
                                running: 'Задача запущена',
                                completed: 'Задача завершена',
                                failed: 'Задача завершилась с ошибкой',
                            };
                            appendLog(
                                taskLabels[data.state] || `Задача: ${data.state}`,
                                data.state === 'failed' ? 'error' : data.state === 'completed' ? 'success' : 'info',
                                data.reason ? String(data.reason) : undefined,
                            );
                            if (data.state === 'completed' || data.state === 'failed') {
                                setActivityLabel(null);
                            }
                            if (data.state === 'failed' && data.reason) {
                                pushSystemMessage(`Задача завершилась с ошибкой: ${data.reason}`);
                            }
                            return;
                        }
                        if (data.type === 'action_explain') {
                            appendLog(String(data.text || data.message || 'Выполняется действие'));
                            return;
                        }
                        if (data.type === 'tool_result') {
                            setActivityLabel(null);
                            appendLog(
                                `${data.name}: ${data.status === 'ok' ? 'готово' : 'ошибка'}`,
                                data.status === 'ok' ? 'success' : 'error',
                                data.result ? String(data.result) : undefined,
                            );
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
                            setActivityLabel(getToolActivityLabel(String(data.name || 'tool')));
                            const args = data.args && Object.keys(data.args).length
                                ? JSON.stringify(data.args, null, 2)
                                : undefined;
                            appendLog(`Запуск инструмента: ${data.name}`, 'info', args);
                        }
                    } catch (e) { }
                },
            },
            2000,
        );
    }, [appendLog, enqueueChunk, findLastStreamingAssistantIndex, pushSystemMessage, refreshSessions]);

    useEffect(() => {
        if (!ipcRenderer) {
            return;
        }

        const onBackendStatus = (_event: unknown, payload: any) => {
            if (!payload || typeof payload !== 'object') {
                return;
            }

            if (payload.type === 'restarting') {
                setIsBackendStarting(true);
                agentReadyRef.current = false;
                setIsAgentReady(false);
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
                setIsBackendStarting(true);
                agentReadyRef.current = false;
                setIsAgentReady(false);
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
                return;
            }

            if (payload.type === 'starting') {
                setIsBackendStarting(true);
                agentReadyRef.current = false;
                setIsAgentReady(false);
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

    const handleSend = useCallback(async (e: React.FormEvent) => {
        e.preventDefault();
        if (!isAgentReady || (!input.trim() && !attachedFile) || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
        setActivityLabel(null);
        await reconcileActiveSession();
        let targetSessionId = activeSessionIdRef.current;
        if (!targetSessionId) {
            const created = await startNewSession();
            targetSessionId = created.id;
        }
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
        let imageDataUrl = '';
        let imagePreviewDataUrl = '';
        const selectedFile = attachedFile;

        // РћРїС‚РёРјРёСЃС‚РёС‡РЅРѕРµ РѕС‚РѕР±СЂР°Р¶РµРЅРёРµ СЃРѕРѕР±С‰РµРЅРёСЏ
        // Р•СЃР»Рё РµСЃС‚СЊ С„Р°Р№Р» вЂ” Р·Р°РіСЂСѓР¶Р°РµРј Рё РёР·РІР»РµРєР°РµРј С‚РµРєСЃС‚
        if (selectedFile) {
            try {
                const formData = new FormData();
                formData.append('file', selectedFile);
                const res = await veraFetch('http://127.0.0.1:8000/api/upload', {
                    method: 'POST',
                    body: formData
                });
                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}`);
                }
                const data = await res.json();
                if (data.kind === 'image' && data.image_data_url) {
                    imageDataUrl = String(data.image_data_url);
                    imagePreviewDataUrl = String(data.image_preview_data_url || data.image_data_url);
                } else {
                    fileContextStr = data.text || '';
                }
            } catch (err) {
                fileContextStr = `[Ошибка загрузки файла: ${selectedFile.name}]`;
            } finally {
                setAttachedFile(null);
                if (fileInputRef.current) fileInputRef.current.value = '';
            }
        }

        const userMsg: Message = {
            role: 'user',
            text: fullText,
            file: selectedFile?.name,
            fileSize: selectedFile?.size,
            imagePreview: imagePreviewDataUrl || undefined,
        };
        setMessages(prev => [...prev, userMsg]);
        pendingUserMsgs.current.add(fullText || (selectedFile ? selectedFile.name : ''));

        const payload = {
            type: 'command',
            session_id: targetSessionId,
            text: fullText,
            file_name: selectedFile ? selectedFile.name : null,
            file_context: fileContextStr,
            image_preview_data_url: imagePreviewDataUrl || null,
            file_size: selectedFile?.size || null,
            image_data_url: imageDataUrl || null,
            task_id: `ui-${Date.now()}-${Math.floor(Math.random() * 100000)}`,
        };

        wsRef.current.send(JSON.stringify(payload));
        appendLog('Запрос отправлен', 'info', fullText || selectedFile?.name);
        setInput('');
    }, [appendLog, input, attachedFile, isAgentReady, reconcileActiveSession, startNewSession]);

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
            session_id: activeSessionIdRef.current,
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
        }));
    }, [thinkingEnabled]);

    return (
        <div
            className="vera-shell vera-workspace-shell relative w-full h-full overflow-hidden"
        >
            <AnimatePresence>
                <SettingsModal
                    isOpen={isAgentReady && isSettingsOpen}
                    onClose={() => setIsSettingsOpen(false)}
                    currentThemeId={currentThemeId}
                    onThemeChange={onThemeChange}
                    initialSection={settingsInitialSection}
                />
            </AnimatePresence>

            <div className="vera-workspace-layout">
            {sessionsPanelOpen && (
                <SessionPanelWindow
                    veraFetch={veraFetch}
                    onSkills={() => {
                        setProjectsOpen(false);
                        setSkillsOpen(true);
                    }}
                    onProjects={() => {
                        setSkillsOpen(false);
                        setProjectsOpen(true);
                    }}
                    onSessionOpen={() => {
                        setProjectsOpen(false);
                        setSkillsOpen(false);
                    }}
                    activeSection={skillsOpen ? 'skills' : projectsOpen ? 'projects' : null}
                />
            )}
            <main
                className="vera-workspace-main"
                onDragEnter={handleDragEnter}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleFileDrop}
            >
            <AnimatePresence>
                {isDraggingFile && (
                    <motion.div
                        className="file-drop-overlay no-drag-region"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                    >
                        <div className="file-drop-frame">
                            <div className="file-drop-copy">
                                <UploadCloud size={19} />
                                <span>Перетащите файл, чтобы прикрепить</span>
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
            <div className="vera-workspace-topbar drag-region">
                <button
                    onClick={() => setSessionsPanelOpen(value => !value)}
                    className="vera-workspace-icon-button no-drag-region"
                    title={sessionsPanelOpen ? 'Скрыть сессии' : 'Показать сессии'}
                >
                    <PanelRight size={18} />
                </button>
                <div />
                <div className="vera-workspace-window-actions no-drag-region">
                    <button
                        onClick={() => setWorkspacePanelOpen(value => !value)}
                        className={workspacePanelOpen ? 'active' : ''}
                        title={workspacePanelOpen ? 'Скрыть рабочую панель' : 'Показать рабочую панель'}
                        aria-expanded={workspacePanelOpen}
                    >
                        <PanelLeft size={18} />
                    </button>
                    <button
                        onClick={() => openSettingsSection('appearance')}
                        title={isAgentReady ? 'Настройки' : 'Настройки будут доступны после подключения'}
                        disabled={!isAgentReady}
                        aria-disabled={!isAgentReady}
                    >
                        <Settings size={18} />
                    </button>
                    <button onClick={handleMinimize} title="Minimize"><Minus size={18} /></button>
                    <button onClick={handleToggleFullscreen} title={isMaximized ? "Restore" : "Fullscreen"}>
                        {isMaximized ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
                    </button>
                    <button onClick={handleQuitApp} title="Close app"><X size={18} /></button>
                </div>
            </div>
            <AnimatePresence>
                {(!isAgentReady || isBackendStarting) && (
                    <motion.div
                        key="agent-connection"
                        className="agent-connection-overlay no-drag-region"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: reduceMotion ? 0 : 0.18 }}
                        aria-live="polite"
                        aria-busy="true"
                    >
                        <div className="agent-connection-label">
                            <span>Соединение</span>
                            <span className="agent-connection-dots" aria-hidden="true" />
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
            {projectsOpen && <ProjectsView onClose={() => setProjectsOpen(false)} />}
            {skillsOpen && <SkillsView onClose={() => setSkillsOpen(false)} />}
            {/* РЎРѕРѕР±С‰РµРЅРёСЏ */}
            <div className="vera-workspace-messages no-drag-region">
                {messages.length === 0 && (
                    <EmptyChatStage isLightMode={isLightMode} />
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
                                className={`vera-workspace-message-row flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                            >
                                <MessageBubble msg={msg} isLightMode={isLightMode} />
                            </motion.div>
                        );
                    })}
                    {status === 'thinking' && (!hasActiveStreamingMessage || activityLabel) && (
                        <motion.div initial={reduceMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }} className="vera-workspace-message-row flex justify-start">
                            <div className={`thinking-status ${reduceMotion ? '' : 'is-animated'}`}>
                                {activityLabel || 'Думает'}
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
                <div ref={messagesEndRef} />
            </div>

            {/* РџР°РЅРµР»СЊ РІРІРѕРґР° */}
            <div className="vera-workspace-composer-wrap">
                <AnimatePresence initial={false}>
                    {logsOpen && (
                        <motion.div
                            className="vera-workspace-log-panel"
                            initial={reduceMotion ? false : { opacity: 0, y: 8, height: 0 }}
                            animate={{ opacity: 1, y: 0, height: 210 }}
                            exit={{ opacity: 0, y: 8, height: 0 }}
                        >
                            <div className="vera-workspace-log-header">
                                <span>Логи</span>
                                <button type="button" onClick={() => setLogs([])}>Очистить</button>
                            </div>
                            <div className="vera-workspace-log-list">
                                {logs.length === 0 && <div className="vera-workspace-log-empty">Событий пока нет</div>}
                                {logs.map(entry => (
                                    <div key={entry.id} className={`vera-workspace-log-entry ${entry.level}`}>
                                        <time>{entry.time}</time>
                                        <div>
                                            <div className="vera-workspace-log-message">{entry.text}</div>
                                            {entry.detail && <pre>{entry.detail}</pre>}
                                        </div>
                                    </div>
                                ))}
                                <div ref={logsEndRef} />
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
                {/* Р§РёРї РїСЂРёРєСЂРµРїР»С‘РЅРЅРѕРіРѕ С„Р°Р№Р»Р° */}
                {attachedFile && (
                    <div className="attachment-preview-wrap">
                        <div className={`attachment-card ${isLightMode ? 'light' : ''}`}>
                            {attachmentPreviewUrl ? (
                                <img
                                    src={attachmentPreviewUrl}
                                    alt=""
                                    className="attachment-image-preview"
                                />
                            ) : (
                                <div className="attachment-icon">
                                    <FileText size={18} />
                                </div>
                            )}
                            <div className="attachment-body">
                                <div className="attachment-name" title={attachedFile.name}>{attachedFile.name}</div>
                                <div className="attachment-meta-line">
                                    <span className="attachment-badge">{getFileExtension(attachedFile.name)}</span>
                                    <span>{formatFileSize(attachedFile.size)}</span>
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
                    accept=".png,.jpg,.jpeg,.webp,.bmp,.docx,.doc,.txt,.md,.py,.pdf,.xlsx,.xls,.pptx,.json,.csv,.xml,.html,.css,.js,.log"
                    onChange={handleFileSelect}
                    className="hidden"
                />

                <form onSubmit={handleSend} className={`vera-workspace-composer ${!isConnected || !isAgentReady ? 'is-disconnected' : ''}`}>
                    <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        className={`vera-workspace-composer-tool ${attachedFile ? 'active' : ''}`}
                        title="Прикрепить файл"
                    >
                        <Paperclip size={18} />
                    </button>
                    <button
                        type="button"
                        onClick={toggleThinking}
                        className={`vera-workspace-composer-tool ${thinkingEnabled ? 'active' : ''}`}
                        title={thinkingEnabled ? "Режим размышления включен" : "Режим размышления выключен"}
                    >
                        <Brain size={18} />
                    </button>
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder={attachedFile ? "Спросите о прикреплённом файле..." : "Написать сообщение..."}
                        className="vera-workspace-composer-input"
                        disabled={!isAgentReady}
                    />
                    <button
                        type="button"
                        onClick={toggleMute}
                        className="vera-workspace-mic-button"
                        title={isMuted ? "Включить микрофон" : "Выключить микрофон"}
                        aria-label={isMuted ? "Включить микрофон" : "Выключить микрофон"}
                    >
                        {isMuted ? <MicOff size={18} /> : <Mic size={18} />}
                    </button>
                </form>
            </div>
            <div className="vera-workspace-statusbar no-drag-region">
                <button
                    type="button"
                    className="vera-workspace-status-action"
                    onClick={() => openSettingsSection('automation')}
                    title={isAgentReady ? 'Периодические задачи' : 'Доступно после подключения'}
                    disabled={!isAgentReady}
                    aria-disabled={!isAgentReady}
                >
                    <Clock3 size={11} />
                    <span>Cron</span>
                </button>
                <div className="vera-workspace-status-spacer" />
                <span className="vera-workspace-runtime-model" title={runtimeInfo.model_path}>
                    {runtimeInfo.model_name}
                </span>
                <span className="vera-workspace-runtime-version">v{runtimeInfo.version}</span>
                <button
                    type="button"
                    className={`vera-workspace-log-toggle ${logsOpen ? 'active' : ''}`}
                    onClick={() => setLogsOpen(value => !value)}
                    title={logsOpen ? 'Скрыть логи' : 'Показать логи'}
                    aria-label={logsOpen ? 'Скрыть логи' : 'Показать логи'}
                    aria-expanded={logsOpen}
                >
                    <TerminalSquare size={11} />
                </button>
            </div>
            </main>
            {workspacePanelOpen && (
                <WorkspacePanel
                    mode={workspacePanelMode}
                    onModeChange={setWorkspacePanelMode}
                />
            )}
            </div>

        </div>
    );
}

