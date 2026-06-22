import re


def clean_markdown_for_rag(raw_markdown: str) -> str:
    text = re.sub(r'!\[.*?\]\(.*?\)', '', raw_markdown)
    text = re.sub(r'<p[^>]*>.*?<img[^>]*>.*?</p>', '', text, flags=re.DOTALL)
    text = re.sub(r'<a[^>]*>.*?<img[^>]*>.*?</a>', '', text, flags=re.DOTALL)
    text = re.sub(r'<img[^>]*>', '', text)
    text = re.sub(r'<(p|a)[^>]*>\s*</\1>', '', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()
