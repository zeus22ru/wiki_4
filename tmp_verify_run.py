"""Проверка результата: чанки, vision-описания, визуальные типы."""
import json
import pathlib
import sqlite3
from collections import Counter

import chromadb

from config import settings
from core.index_manifest import load_index_manifest, manifest_path

out = {}

client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
col = client.get_collection(settings.CHROMA_COLLECTION_NAME)
data = col.get(include=["metadatas", "documents"])
kinds = Counter(str((m or {}).get("chunk_kind")) for m in data["metadatas"])
out["total_chunks"] = col.count()
out["chunk_kinds"] = dict(kinds)
out["visual_chunks"] = kinds.get("visual", 0)

# сколько визуальных чанков реально содержит описание
with_desc = 0
sample = None
for text, meta in zip(data["documents"], data["metadatas"]):
    if str((meta or {}).get("chunk_kind")) == "visual":
        if "Описание изображения:" in (text or ""):
            with_desc += 1
            if sample is None:
                sample = (text or "")[:700]
out["visual_chunks_with_description"] = with_desc
out["sample_visual_chunk"] = sample

mp = manifest_path()
out["manifest_exists"] = mp.is_file()
if mp.is_file():
    man = load_index_manifest()
    out["manifest_generated_at"] = man.get("generated_at")
    out["manifest_files"] = len(man.get("files") or {})

conn = sqlite3.connect(str(pathlib.Path(settings.KB_ASSETS_DIR) / "catalog.sqlite"))
out["analyses_ocr"] = conn.execute("select count(*) from analyses where kind='ocr'").fetchone()[0]
out["analyses_vision"] = conn.execute("select count(*) from analyses where kind='vision'").fetchone()[0]
out["occurrences_total"] = conn.execute("select count(*) from occurrences").fetchone()[0]
rows = conn.execute("select visual_type, count(*) from occurrences group by visual_type").fetchall()
out["visual_type_distribution"] = {str(r[0]): int(r[1]) for r in rows}
conn.close()

text = json.dumps(out, ensure_ascii=False, indent=2)
pathlib.Path("verify_result.json").write_text(text, encoding="utf-8")
print(text)
