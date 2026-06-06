
import re
import random
import time
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Optional, List, Tuple
from urllib.parse import urlparse, quote_plus, parse_qs

from web.http_client import http as requests


def relevance_score(query: str, text: str) -> int:
    """Вычисляет релевантность текста запросу."""
    words = re.findall(r"[a-zA-Zа-яё0-9]+", query.lower())
    if not words:
        return 0
    t_low = text.lower()
    uniq_hits = sum(1 for w in set(words) if w and w in t_low)
    total_hits = sum(t_low.count(w) for w in words if w)
    return uniq_hits * 10 + total_hits


def domain_boost(domain: str) -> int:
    """Добавляет бонус за доверенные домены."""
    trusted = ["wikipedia.org", "ru.wikipedia.org", "habr.com"]
    d = domain.lower()
    return 20 if any(t in d for t in trusted) else 0


_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

_BASE_HEADERS = {
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}



def get_default_headers() -> dict:
    """Возвращает заголовки со случайным User-Agent."""
    headers = _BASE_HEADERS.copy()
    headers["User-Agent"] = random.choice(_USER_AGENTS)
    return headers



def _is_valid_result_url(href: str, seen: set) -> bool:
    """Проверяет, является ли URL валидным результатом поиска."""
    if not href.startswith("http"):
        return False
    if href in seen:
        return False
    skip_domains = ["brave.com", "search.brave", "favicon", "icon", "logo", "cdn.", "static."]
    if any(skip in href.lower() for skip in skip_domains):
        return False
    return True


def _collect_links(tags, seen: set, max_results: int) -> list:
    """Вспомогательная функция: извлекает href из тегов и фильтрует через _is_valid_result_url."""
    links = []
    for tag in tags:
        a_tag = tag if tag.name == "a" else tag.find("a", href=True)
        if not a_tag:
            continue
        href = a_tag.get("href", "")
        if _is_valid_result_url(href, seen):
            links.append(href)
            seen.add(href)
            if len(links) >= max_results:
                break
    return links


def unwrap_url(href: str) -> str:
    """Декодирует и очищает URL редиректов DuckDuckGo."""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    if "uddg=" in href:
        try:
            parsed = urlparse(href)
            queries = parse_qs(parsed.query)
            if "uddg" in queries and queries["uddg"]:
                return queries["uddg"][0]
        except Exception:
            pass
    return href


def search_ddg_lite(query: str, max_results: int = 6) -> List[str]:
    """
    Выполняет поиск через DuckDuckGo Lite (POST-запрос для чистых прямых ссылок).
    Служит резервным каналом в случае недоступности Brave Search.
    """
    links = []
    url = "https://lite.duckduckgo.com/lite/"
    headers = get_default_headers()
    
    try:
        resp = requests.post(url, data={"q": query}, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"[SEARCH] DuckDuckGo Lite HTTP {resp.status_code}")
            return []
            
        soup = BeautifulSoup(resp.text, "html.parser")
        seen = set()
        
        for a in soup.find_all("a", class_="result-link"):
            href = a.get("href", "")
            href = unwrap_url(href)
            if href.startswith("http") and not any(skip in href.lower() for skip in ["duckduckgo.com", "yandex.", "google."]):
                if href not in seen:
                    seen.add(href)
                    links.append(href)
                    if len(links) >= max_results:
                        break
                        
        print(f"[SEARCH] DuckDuckGo Lite: найдено {len(links)} ссылок для '{query}'")
    except Exception as e:
        print(f"[SEARCH] DuckDuckGo Lite error: {e}")
        
    return links


def search_brave(query: str, max_results: int = 6) -> List[str]:
    links = []
    try:
        headers = get_default_headers()
        url = f"https://search.brave.com/search?q={quote_plus(query)}"
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            seen = set()
            
            # Метод 1: div.snippet (основные результаты)
            links = _collect_links(soup.select("div.snippet"), seen, max_results)
            
            # Метод 2: a.result-header (fallback)
            if not links:
                links = _collect_links(soup.select("a.result-header"), seen, max_results)
            
            # Метод 3: все внешние ссылки (последний fallback)
            if not links:
                links = _collect_links(soup.find_all("a", href=True), seen, max_results)
            
            if links:
                print(f"[SEARCH] Brave: найдено {len(links)} ссылок")
                return links
            else:
                print(f"[SEARCH] Brave: 0 ссылок найдено для '{query}' (HTML длина: {len(resp.text)})")
        else:
            print(f"[SEARCH] Brave: HTTP {resp.status_code}")
            
    except Exception as e:
        print(f"[SEARCH] Brave error: {e}")
        
    print(f"[SEARCH] Использование резервного поиска через DuckDuckGo Lite для: '{query}'")
    return search_ddg_lite(query, max_results)



def extract_visible_text(html: str) -> str:
    """Извлекает читаемый текст из HTML, очищая от меню и кнопок."""
    soup = BeautifulSoup(html, "html.parser")
    
    # Удаляем нерелевантные элементы
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form", "button", "iframe", "svg", "menu", "dialog"]):
        tag.decompose()
    
    # Удаляем инфобоксы Википедии
    for infobox in soup.find_all("table", class_=lambda x: x and "infobox" in str(x)):
        infobox.decompose()
    for infobox in soup.find_all("div", class_=lambda x: x and "infobox" in str(x)):
        infobox.decompose()
    
    root = soup.find("main") or soup.find("article") or soup.body or soup
    
    # Извлекаем текст, разделённый переносами строк
    raw_lines = root.get_text(separator="\n", strip=True).split("\n")
    
    good_lines = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        # Эвристика: оставляем строки, где >= 4 слов, либо есть знаки препинания в конце
        words = line.split()
        if len(words) >= 4 or (len(words) >= 2 and line[-1] in ".?!:,"):
            good_lines.append(line)
            
    text = " ".join(good_lines)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_page(url: str, timeout: float = 5.0, max_bytes: int = 70000, per_page_limit: int = 1500, log_errors: bool = False) -> Tuple[str, str]:

    try:
        headers = get_default_headers()
        resp = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            stream=True,
            allow_redirects=True
        )
        
        # Retry с Referer при блокировке
        if resp.status_code in (401, 403):
            try:
                parsed = urlparse(url)
                referer = f"{parsed.scheme}://{parsed.netloc}/"
            except Exception:
                referer = "https://www.google.com/"
            headers["Referer"] = referer
            resp = requests.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
        
        resp.raise_for_status()
        
        ct = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" not in ct and "application/xhtml" not in ct:
            return url, ""
        
        buf = bytearray()
        for chunk in resp.iter_content(chunk_size=4096):
            if not chunk:
                continue
            buf.extend(chunk)
            if len(buf) >= max_bytes:
                break
        
        enc = resp.encoding or getattr(resp, "apparent_encoding", None) or "utf-8"
        try:
            html = buf.decode(enc, errors="ignore")
        except Exception:
            html = buf.decode("utf-8", errors="ignore")
        
        text = extract_visible_text(html)[:per_page_limit]
        return url, text
        
    except Exception as e:
        if log_errors:
            print(f"[FETCH] Ошибка загрузки {url}: {e}")
        return url, ""


def fetch_url(url: str, headers: dict, web_cfg: dict, log_page_errors: bool = False) -> Optional[Tuple[str, str]]:

    timeout = float(web_cfg.get("page_timeout_sec", 3))
    per_page_limit = int(web_cfg.get("per_page_limit", 2000))
    max_bytes = int(web_cfg.get("max_bytes_per_page", 200000))
    
    url, text = _fetch_page(url, timeout=timeout, max_bytes=max_bytes, per_page_limit=per_page_limit, log_errors=log_page_errors)
    return (url, text) if text else None


def fetch_urls_parallel(
    urls: List[str],
    max_sources: int = 3,
    timeout: float = 3.0,
    early_stop_min: int = 3,
    early_stop_timeout: float = 5.0
) -> List[Tuple[str, str]]:

    results: List[Tuple[str, str]] = []
    results_lock = Lock()
    start_time = time.time()
    
    max_workers = min(len(urls), 10)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {
            executor.submit(_fetch_page, url, timeout): url 
            for url in urls
        }
        
        for future in as_completed(future_to_url):
            try:
                url, text = future.result()
                
                if text:
                    with results_lock:
                        results.append((url, text))
                        current_count = len(results)
                    
                    elapsed = time.time() - start_time
                    
                    if current_count >= max_sources:
                        print(f"[FETCH] Достигнут максимум: {max_sources} источников")
                        # Заметка: cancel() на futures ThreadPoolExecutor не останавливает
                        # уже запущенные запросы, а break + выход из with прекращает
                        # ожидание незавершённых futures
                        break
                    
                    if current_count >= early_stop_min and elapsed >= early_stop_timeout:
                        print(f"[FETCH] Early stop: {current_count} источников за {elapsed:.1f}с")
                        break
                        
            except Exception:
                continue
    
    return results
