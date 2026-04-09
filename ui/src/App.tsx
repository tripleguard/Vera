import { useEffect, useState, useRef, useCallback, useMemo, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Paperclip, X, Send, ExternalLink, FolderOpen, Sun, Moon, FileText, Mic, MicOff, Brain, ChevronDown, ChevronUp } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { connectSocketWithReconnect } from './services/socketService';

import { Settings } from 'lucide-react';

const ipcRenderer = window.require ? window.require('electron').ipcRenderer : null;
const shell = window.require ? window.require('electron').shell : null;

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

function ThinkingBlock({ thoughts, isLightMode }: { thoughts: string, isLightMode: boolean }) {
    const [isExpanded, setIsExpanded] = useState(false);
    
    if (!thoughts) return null;
    
    return (
        <div className={`mb-4 rounded-xl border transition-all ${
            isLightMode ? 'bg-gray-50 border-gray-200' : 'bg-white/5 border-white/10'
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

function SettingsModal({ isOpen, onClose }: { isOpen: boolean, onClose: () => void }) {
    const [config, setConfig] = useState<any>(null);
    const [tasks, setTasks] = useState<any[]>([]);
    const [plugins, setPlugins] = useState<any[]>([]);
    const [pluginsLoading, setPluginsLoading] = useState(false);
    const [pluginBusyId, setPluginBusyId] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState('');

    const fetchPlugins = useCallback(async () => {
        setPluginsLoading(true);
        try {
            const res = await fetch('http://127.0.0.1:8000/api/plugins');
            const data = await res.json();
            setPlugins(Array.isArray(data) ? data : []);
        } catch (err: any) {
            setMessage('Ошибка загрузки плагинов: ' + (err?.message || String(err)));
        } finally {
            setPluginsLoading(false);
        }
    }, []);

    useEffect(() => {
        if (isOpen) {
            setMessage('');
            Promise.all([
                fetch('http://127.0.0.1:8000/api/config').then(res => res.json()),
                fetch('http://127.0.0.1:8000/api/heartbeat-tasks').then(res => res.json()),
                fetch('http://127.0.0.1:8000/api/plugins').then(res => res.json())
            ])
            .then(([cfgData, tasksData, pluginsData]) => {
                setConfig(cfgData);
                setTasks(Array.isArray(tasksData) ? tasksData : []);
                setPlugins(Array.isArray(pluginsData) ? pluginsData : []);
            })
            .catch(err => setMessage('Ошибка загрузки настроек: ' + err.message));
        }
    }, [isOpen]);

    if (!isOpen) return null;

    const handleSave = async () => {
        setLoading(true);
        try {
            await Promise.all([
                fetch('http://127.0.0.1:8000/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config)
                }),
                fetch('http://127.0.0.1:8000/api/heartbeat-tasks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tasks: tasks })
                })
            ]);
            setMessage("После сохранения приложение автоматически перезапустится...");

            setTimeout(() => {
                if (ipcRenderer) {
                    ipcRenderer.send('restart-app');
                } else {
                    window.location.reload();
                }
            }, 1500);

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

    const togglePlugin = async (pluginId: string, enabled: boolean) => {
        setPluginBusyId(pluginId);
        // Оптимистичное обновление
        setPlugins(prev => prev.map(p => p.plugin_id === pluginId ? { ...p, enabled } : p));
        try {
            const res = await fetch('http://127.0.0.1:8000/api/plugins/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ plugin_id: pluginId, enabled }),
            });
            if (!res.ok) {
                throw new Error(await res.text());
            }
            await fetchPlugins();
        } catch (err: any) {
            setMessage('Ошибка переключения плагина: ' + (err?.message || String(err)));
            // Откат
            setPlugins(prev => prev.map(p => p.plugin_id === pluginId ? { ...p, enabled: !enabled } : p));
            await fetchPlugins();
        } finally {
            setPluginBusyId(null);
        }
    };

    const uninstallPlugin = async (pluginId: string) => {
        setPluginBusyId(pluginId);
        // Оптимистичное удаление
        setPlugins(prev => prev.filter(p => p.plugin_id !== pluginId));
        try {
            const res = await fetch('http://127.0.0.1:8000/api/plugins/uninstall', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ plugin_id: pluginId }),
            });
            if (!res.ok) {
                throw new Error(await res.text());
            }
            await fetchPlugins();
        } catch (err: any) {
            setMessage('Ошибка удаления плагина: ' + (err?.message || String(err)));
            await fetchPlugins(); // Вернем обратно, загрузив с сервера
        } finally {
            setPluginBusyId(null);
        }
    };

    return (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 text-white">
            <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                className="bg-[#1a1a1a] w-full max-w-2xl max-h-[90vh] rounded-2xl border border-white/10 shadow-2xl flex flex-col overflow-hidden"
            >
                {/* Header */}
                <div className="flex items-center justify-between p-4 border-b border-white/10 bg-white/5 no-drag-region">
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

                            {/* Audio TTS */}
                            <section>
                                <h3 className="text-sm font-semibold opacity-50 uppercase tracking-widest mb-4">Озвучивание (TTS)</h3>
                                <div className="space-y-4">
                                    <div className="grid grid-cols-2 gap-4">
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">Скорость речи (rate)</label>
                                            <input
                                                type="number"
                                                value={config.tts?.rate || 0}
                                                onChange={e => handleChange('tts', 'rate', e.target.value, 'number')}
                                                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                            />
                                        </div>
                                        <div>
                                            <label className="block text-sm opacity-80 mb-1">Громкость (0.0 - 1.0)</label>
                                            <input
                                                type="number" step="0.1"
                                                value={config.tts?.volume || 0}
                                                onChange={e => handleChange('tts', 'volume', e.target.value, 'float')}
                                                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                            />
                                        </div>
                                    </div>
                                    <div>
                                        <label className="block text-sm opacity-80 mb-1">Индекс системного голоса</label>
                                        <input
                                            type="number"
                                            value={config.tts?.voice_index || 0}
                                            onChange={e => handleChange('tts', 'voice_index', e.target.value, 'number')}
                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-white/30"
                                        />
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
                                        className="text-xs text-green-400 hover:text-green-300 font-medium px-2 py-1 bg-white/5 hover:bg-white/10 rounded-md transition-all"
                                    >
                                        + Добавить
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
                                        className="text-xs text-green-400 hover:text-green-300 font-medium px-2 py-1 bg-white/5 hover:bg-white/10 rounded-md transition-all"
                                    >
                                        + Добавить задачу
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

                            <div className="h-px bg-white/5 w-full" />

                            <section>
                                <div className="flex items-center justify-between mb-4">
                                    <h3 className="text-sm font-semibold opacity-50 uppercase tracking-widest">Менеджер плагинов</h3>
                                    <button
                                        onClick={fetchPlugins}
                                        className="text-xs text-cyan-300 hover:text-cyan-200 font-medium px-2 py-1 bg-white/5 hover:bg-white/10 rounded-md transition-all"
                                    >
                                        Обновить
                                    </button>
                                </div>

                                {pluginsLoading ? (
                                    <div className="text-sm opacity-60">Загрузка плагинов...</div>
                                ) : plugins.length === 0 ? (
                                    <div className="text-sm opacity-50 px-2 py-4 border border-dashed border-white/10 rounded-lg text-center">
                                        Нет установленных плагинов
                                    </div>
                                ) : (
                                    <div className="space-y-3">
                                        {plugins.map((plugin) => {
                                            const pid = String(plugin.plugin_id || '');
                                            const isBusy = pluginBusyId === pid;
                                            const enabled = Boolean(plugin.enabled);
                                            return (
                                                <div key={pid} className="p-3 rounded-lg border border-white/10 bg-white/5">
                                                    <div className="flex items-start justify-between gap-3">
                                                        <div>
                                                            <div className="text-sm font-semibold">{plugin.name || pid}</div>
                                                            <div className="text-xs opacity-60 mt-1">
                                                                id: {pid} | v{plugin.version || '-'}
                                                            </div>
                                                            <div className="text-xs opacity-60 mt-1">
                                                                доверие: {plugin.trust_level || '-'} | рантайм: {plugin.runtime_profile || '-'}
                                                            </div>
                                                        </div>
                                                        <div className="flex items-center gap-2">
                                                            <button
                                                                disabled={isBusy}
                                                                onClick={() => togglePlugin(pid, !enabled)}
                                                                className={`px-2.5 py-1.5 text-xs rounded-md transition-all ${enabled
                                                                    ? 'bg-amber-500/20 text-amber-300 hover:bg-amber-500/30'
                                                                    : 'bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30'
                                                                    } disabled:opacity-40`}
                                                            >
                                                                {enabled ? 'Выключить' : 'Включить'}
                                                            </button>
                                                            <button
                                                                disabled={isBusy}
                                                                onClick={() => uninstallPlugin(pid)}
                                                                className="px-2.5 py-1.5 text-xs rounded-md bg-red-500/20 text-red-300 hover:bg-red-500/30 disabled:opacity-40"
                                                            >
                                                                Удалить
                                                            </button>
                                                        </div>
                                                    </div>

                                                    <div className="mt-2 text-xs opacity-70">
                                                        возможностей: {Array.isArray(plugin.capabilities) ? plugin.capabilities.length : 0}
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
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

    useEffect(() => {
        const handleHashChange = () => setRoute(window.location.hash);
        window.addEventListener('hashchange', handleHashChange);
        return () => window.removeEventListener('hashchange', handleHashChange);
    }, []);

    if (route === '#/widget') return <WidgetView />;
    return <ChatView />;
}

function WidgetView() {
    const [status, setStatus] = useState('listening'); // 'listening', 'thinking', 'speaking'

    useEffect(() => {
        return connectSocketWithReconnect(
            'ws://127.0.0.1:8000/ws',
            {
                onMessage: (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.type === 'state') setStatus(data.value);
                    } catch (e) { }
                },
            },
            2000,
        );
    }, []);

    const handleClick = () => {
        if (ipcRenderer) ipcRenderer.send('toggle-chat');
    };

    // Р¦РІРµС‚Р° Рё Р°РЅРёРјР°С†РёРё РІ Р·Р°РІРёСЃРёРјРѕСЃС‚Рё РѕС‚ СЃРѕСЃС‚РѕСЏРЅРёСЏ
    const isSpeaking = status === 'speaking';
    const isThinking = status === 'thinking';
    const reduceMotion = true;

    return (
        <div
            className="w-full h-full flex items-center justify-center bg-[#111111]/90 backdrop-blur-md rounded-2xl border border-white/10 shadow-2xl drag-region select-none overflow-hidden hover:bg-[#1a1a1a]/90 transition-colors"
        >
            <div className="relative flex items-center justify-center w-12 h-12 cursor-pointer no-drag-region" onClick={handleClick}>
                {/* РџСѓР»СЊСЃРёСЂСѓСЋС‰Р°СЏ РѕР±РІРѕРґРєР° РїСЂРё СЂР°Р·РіРѕРІРѕСЂРµ */}
                {isSpeaking && (
                    <div className="absolute inset-0 bg-white rounded-full opacity-75 animate-ping-slow transition-all"></div>
                )}

                {/* Р“Р»Р°РІРЅС‹Р№ РєСЂСѓР¶РѕРє */}
                <motion.div
                    animate={{
                        scale: reduceMotion ? 1 : (isSpeaking ? [1, 1.1, 1] : isThinking ? [1, 0.9, 1] : 1),
                        backgroundColor: isSpeaking ? '#ffffff' : isThinking ? '#e2e8f0' : '#64748b'
                    }}
                    transition={{
                        duration: reduceMotion ? 0.2 : (isSpeaking ? 0.8 : isThinking ? 1.5 : 0.3),
                        repeat: reduceMotion ? 0 : ((isSpeaking || isThinking) ? Infinity : 0),
                        ease: "easeInOut"
                    }}
                    className={`relative w-8 h-8 rounded-full shadow-lg ${!isSpeaking && !isThinking ? 'opacity-70 hover:opacity-100' : ''}`}
                />
            </div>
        </div>
    );
}


interface Message {
    role: string;
    text: string;
    thoughts?: string;
    file?: string;
    streaming?: boolean;
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
            className={`max-w-[85%] rounded-2xl px-4 py-3 text-[15px] leading-relaxed relative select-text cursor-text ${msg.role === 'user'
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
                        <div className={`flex items-center gap-2 mt-2 px-3 py-2 rounded-lg text-[13px] ${isLightMode
                            ? 'bg-blue-700/20 text-white/90'
                            : 'bg-black/10 text-black/70'
                            }`}>
                            <FileText size={16} className="flex-shrink-0" />
                            <span className="truncate">{msg.file}</span>
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
                            <div className={`flex flex-wrap gap-1.5 mt-3 pt-2 border-t ${isLightMode ? 'border-gray-200' : 'border-white/5'}`}>
                                {sources.map((url, i) => (
                                    <button
                                        key={i}
                                        onClick={() => shell?.openExternal(url)}
                                        className={`inline-flex items-center gap-1 px-2.5 py-1 text-[11px] border rounded-lg transition-all cursor-pointer ${isLightMode
                                            ? 'bg-black/5 hover:bg-black/10 border-gray-200 text-gray-600 hover:text-gray-900'
                                            : 'bg-white/10 hover:bg-white/20 border-white/10 text-white/60 hover:text-white/90'
                                            }`}
                                        title={url}
                                    >
                                        <ExternalLink size={10} />
                                        {getDomain(url)}
                                    </button>
                                ))}
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

function ChatView() {
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

    // Light mode state with persistence
    const [isLightMode, setIsLightMode] = useState(() => {
        const saved = localStorage.getItem('vera_light_mode');
        return saved === 'true';
    });

    const wsRef = useRef<WebSocket | null>(null);
    const messagesEndRef = useRef<HTMLDivElement | null>(null);
    const pendingUserMsgs = useRef<Set<string>>(new Set()); // РўСЂРµРєРµСЂ РѕРїС‚РёРјРёСЃС‚РёС‡РЅС‹С… СЃРѕРѕР±С‰РµРЅРёР№
    const fileInputRef = useRef<HTMLInputElement | null>(null);
    const [attachedFile, setAttachedFile] = useState<File | null>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [isMuted, setIsMuted] = useState(false);
    const [renderWindow, setRenderWindow] = useState(180);
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

    const reduceMotion = true;

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
        return connectSocketWithReconnect(
            'ws://127.0.0.1:8000/ws',
            {
                onOpen: (ws) => {
                    wsRef.current = ws;
                    setIsConnected(true);
                    ws.send(JSON.stringify({
                        type: 'set_thinking_mode',
                        enabled: thinkingEnabledRef.current,
                        reasoning_budget: reasoningBudgetRef.current,
                    }));
                    ws.send(JSON.stringify({ type: 'get_thinking_mode' }));
                },
                onError: () => setIsConnected(false),
                onClose: () => setIsConnected(false),
                onMessage: (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.type === 'state') {
                            setStatus(data.value);
                            return;
                        }
                        if (data.type === 'thinking_mode') {
                            if (typeof data.enabled === 'boolean') setThinkingEnabled(data.enabled);
                            if (typeof data.reasoning_budget === 'number') setReasoningBudget(data.reasoning_budget);
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
                        if (data.type === 'plugin_discovered') {
                            pushSystemMessage(`Найден пакет плагина: ${data.path}`);
                            return;
                        }
                        if (data.type === 'plugin_install_status') {
                            pushSystemMessage(`Plugin ${data.plugin_id || ''}: ${data.status}${data.reason ? ` (${data.reason})` : ''}`);
                            return;
                        }
                        if (data.type === 'plugin_permission_request') {
                            pushSystemMessage(`Плагин ${data.plugin_id} требует подтверждения разрешений.`);
                            return;
                        }
                        if (data.type === 'plugin_capability_added') {
                            const title = data?.capability?.title || data?.capability?.id || 'new capability';
                            pushSystemMessage(`Подключена capability плагина: ${title}`);
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
        localStorage.setItem('vera_light_mode', isLightMode.toString());
        if (isLightMode) {
            document.body.classList.add('light-mode');
        } else {
            document.body.classList.remove('light-mode');
        }
    }, [isLightMode]);

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
        if (attachedFile) userMsg.file = attachedFile.name;
        setMessages(prev => [...prev, userMsg]);
        pendingUserMsgs.current.add(fullText || (attachedFile ? attachedFile.name : ''));

        // Р•СЃР»Рё РµСЃС‚СЊ С„Р°Р№Р» вЂ” Р·Р°РіСЂСѓР¶Р°РµРј Рё РёР·РІР»РµРєР°РµРј С‚РµРєСЃС‚
        if (attachedFile) {
            setIsUploading(true);
            try {
                const formData = new FormData();
                formData.append('file', attachedFile);
                const res = await fetch('http://127.0.0.1:8000/api/upload', {
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
        <div className={`w-full h-full flex flex-col backdrop-blur-xl rounded-xl border overflow-hidden shadow-2xl transition-colors ${isLightMode
            ? 'bg-[#f8f9fa]/95 border-gray-200/50 text-gray-900'
            : 'bg-[#111111]/90 border-white/10 text-white'
            }`}>
            <AnimatePresence>
                <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
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
                        Vera AI 
                        {!isConnected && <span className="text-[11px] font-normal tracking-normal ml-2 text-red-500/90 whitespace-nowrap">(ожидание)</span>}
                    </span>
                </div>
                <div className="flex items-center gap-2 no-drag-region">
                    <button
                        onClick={() => setIsLightMode(!isLightMode)}
                        className={`p-1.5 rounded-md transition-all ${isLightMode
                            ? 'text-gray-600 hover:bg-black/5 hover:text-gray-900'
                            : 'text-white opacity-50 hover:opacity-100 hover:bg-white/10'
                            }`}
                        title={isLightMode ? 'Тёмная тема' : 'Светлая тема'}
                    >
                        {isLightMode ? <Moon size={16} /> : <Sun size={16} />}
                    </button>
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
                    <div className="flex items-center gap-2 mb-2 max-w-3xl mx-auto">
                        <div className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium ${isLightMode
                            ? 'bg-blue-50 text-blue-700 border border-blue-200'
                            : 'bg-white/10 text-white/80 border border-white/10'
                            }`}>
                            <Paperclip size={12} />
                            {attachedFile.name}
                            <button
                                onClick={handleRemoveFile}
                                className={`ml-1 p-0.5 rounded-full transition-colors ${isLightMode ? 'hover:bg-blue-100' : 'hover:bg-white/10'
                                    }`}
                            >
                                <X size={12} />
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

                <form onSubmit={handleSend} className={`relative flex items-center w-full max-w-3xl mx-auto rounded-xl border overflow-hidden transition-all ${
                    !isConnected ? 'opacity-50 pointer-events-none grayscale' : ''
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

