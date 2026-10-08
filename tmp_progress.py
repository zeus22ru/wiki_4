"""Текущее время, свежесть лога и прогресс vision-кэша."""
import datetime
import pathlib
import sqlite3

from config import settings

log = pathlib.Path("logs/wiki_qa.log")
lines = [ln for ln in log.read_text(encoding="utf-8", errors="replace").splitlines() if "Визуальная индексация" in ln]
print("сейчас:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("последняя строка лога:", lines[-1][:150] if lines else "нет")

conn = sqlite3.connect(str(pathlib.Path(settings.KB_ASSETS_DIR) / "catalog.sqlite"))
print("analyses vision:", conn.execute("select count(*) from analyses where kind='vision'").fetchone()[0])
print("occurrences:", conn.execute("select count(*) from occurrences").fetchone()[0])
conn.close()
