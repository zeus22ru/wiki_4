"""Тесты персистентного кэша эмбеддингов."""

from utils.cache import FileCache, EmbeddingCache


def test_file_cache_persists_across_instances(tmp_path):
    c1 = FileCache(cache_dir=str(tmp_path), default_ttl=3600, max_size=100)
    assert c1.set("k1", [1.0, 2.5, 3.0])
    c1._save_index()

    c2 = FileCache(cache_dir=str(tmp_path), default_ttl=3600, max_size=100)
    val = c2.get("k1")
    assert val == [1.0, 2.5, 3.0]


def test_file_cache_removes_orphan_files(tmp_path):
    orphan = tmp_path / "deadbeef.cache"
    orphan.write_bytes(b"orphan")
    FileCache(cache_dir=str(tmp_path), default_ttl=3600, max_size=100)
    assert not orphan.exists()


def test_embedding_cache_key_includes_mode_and_dims(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.cache.settings.EMBEDDING_API_MODE", "ollama", raising=False)
    monkeypatch.setattr("utils.cache.settings.EMBEDDING_DIMENSIONS", 1024, raising=False)

    cache = EmbeddingCache(cache_dir=str(tmp_path), ttl=3600)
    vec = [0.25, 0.5, 0.75]
    assert cache.set("привет", "model-a", vec)
    assert cache.get("привет", "model-a") == vec

    monkeypatch.setattr("utils.cache.settings.EMBEDDING_DIMENSIONS", 768, raising=False)
    assert cache.get("привет", "model-a") is None
