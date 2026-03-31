"""
Инструмент генерации документов для агента Вера.

Поддерживаемые форматы:
- .txt — текстовые файлы
- .md — Markdown документы
- .docx — Microsoft Word документы
- .pptx — PowerPoint презентации
- .xlsx — Excel таблицы

Все документы сохраняются в ~/Documents/Vera/
"""
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# Опциональные библиотеки
try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment
    HAS_XLSX = True
except ImportError:
    HAS_XLSX = False


def get_documents_dir() -> Path:
    """
    Получает путь к папке для документов.
    Создаёт ~/Documents/Vera/ если не существует.
    """
    # Получаем путь к Documents
    try:
        # Windows
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                           r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
            docs_path = Path(winreg.QueryValueEx(key, "Personal")[0])
    except Exception:
        # Fallback
        docs_path = Path.home() / "Documents"
    
    vera_docs = docs_path / "Vera"
    vera_docs.mkdir(parents=True, exist_ok=True)
    
    return vera_docs


def sanitize_filename(name: str) -> str:
    """Очищает имя файла от недопустимых символов."""
    # Убираем расширение если есть
    name = re.sub(r'\.[a-zA-Z]{2,5}$', '', name)
    # Заменяем недопустимые символы
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Убираем лишние пробелы и подчёркивания
    name = re.sub(r'[\s_]+', '_', name).strip('_')
    # Ограничиваем длину
    if len(name) > 100:
        name = name[:100]
    return name or f"document_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def generate_unique_path(base_dir: Path, filename: str, extension: str) -> Path:
    """Генерирует уникальный путь к файлу (добавляет номер если файл существует)."""
    clean_name = sanitize_filename(filename)
    path = base_dir / f"{clean_name}.{extension}"
    
    if not path.exists():
        return path
    
    # Добавляем номер
    counter = 1
    while True:
        path = base_dir / f"{clean_name}_{counter}.{extension}"
        if not path.exists():
            return path
        counter += 1
        if counter > 100:  # Защита от бесконечного цикла
            path = base_dir / f"{clean_name}_{datetime.now().strftime('%H%M%S')}.{extension}"
            break
    
    return path


# ============ Генераторы документов ============

def create_txt(filename: str, content: str) -> str:
    """Создаёт текстовый файл."""
    docs_dir = get_documents_dir()
    file_path = generate_unique_path(docs_dir, filename, "txt")
    
    try:
        file_path.write_text(content, encoding='utf-8')
        return f"Файл создан: {file_path}"
    except Exception as e:
        return f"Ошибка создания файла: {e}"


def create_md(filename: str, content: str, title: Optional[str] = None) -> str:
    """Создаёт Markdown файл."""
    docs_dir = get_documents_dir()
    file_path = generate_unique_path(docs_dir, filename, "md")
    
    try:
        md_content = ""
        if title:
            md_content = f"# {title}\n\n"
        md_content += content
        
        file_path.write_text(md_content, encoding='utf-8')
        return f"Markdown создан: {file_path}"
    except Exception as e:
        return f"Ошибка создания Markdown: {e}"


def create_docx(
    filename: str,
    content: str,
    title: Optional[str] = None,
    author: Optional[str] = None
) -> str:
    """Создаёт Word документ."""
    if not HAS_DOCX:
        return "Ошибка: библиотека python-docx не установлена."
    
    docs_dir = get_documents_dir()
    file_path = generate_unique_path(docs_dir, filename, "docx")
    
    try:
        doc = DocxDocument()
        
        # Заголовок
        if title:
            heading = doc.add_heading(title, 0)
            heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # Содержимое (разбиваем по абзацам)
        paragraphs = content.split('\n\n')
        for para in paragraphs:
            if para.strip():
                doc.add_paragraph(para.strip())
        
        # Метаданные
        if author:
            doc.core_properties.author = author
        doc.core_properties.created = datetime.now()
        
        doc.save(str(file_path))
        return f"Документ Word создан: {file_path}"
    except Exception as e:
        return f"Ошибка создания Word документа: {e}"


def create_pptx(
    filename: str,
    slides: List[Dict[str, str]],
    title: Optional[str] = None,
    theme: str = "light_blue"
) -> str:
    """
    Создаёт PowerPoint презентацию.
    
    Args:
        filename: Имя файла
        slides: Список слайдов [{"title": "...", "content": "..."}, ...]
        title: Заголовок презентации (первый слайд)
        theme: Тема оформления ("white", "light_blue", "beige", "mint")
    """
    if not HAS_PPTX:
        return "Ошибка: библиотека python-pptx не установлена."
    
    docs_dir = get_documents_dir()
    file_path = generate_unique_path(docs_dir, filename, "pptx")
    
    # Цвета тем (только светлые для совместимости с черным текстом)
    themes = {
        "white": RGBColor(255, 255, 255),
        "light_blue": RGBColor(235, 245, 255),
        "beige": RGBColor(250, 248, 240),
        "mint": RGBColor(240, 255, 250),
        "lavender": RGBColor(245, 240, 255)
    }
    bg_color = themes.get(theme, themes["light_blue"])
    
    try:
        prs = Presentation()
        
        # Функция применения фона
        def apply_background(slide):
            background = slide.background
            fill = background.fill
            fill.solid()
            fill.fore_color.rgb = bg_color
        
        # Титульный слайд
        if title:
            slide_layout = prs.slide_layouts[0]  # Title Slide
            slide = prs.slides.add_slide(slide_layout)
            apply_background(slide)
            
            title_shape = slide.shapes.title
            if title_shape:
                title_shape.text = title
        
        # Слайды с контентом
        for slide_data in slides:
            slide_layout = prs.slide_layouts[1]  # Title and Content
            slide = prs.slides.add_slide(slide_layout)
            apply_background(slide)
            
            # Заголовок слайда
            if slide.shapes.title:
                slide.shapes.title.text = slide_data.get("title", "")
            
            # Контент
            content = slide_data.get("content", "")
            if content and len(slide.placeholders) > 1:
                body_shape = slide.placeholders[1]
                tf = body_shape.text_frame
                tf.text = content
                tf.word_wrap = True
                
                try:
                    from pptx.enum.text import MSO_AUTO_SIZE
                    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
                except ImportError:
                    pass
        
        prs.save(str(file_path))
        return f"Презентация создана: {file_path} (Тема: {theme})"
    except Exception as e:
        return f"Ошибка создания презентации: {e}"


def create_xlsx(
    filename: str,
    data: List[List[Any]],
    headers: Optional[List[str]] = None,
    sheet_name: str = "Лист1"
) -> str:
    """
    Создаёт Excel таблицу.
    
    Args:
        filename: Имя файла
        data: Данные [[row1], [row2], ...]
        headers: Заголовки столбцов
        sheet_name: Название листа
    """
    if not HAS_XLSX:
        return "Ошибка: библиотека openpyxl не установлена."
    
    docs_dir = get_documents_dir()
    file_path = generate_unique_path(docs_dir, filename, "xlsx")
    
    try:
        wb = Workbook()
        ws = wb.active
        ws.title = sheet_name
        
        start_row = 1
        
        # Заголовки
        if headers:
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal='center')
            start_row = 2
        
        # Данные
        for row_idx, row_data in enumerate(data, start_row):
            for col_idx, value in enumerate(row_data, 1):
                ws.cell(row=row_idx, column=col_idx, value=value)
        
        # Автоширина столбцов
        for column_cells in ws.columns:
            length = max(len(str(cell.value or "")) for cell in column_cells)
            ws.column_dimensions[column_cells[0].column_letter].width = min(length + 2, 50)
        
        wb.save(str(file_path))
        return f"Таблица Excel создана: {file_path}"
    except Exception as e:
        return f"Ошибка создания Excel таблицы: {e}"


# ============ Диспетчер инструмента ============

def execute_document_generator(arguments: dict) -> str:
    """
    Главная функция инструмента — диспетчер по действиям.
    
    Поддерживаемые действия:
    - create_txt: {"action": "create_txt", "filename": "...", "content": "..."}
    - create_md: {"action": "create_md", "filename": "...", "content": "...", "title": "..."}
    - create_docx: {"action": "create_docx", "filename": "...", "content": "...", "title": "..."}
    - create_pptx: {"action": "create_pptx", "filename": "...", "slides": [...], "title": "..."}
    - create_xlsx: {"action": "create_xlsx", "filename": "...", "data": [...], "headers": [...]}
    """
    action = arguments.get("action", "").strip().lower()
    filename = arguments.get("filename", "").strip()
    
    if not action:
        return "Укажите действие: create_txt, create_md, create_docx, create_pptx, create_xlsx"
    
    if not filename:
        filename = f"document_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    print(f"[DOC_GEN] Действие: {action}, файл: {filename}")
    
    # Текстовый файл
    if action == "create_txt":
        content = arguments.get("content", "")
        if not content:
            return "Укажите content — текст для файла."
        return create_txt(filename, content)
    
    # Markdown
    if action == "create_md":
        content = arguments.get("content", "")
        title = arguments.get("title")
        if not content:
            return "Укажите content — текст для Markdown."
        return create_md(filename, content, title)
    
    # Word документ
    if action == "create_docx":
        content = arguments.get("content", "")
        title = arguments.get("title")
        author = arguments.get("author")
        if not content:
            return "Укажите content — текст документа."
        return create_docx(filename, content, title, author)
    
    # PowerPoint
    if action == "create_pptx":
        slides = arguments.get("slides", [])
        title = arguments.get("title")
        # Если вместо slides передан content — преобразуем
        if not slides and "content" in arguments:
            content = arguments["content"]
            slides = [{"title": title or "Слайд 1", "content": content}]
        if not slides:
            return "Укажите slides — список слайдов."
        return create_pptx(filename, slides, title, arguments.get("theme", "light_blue"))
    
    # Excel
    if action == "create_xlsx":
        data = arguments.get("data", [])
        headers = arguments.get("headers")
        sheet_name = arguments.get("sheet_name", "Лист1")
        if not data:
            return "Укажите data — данные таблицы."
        return create_xlsx(filename, data, headers, sheet_name)
    
    return f"Неизвестное действие: {action}. Доступны: create_txt, create_md, create_docx, create_pptx, create_xlsx"
