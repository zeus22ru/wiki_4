"""Тесты извлечения зачёркнутого HTML для индексации."""

from bs4 import BeautifulSoup

from core.chunking import chunk_html_structural
from core.html_text import get_index_text, normalize_strikethrough_mode

ERROR_268_PARAGRAPH = """
<p>Бабинчук даёт декл. соответствия
<del>а мы обращаемся к Володе, или Елене, или Сергею, чтобы он её подтянул.</del>
Не надо к нам обращаться, надо переотправить УПД (п. 2)</p>
"""

ERROR_268_HTML = f"""<!doctype html>
<html lang="ru"><body>
<article><h1>Код ошибки 268</h1>
<div id="xwikicontent">{ERROR_268_PARAGRAPH}</div>
</article></body></html>"""


def test_normalize_strikethrough_mode_defaults_to_mark():
    assert normalize_strikethrough_mode(None) == "mark"
    assert normalize_strikethrough_mode("MARK") == "mark"
    assert normalize_strikethrough_mode("unknown") == "mark"


def test_mark_wraps_del_text_and_keeps_current():
    soup = BeautifulSoup(ERROR_268_PARAGRAPH, "html.parser")
    text = get_index_text(soup.p, mode="mark")
    assert "[УСТАРЕЛО:" in text
    assert "Володе" in text
    assert "Не надо к нам обращаться" in text
    assert text.index("[УСТАРЕЛО:") < text.index("Не надо")


def test_exclude_omits_del_text():
    soup = BeautifulSoup(ERROR_268_PARAGRAPH, "html.parser")
    text = get_index_text(soup.p, mode="exclude")
    assert "Володе" not in text
    assert "Не надо к нам обращаться" in text


def test_keep_includes_del_without_marker():
    soup = BeautifulSoup(ERROR_268_PARAGRAPH, "html.parser")
    text = get_index_text(soup.p, mode="keep")
    assert "[УСТАРЕЛО:" not in text
    assert "Володе" in text
    assert "Не надо к нам обращаться" in text


def test_chunk_html_structural_includes_obsolete_marker():
    chunks = chunk_html_structural(ERROR_268_HTML, "Код ошибки 268", "faq/error268.html")
    combined = " ".join(c.get("text", "") for c in chunks)
    assert "[УСТАРЕЛО:" in combined
    assert "Володе" in combined
    assert "Не надо к нам обращаться" in combined


def test_line_through_style_marked():
    html = '<p>Актуально <span style="text-decoration: line-through">устарело</span> снова</p>'
    soup = BeautifulSoup(html, "html.parser")
    text = get_index_text(soup.p, mode="mark")
    assert "[УСТАРЕЛО:" in text
    assert "устарело" in text
    assert "снова" in text
