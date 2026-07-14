import re
import time
import threading
from collections import OrderedDict
from urllib.parse import urlparse, quote_plus
from typing import Optional

from main.response_sanitizer import strip_thinking_markup
from web.http_client import http as requests
from web.web_utils import get_default_headers, search_brave, relevance_score, domain_boost, fetch_urls_parallel

_WEB_SUMMARY_PROMPT = (
    "Тебе дан контекст из веб-поиска. "
    "Дай краткий, точный ответ на вопрос пользователя на основе контекста."
)

_SEARCH_CACHE: "OrderedDict[str, tuple[float, str, list[str]]]" = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _strip_thinking_markup(text: str) -> str:
    return strip_thinking_markup(text).strip()


def _cache_lookup(key: str, ttl: int) -> Optional[tuple[str, list[str]]]:
    if ttl <= 0:
        return None
    now = time.time()
    with _CACHE_LOCK:
        entry = _SEARCH_CACHE.get(key)
        if not entry:
            return None
        ts, answer, urls = entry
        if now - ts > ttl:
            del _SEARCH_CACHE[key]
            return None
        return answer, list(urls)


def _cache_store(key: str, answer: str, urls: list[str], max_entries: int) -> None:
    if not key or max_entries <= 0:
        return
    with _CACHE_LOCK:
        _SEARCH_CACHE[key] = (time.time(), answer, list(urls))
        _SEARCH_CACHE.move_to_end(key, last=True)
        while len(_SEARCH_CACHE) > max_entries:
            _SEARCH_CACHE.popitem(last=False)


def _get_search_links(query: str, web_cfg: dict) -> list[str]:
    """Обёртка над search_brave с учётом конфига."""
    max_results = int(web_cfg.get("max_sources", 3)) * int(web_cfg.get("oversample_links_factor", 2))
    return search_brave(query, max_results)





def execute_wikipedia_command(text: str) -> Optional[str]:
    lowered = (text or "").lower().strip()
    m = (
        re.search(r"\bкто\s+так(ой|ая|ие)\s+(.+)", lowered) or
        re.search(r"\bчто\s+такое\s+(.+)", lowered)
    )
    if not m:
        return None
    if m.lastindex and m.lastindex >= 2 and m.group(2):
        query = m.group(2).strip()
    else:
        query = m.group(m.lastindex or 1).strip()
    query = re.sub(r"[?!.]+$", "", query).strip()
    if not query:
        return None
    try:
        q = re.sub(r"\(.*?\)", "", query).strip()
        headers = get_default_headers()
        sum_url = f"https://ru.wikipedia.org/api/rest_v1/page/summary/{quote_plus(q)}"
        r = requests.get(sum_url, headers=headers, timeout=3)
        if r.status_code == 200:
            data = r.json()
            extract = (data.get("extract") or "").strip()
            if extract:
                return extract if len(extract) <= 600 else extract[:600].rsplit(" ", 1)[0] + "..."
    except Exception:
        # На любой ошибке возвращаем None — маршрутизация решит, как отвечать дальше
        return None
    return None

def web_search_answer(query: str, web_cfg: dict, llm, last_search_urls: list) -> str:
    log_page_errors = bool(web_cfg.get("log_page_errors", False))
    web_max_sources = int(web_cfg.get("max_sources", 5))
    web_page_timeout = float(web_cfg.get("page_timeout_sec", 3.0))
    cache_ttl = int(web_cfg.get("cache_ttl_sec", 0))
    cache_max_entries = int(web_cfg.get("cache_max_entries", 32))
    cache_key = (query or "").strip().lower()
    if cache_key and cache_ttl > 0:
        cached = _cache_lookup(cache_key, cache_ttl)
        if cached:
            answer, cached_urls = cached
            last_search_urls.clear()
            last_search_urls.extend(cached_urls)
            # print(f"[CACHE] Использован кэш для запроса: {query}")
            return answer
        # else:
            # print(f"[CACHE] Кэш пропущен для запроса: {query}")
    links = _get_search_links(query, web_cfg)
    if not links:
        return "Не нашла подходящих результатов."

    def _host(u: str) -> str:
        try:
            h = urlparse(u).netloc.lower()
            return h[4:] if h.startswith("www.") else h
        except Exception:
            return ""

    allowed_domains = set(d.strip().lower() for d in web_cfg.get("allowed_domains", []) if d.strip())
    blocked_domains = set(d.strip().lower() for d in web_cfg.get("blocked_domains", []) if d.strip())
    filtered_links: list[str] = []
    for u in links:
        h = _host(u)
        if allowed_domains and h not in allowed_domains:
            continue
        if blocked_domains and h in blocked_domains:
            continue
        filtered_links.append(u)
    links = filtered_links or links

    candidates = []
    seen = set()
    oversample_candidates_factor = int(web_cfg.get("oversample_candidates_factor", 3))
    for u in links:
        if u not in seen:
            seen.add(u)
            candidates.append(u)
        if len(candidates) >= max(web_max_sources * oversample_candidates_factor, web_max_sources):
            break

    sources: list[tuple[str, str]] = []
    last_search_urls.clear()

    total_context_limit = int(web_cfg.get("total_context_limit", 4500))
    
    early_stop_min = int(web_cfg.get("early_stop_min_sources", 3))
    early_stop_timeout = float(web_cfg.get("early_stop_timeout", 5.0))
    
    # Асинхронная загрузка URL с early stopping
    sources_raw = fetch_urls_parallel(
        candidates,
        max_sources=web_max_sources,
        timeout=web_page_timeout,
        early_stop_min=early_stop_min,
        early_stop_timeout=early_stop_timeout,
        log_page_errors=log_page_errors,
    )
    
    # Обрабатываем результаты и соблюдаем лимит контекста
    total_len = 0
    for url, text in sources_raw:
        if total_len >= total_context_limit:
            break
        
        sources.append((url, text))
        last_search_urls.append(url)
        total_len += len(text)

    if not sources:
        return "Не удалось получить содержание страниц."

    def _score(u: str, t: str) -> int:
        try:
            return relevance_score(query, t) + domain_boost(urlparse(u).netloc)
        except Exception:
            return relevance_score(query, t)
    sources.sort(key=lambda item: _score(item[0], item[1]), reverse=True)
    context_lines: list[str] = []
    acc = 0
    for u, t in sources[:web_max_sources]:
        if acc >= total_context_limit:
            break
        remain = total_context_limit - acc
        take = t[:max(0, remain)]
        if not take:
            continue
        context_lines.append(f"[{urlparse(u).netloc}] {take}")
        acc += len(take)
    context = "\n".join(context_lines)
    has_context = bool(context_lines)
    extra_rules: list[str] = []
    if has_context:
        extra_rules.append(
            "Если контекст непустой, дай краткий содержательный ответ по ключевым фактам. Не отвечай фразами вроде 'Не нашла информации', если в контексте есть данные."
        )


    extra_text = (" " + " ".join(extra_rules)) if extra_rules else ""
    messages = [
        {"role": "system", "content": f"{_WEB_SUMMARY_PROMPT} Отвечай ТОЛЬКО по контексту. Не выдумывай.{extra_text}"},
        {"role": "user", "content": f"Вопрос: {query}\nКонтекст:\n{context}\n\nОтвет:"},
    ]

    gen_args = {k: web_cfg[k] for k in ("temperature", "top_p") if k in web_cfg}
    gen_args["chat_template_kwargs"] = {"enable_thinking": False}
    
    mt = int(web_cfg.get("llm_max_tokens", 128))
        
    if mt > 0:
        gen_args["max_tokens"] = mt
    try:
        result = llm.create_chat_completion(messages=messages, **gen_args)
        answer = _strip_thinking_markup(result["choices"][0]["message"]["content"])
        if not answer:
            answer = "Не удалось сформировать итоговый ответ по найденным источникам."
    except Exception as e:
        print(f"[WEB_SEARCH] LLM error: {e}")
        answer = "Не удалось сгенерировать ответ."

    if cache_key and cache_ttl > 0:
        _cache_store(cache_key, answer, last_search_urls, cache_max_entries)

    return f"{answer} (источники: {' '.join(last_search_urls)})"
