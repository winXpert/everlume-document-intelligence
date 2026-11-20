import re
import unicodedata
from pathlib import Path

SUPPORTED = {'.pdf', '.docx', '.txt', '.csv', '.md', '.json', '.log'}


def extract(path: Path, extension: str):
    if extension == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        if len(reader.pages) > 1000:
            raise ValueError('PDF exceeds 1000 pages')
        pages = [p.extract_text() or '' for p in reader.pages]
    elif extension == '.docx':
        import zipfile
        with zipfile.ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError('Expanded DOCX exceeds 100 MB')
        from docx import Document
        doc = Document(path)
        pages = ['\n'.join([p.text for p in doc.paragraphs] +
                            [' | '.join(c.text for c in row.cells) for t in doc.tables for row in t.rows])]
    else:
        pages = [path.read_text(encoding='utf-8-sig')]
    return [re.sub(r'[ \t]+', ' ', unicodedata.normalize('NFKC', p)).strip() for p in pages]


def chunks(pages):
    result = []
    for page, text in enumerate(pages, 1):
        for offset in range(0, len(text), 1000):
            part = text[offset:offset + 1200].strip()
            if part:
                result.append({'page': page, 'text': part, 'section': part.split('\n')[0][:120]})
    return result
