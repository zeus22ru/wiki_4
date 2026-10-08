#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Провайдер OCR: portable RapidOCR-json (ТЗ §8).

Контракт провайдера: :meth:`OCRProvider.health_check`, :meth:`recognize`,
:meth:`close`. Результат нормализуется в схему приложения (ТЗ §8.2), а не
копирует upstream-формат.

Реализация не подменяется установкой ``rapidocr``/``rapidocr_onnxruntime`` через
pip: используется готовый Windows x64 EXE. Тесты работают с
:class:`FakeOCRProvider`, реальный EXE проверяется отдельными Windows
integration-тестами.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import settings, get_logger

logger = get_logger(__name__)


# --- Схема результата (ТЗ §8.2) ----------------------------------------------

@dataclass
class OCRBlock:
    text: str
    polygon: List[List[float]] = field(default_factory=list)
    confidence: float = 0.0
    reading_order: int = 0
    #: Альтернативное чтение блока вторым профилем (например, английским).
    text_alt: str = ""
    #: Профиль, чьё чтение выбрано основным.
    source_profile: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OCRResult:
    status: str  # success | no_text | failed | unavailable
    engine: str = "rapidocr-json"
    engine_version: str = ""
    model_fingerprint: str = ""
    profile: str = ""
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    text_raw: str = ""
    #: Текст второго прохода (для латиницы/цифр); не заменяет text_raw.
    text_raw_alt: str = ""
    blocks: List[OCRBlock] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["blocks"] = [b.to_dict() if isinstance(b, OCRBlock) else b for b in self.blocks]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OCRResult":
        blocks = [OCRBlock(**b) if isinstance(b, dict) else b for b in (data.get("blocks") or [])]
        payload = {k: v for k, v in data.items() if k != "blocks"}
        return cls(blocks=blocks, **payload)


class OCRProviderError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


#: Языковые профили portable RapidOCR-json v0.2.0 (cmd.txt архива).
#: Каждый профиль — набор имён файлов внутри каталога models/.
PROFILE_MODELS: Dict[str, Dict[str, str]] = {
    "cyrillic": {
        "det": "ch_PP-OCRv3_det_infer.onnx",
        "cls": "ch_ppocr_mobile_v2.0_cls_infer.onnx",
        "rec": "rec_cyrillic_PP-OCRv3_infer.onnx",
        "keys": "dict_cyrillic.txt",
    },
    "english": {
        "det": "ch_PP-OCRv3_det_infer.onnx",
        "cls": "ch_ppocr_mobile_v2.0_cls_infer.onnx",
        "rec": "rec_en_PP-OCRv3_infer.onnx",
        # Апстрим в cmd.txt указывает dict_chinese.txt, но для английского
        # корректный словарь — dict_en.txt (проверено на реальном выпуске).
        "keys": "dict_en.txt",
    },
    "chinese_v4": {
        "det": "ch_PP-OCRv4_det_infer.onnx",
        "cls": "ch_ppocr_mobile_v2.0_cls_infer.onnx",
        "rec": "rec_ch_PP-OCRv4_infer.onnx",
        "keys": "ppocr_keys_v1.txt",
    },
    "chinese_v3": {
        "det": "ch_PP-OCRv3_det_infer.onnx",
        "cls": "ch_ppocr_mobile_v2.0_cls_infer.onnx",
        "rec": "ch_PP-OCRv3_rec_infer.onnx",
        "keys": "dict_chinese.txt",
    },
    "japan": {
        "det": "ch_PP-OCRv3_det_infer.onnx",
        "cls": "ch_ppocr_mobile_v2.0_cls_infer.onnx",
        "rec": "rec_japan_PP-OCRv3_infer.onnx",
        "keys": "dict_japan.txt",
    },
    "korean": {
        "det": "ch_PP-OCRv3_det_infer.onnx",
        "cls": "ch_ppocr_mobile_v2.0_cls_infer.onnx",
        "rec": "rec_korean_PP-OCRv3_infer.onnx",
        "keys": "dict_korean.txt",
    },
}


def profile_args(profile: str, *, models_dir: str = "models") -> List[str]:
    """Собрать аргументы выбора моделей для указанного профиля."""
    spec = PROFILE_MODELS.get(profile)
    if spec is None:
        raise OCRProviderError("ocr_model_missing", f"Неизвестный профиль OCR: {profile!r}")
    return [
        f"--models={models_dir}",
        f"--det={spec['det']}",
        f"--cls={spec['cls']}",
        f"--rec={spec['rec']}",
        f"--keys={spec['keys']}",
    ]


def _script_ratio(text: str) -> Tuple[float, float]:
    """Доля кириллицы и доля латиницы/цифр среди буквенно-цифровых символов."""
    cyr = lat = other = 0
    for ch in text or "":
        if ch.isalpha():
            if "\u0400" <= ch <= "\u04ff":
                cyr += 1
            else:
                lat += 1
        elif ch.isdigit():
            other += 1
    total = cyr + lat + other
    if total == 0:
        return (0.0, 0.0)
    return (cyr / total, (lat + other) / total)



# --- Базовый интерфейс --------------------------------------------------------

class OCRProvider:
    """Базовый контракт OCR-провайдера."""

    name = "base"

    def health_check(self) -> Dict[str, Any]:
        raise NotImplementedError

    def recognize(self, image: bytes, *, profile: Optional[str] = None,
                  options: Optional[Dict[str, Any]] = None) -> OCRResult:
        raise NotImplementedError

    def recognize_path(self, image_path: Path, *, profile: Optional[str] = None,
                       options: Optional[Dict[str, Any]] = None) -> OCRResult:
        """Распознать по пути (удобно для файловых движков)."""
        data = Path(image_path).read_bytes()
        return self.recognize(data, profile=profile, options=options)

    def close(self) -> None:
        return None

    def __enter__(self) -> "OCRProvider":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


# --- Portable RapidOCR-json ---------------------------------------------------

def _discover_executable() -> str:
    """Найти RapidOCR-json.exe в .tools/rapidocr-json/<version>/ (ТЗ §8.1)."""
    project_root = Path(__file__).resolve().parents[1]
    base = project_root / ".tools" / "rapidocr-json"
    if not base.is_dir():
        return ""
    candidates = sorted(base.glob("*/RapidOCR-json.exe"), reverse=True)
    for exe in candidates:
        if exe.is_file():
            return str(exe)
    return ""


class RapidOcrJsonProvider(OCRProvider):
    """Провайдер поверх portable RapidOCR-json EXE.

    Поддерживает два режима:

    * ``pipe`` — постоянный процесс, по одному JSON-запросу на строку (по умолчанию);
    * ``oneshot`` — запуск EXE на каждый запрос с путём к изображению в аргументах.

    Процесс запускается через список аргументов и ``shell=False``; отдельное
    консольное окно на Windows не открывается.
    """

    name = "rapidocr_json"

    def __init__(
        self,
        executable: Optional[str] = None,
        *,
        mode: str = "oneshot",
        profile: Optional[str] = None,
        secondary_profile: Optional[str] = None,
        dual_pass: Optional[bool] = None,
        models_dir: str = "models",
        models_root: Optional[str] = None,
        require_models_dir: bool = True,
        include_model_args: bool = True,
        startup_timeout_sec: Optional[float] = None,
        recognize_timeout_sec: Optional[float] = None,
        retry_count: int = 1,
        model_fingerprint: Optional[str] = None,
        extra_args: Optional[List[str]] = None,
        request_key: str = "image_path",
        response_exit_code_text: int = 100,
        response_exit_code_no_text: int = 101,
    ) -> None:
        self.executable = executable or getattr(settings, "OCR_EXECUTABLE", "") or ""
        if not self.executable:
            self.executable = _discover_executable()
        self.mode = mode
        self.profile = profile or getattr(settings, "OCR_MODEL_PROFILE", "cyrillic")
        self.secondary_profile = (
            secondary_profile if secondary_profile is not None
            else getattr(settings, "OCR_SECONDARY_PROFILE", "english")
        )
        if dual_pass is None:
            dual_pass = bool(getattr(settings, "OCR_DUAL_PASS", True))
        # Второй проход имеет смысл только для кириллического профиля.
        self.dual_pass = bool(dual_pass) and self.profile == "cyrillic" and bool(self.secondary_profile)
        self.models_dir = models_dir
        self.models_root = models_root
        self.require_models_dir = bool(require_models_dir)
        self.include_model_args = bool(include_model_args)
        self.startup_timeout_sec = float(startup_timeout_sec or getattr(settings, "OCR_STARTUP_TIMEOUT_SEC", 30))
        self.recognize_timeout_sec = float(recognize_timeout_sec or getattr(settings, "OCR_TIMEOUT_SEC", 60))
        self.retry_count = int(retry_count)
        self.model_fingerprint = model_fingerprint or getattr(settings, "OCR_MODEL_FINGERPRINT", "")
        self.engine_version = str(getattr(settings, "OCR_ENGINE_VERSION", "0.2.0"))
        self.extra_args = list(extra_args or [])
        self.request_key = request_key
        self._text_code = response_exit_code_text
        self._no_text_code = response_exit_code_no_text

        self._procs: Dict[str, subprocess.Popen] = {}
        self._queues: Dict[str, "queue.Queue[Optional[str]]"] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._proc_lock = threading.RLock()
        self._temp_files: List[Path] = []

    def _model_args(self, profile: str) -> List[str]:
        base = profile_args(profile, models_dir=self.models_dir) if self.include_model_args else []
        return base + list(self.extra_args)

    # --- окружение ------------------------------------------------------------

    def _popen_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
            "cwd": str(Path(self.executable).parent) if self.executable else None,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }
        if sys.platform == "win32":
            # Не открывать консольное окно при каждом вызове.
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
            startupinfo.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = startupinfo
        return kwargs

    def health_check(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "provider": self.name,
            "executable": self.executable,
            "mode": self.mode,
            "profile": self.profile,
            "ok": False,
        }
        if not self.executable or not Path(self.executable).is_file():
            info["error"] = "ocr_runtime_missing"
            return info
        info["ok"] = True
        return info

    # --- запуск процесса ------------------------------------------------------

    def _start_process(self, profile: str) -> subprocess.Popen:
        if not self.executable or not Path(self.executable).is_file():
            raise OCRProviderError("ocr_runtime_missing", f"Не найден EXE OCR: {self.executable!r}")
        models_path = Path(self.models_root) / self.models_dir if self.models_root else (
            Path(self.executable).parent / self.models_dir
        )
        if self.require_models_dir and not models_path.is_dir():
            raise OCRProviderError("ocr_model_missing", f"Нет каталога моделей: {models_path}")
        args = [self.executable, *self._model_args(profile)]
        proc = subprocess.Popen(args, **self._popen_kwargs())
        sink: "queue.Queue[Optional[str]]" = queue.Queue()
        self._queues[profile] = sink
        self._procs[profile] = proc
        thread = threading.Thread(target=self._pump_stdout, args=(proc, sink), daemon=True)
        self._threads[profile] = thread
        thread.start()
        self._verify_startup(proc)
        return proc

    @staticmethod
    def _pump_stdout(proc: subprocess.Popen, sink: "queue.Queue[Optional[str]]") -> None:
        """Читать stdout построчно в очередь, не блокируя основной поток."""
        try:
            if proc.stdout is None:
                return
            for line in proc.stdout:
                sink.put(line)
        except Exception:
            pass
        finally:
            sink.put(None)  # маркер завершения потока

    def _verify_startup(self, proc: subprocess.Popen) -> None:
        """Короткая проверка, что процесс не упал сразу после запуска."""
        deadline = time.monotonic() + min(self.startup_timeout_sec, 3.0)
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                err = ""
                try:
                    err = (proc.stderr.read() if proc.stderr else "") or ""
                except Exception:
                    err = ""
                raise OCRProviderError("ocr_invalid_response", f"Процесс завершился при старте: {err[:500]}")
            time.sleep(0.05)

    def _ensure_process(self, profile: str) -> Tuple[subprocess.Popen, "queue.Queue[Optional[str]]"]:
        with self._proc_lock:
            proc = self._procs.get(profile)
            if proc is None or proc.poll() is not None:
                self._kill_profile(profile)
                proc = self._start_process(profile)
            return proc, self._queues[profile]

    def _kill_profile(self, profile: str) -> None:
        proc = self._procs.pop(profile, None)
        self._queues.pop(profile, None)
        thread = self._threads.pop(profile, None)
        if proc is None:
            if thread is not None:
                thread.join(timeout=2)
            return
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
        finally:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
        if thread is not None:
            thread.join(timeout=2)

    def close(self) -> None:
        with self._proc_lock:
            for profile in list(self._procs.keys()):
                self._kill_profile(profile)
        for tmp in self._temp_files:
            try:
                tmp.unlink()
            except OSError:
                pass
        self._temp_files = []

    # --- распознавание --------------------------------------------------------

    def recognize(self, image: bytes, *, profile: Optional[str] = None,
                  options: Optional[Dict[str, Any]] = None) -> OCRResult:
        primary = profile or self.profile
        last_error: Optional[OCRProviderError] = None
        attempts = self.retry_count + 1
        for attempt in range(attempts):
            try:
                return self._recognize_once(image, primary=primary, options=options)
            except OCRProviderError as exc:
                last_error = exc
                logger.warning("OCR попытка %s/%s не удалась: %s", attempt + 1, attempts, exc.code)
                with self._proc_lock:
                    self._kill_profile(primary)
                    if self.dual_pass and self.secondary_profile:
                        self._kill_profile(self.secondary_profile)
                if exc.code in ("ocr_runtime_missing", "ocr_model_missing"):
                    break
        assert last_error is not None
        return OCRResult(
            status="unavailable" if last_error.code in ("ocr_runtime_missing", "ocr_model_missing") else "failed",
            engine=self.name, engine_version=self.engine_version, profile=primary,
            model_fingerprint=self.model_fingerprint,
            warnings=[f"{last_error.code}: {last_error.message}"],
        )

    def _write_temp_image(self, image: bytes) -> Path:
        fd, name = tempfile.mkstemp(suffix=".png", prefix="kb_ocr_")
        with os.fdopen(fd, "wb") as handle:
            handle.write(image)
        path = Path(name)
        self._temp_files.append(path)
        return path

    def _recognize_with(self, image_path: Path, profile: str) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
        if self.mode == "oneshot":
            return self._run_oneshot(image_path, profile)
        return self._run_pipe(image_path, profile)

    def _recognize_once(self, image: bytes, *, primary: str,
                        options: Optional[Dict[str, Any]]) -> OCRResult:
        image_path = self._write_temp_image(image)
        started = time.perf_counter()
        raw, code = self._recognize_with(image_path, primary)
        primary_result = self._normalize(raw, exit_code=code, profile=primary, duration_ms=0)
        if not self.dual_pass or not self.secondary_profile:
            primary_result.duration_ms = int((time.perf_counter() - started) * 1000)
            return primary_result
        # Второй проход (латиница/цифры) — только если первый дал текст.
        if primary_result.status != "success":
            primary_result.duration_ms = int((time.perf_counter() - started) * 1000)
            return primary_result
        try:
            raw2, code2 = self._recognize_with(image_path, self.secondary_profile)
            secondary_result = self._normalize(raw2, exit_code=code2,
                                               profile=self.secondary_profile, duration_ms=0)
        except OCRProviderError as exc:
            logger.warning("OCR: второй проход не удался (%s), оставлен основной результат", exc.code)
            primary_result.warnings.append(f"secondary_pass_failed:{exc.code}")
            primary_result.duration_ms = int((time.perf_counter() - started) * 1000)
            return primary_result
        merged = self._merge_dual(primary_result, secondary_result)
        merged.duration_ms = int((time.perf_counter() - started) * 1000)
        return merged

    def _merge_dual(self, primary: OCRResult, secondary: OCRResult) -> OCRResult:
        """Объединить чтения двух профилей (ТЗ §8.1, документировано).

        Основным остаётся кириллическое чтение. Для блоков, где основной текст
        состоит преимущественно из латиницы/цифр, а второй проход даёт более
        «латинское» и уверенное чтение, основной текст заменяется. Оба варианта
        сохраняются (``text`` и ``text_alt``), чтобы поиск видел точные имена.
        """
        if secondary.status != "success" or not secondary.blocks:
            return primary
        sec_blocks = list(secondary.blocks)
        sec_used: set = set()
        alt_texts: List[str] = []
        for block in primary.blocks:
            match_idx = self._best_overlap(block, sec_blocks, sec_used)
            if match_idx is None:
                continue
            alt = sec_blocks[match_idx]
            block.text_alt = alt.text
            cyr_ratio, lat_ratio = _script_ratio(block.text)
            alt_cyr, alt_lat = _script_ratio(alt.text)
            # Консервативная замена: только если в основном чтении НЕТ кириллицы
            # (чисто латинско-цифровой фрагмент), а второй проход увереннее/латиннее.
            if cyr_ratio == 0.0 and alt_lat > 0.5 and alt.confidence >= block.confidence - 0.15:
                alt.text_alt = block.text
                alt.source_profile = secondary.profile
                block.text, alt.text = alt.text, block.text
                block.confidence = alt.confidence
                block.text_alt = alt.text
            alt_texts.append(alt.text)
        # Пересобрать text_raw по итоговым блокам.
        primary.text_raw = "\n".join(b.text for b in primary.blocks)
        primary.text_raw_alt = "\n".join(t for t in alt_texts if t and t != primary.text_raw)
        primary.warnings.append("dual_pass_merged")
        return primary

    @staticmethod
    def _best_overlap(block: OCRBlock, candidates: List[OCRBlock], used: set) -> Optional[int]:
        if not block.polygon:
            return None
        bx = [p[0] for p in block.polygon]
        by = [p[1] for p in block.polygon]
        b_cx, b_cy = sum(bx) / len(bx), sum(by) / len(by)
        best_idx, best_dist = None, None
        for idx, cand in enumerate(candidates):
            if idx in used or not cand.polygon:
                continue
            cx = [p[0] for p in cand.polygon]
            cy = [p[1] for p in cand.polygon]
            c_cx, c_cy = sum(cx) / len(cx), sum(cy) / len(cy)
            dist = abs(b_cx - c_cx) + abs(b_cy - c_cy)
            if best_dist is None or dist < best_dist:
                best_idx, best_dist = idx, dist
        if best_idx is None or best_dist is None:
            return None
        # Близость: не дальше половины диагонали блока.
        span = max(max(bx) - min(bx), max(by) - min(by), 1.0)
        if best_dist > span * 0.5:
            return None
        used.add(best_idx)
        return best_idx

    def _run_oneshot(self, image_path: Path, profile: str) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
        # В oneshot нет отдельного этапа старта процесса: проверяем EXE/модели здесь.
        if not self.executable or not Path(self.executable).is_file():
            raise OCRProviderError("ocr_runtime_missing", f"Не найден EXE OCR: {self.executable!r}")
        models_path = Path(self.models_root) / self.models_dir if self.models_root else (
            Path(self.executable).parent / self.models_dir
        )
        if self.require_models_dir and not models_path.is_dir():
            raise OCRProviderError("ocr_model_missing", f"Нет каталога моделей: {models_path}")
        args = [self.executable, *self._model_args(profile), f"--image={image_path}"]
        kwargs = self._popen_kwargs()
        try:
            proc = subprocess.run(
                args, capture_output=True, timeout=self.recognize_timeout_sec, shell=False,
                cwd=kwargs.get("cwd"), text=True, encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            raise OCRProviderError(
                "ocr_timeout", f"Таймаут распознавания OCR ({self.recognize_timeout_sec}с)"
            ) from exc
        except (FileNotFoundError, OSError) as exc:
            raise OCRProviderError("ocr_runtime_missing", f"Не удалось запустить EXE OCR: {exc}") from exc
        return self._extract_json(proc.stdout or ""), proc.returncode

    def _run_pipe(self, image_path: Path, profile: str) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
        proc, sink = self._ensure_process(profile)
        line = json.dumps({self.request_key: str(image_path)}, ensure_ascii=False) + "\n"
        try:
            assert proc.stdin is not None
            proc.stdin.write(line)
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise OCRProviderError("ocr_process_died", str(exc)) from exc
        return self._read_response(proc, sink)

    def _read_response(self, proc: subprocess.Popen,
                       sink: "queue.Queue[Optional[str]]") -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
        deadline = time.monotonic() + self.recognize_timeout_sec
        while time.monotonic() < deadline:
            if proc.poll() is not None and sink.empty():
                err = ""
                try:
                    err = (proc.stderr.read() if proc.stderr else "") or ""
                except Exception:
                    err = ""
                raise OCRProviderError("ocr_process_died", f"Процесс OCR завершился: {err[:500]}")
            try:
                line = sink.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                raise OCRProviderError("ocr_process_died", "Поток stdout OCR завершился")
            payload = self._extract_json(line)
            if payload is not None:
                return payload, None
        raise OCRProviderError("ocr_timeout", "Таймаут ожидания ответа OCR")

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        for raw_line in text.splitlines():
            candidate = raw_line.strip()
            if not candidate or not candidate.startswith("{"):
                continue
            try:
                obj = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
        return None

    def _normalize(self, payload: Optional[Dict[str, Any]], *, exit_code: Optional[int],
                   profile: str, duration_ms: int) -> OCRResult:
        """Преобразовать upstream-ответ в схему приложения (ТЗ §8.2)."""
        if payload is None:
            if exit_code == self._no_text_code:
                return OCRResult(status="no_text", engine=self.name,
                                 engine_version=self.engine_version,
                                 model_fingerprint=self.model_fingerprint, profile=profile,
                                 duration_ms=duration_ms)
            return OCRResult(status="failed", engine=self.name,
                             engine_version=self.engine_version, profile=profile,
                             model_fingerprint=self.model_fingerprint,
                             warnings=["ocr_invalid_response"], duration_ms=duration_ms)

        code = payload.get("code")
        if code == self._no_text_code:
            return OCRResult(status="no_text", engine=self.name,
                             engine_version=self.engine_version,
                             model_fingerprint=self.model_fingerprint, profile=profile,
                             duration_ms=duration_ms)

        raw_items: List[Any] = []
        if isinstance(payload.get("data"), list):
            raw_items = payload["data"]
        elif isinstance(payload.get("data"), dict):
            d = payload["data"]
            raw_items = d.get("text_blocks") or d.get("blocks") or d.get("items") or []
        if not raw_items:
            raw_items = payload.get("text_blocks") or payload.get("blocks") or payload.get("items") or []
        blocks: List[OCRBlock] = []
        for idx, item in enumerate(raw_items):
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("label") or "").strip()
                box = item.get("box") or item.get("polygon") or item.get("points") or []
                score = float(item.get("score") or item.get("confidence") or 0.0)
            elif isinstance(item, (list, tuple)) and len(item) >= 3:
                box, text, score = item[0], str(item[1]), float(item[2])
            else:
                continue
            if not text:
                continue
            polygon = self._normalize_polygon(box)
            blocks.append(OCRBlock(text=text, polygon=polygon, confidence=score,
                                   reading_order=idx, source_profile=profile))

        text_raw = "\n".join(b.text for b in blocks)
        status = "success" if blocks else "no_text"
        width = payload.get("image_width")
        height = payload.get("image_height")
        if exit_code == self._no_text_code and not blocks:
            status = "no_text"
        return OCRResult(
            status=status, engine=self.name, engine_version=self.engine_version,
            model_fingerprint=self.model_fingerprint, profile=profile,
            image_width=width, image_height=height, text_raw=text_raw, blocks=blocks,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _normalize_polygon(box: Any) -> List[List[float]]:
        if not box:
            return []
        try:
            if len(box) == 4 and all(isinstance(p, (int, float)) for p in box):
                x1, y1, x2, y2 = box
                return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
            if isinstance(box[0], (list, tuple)):
                return [[float(p[0]), float(p[1])] for p in box]
        except (TypeError, IndexError, ValueError):
            return []
        return []


# --- Fake-провайдер для тестов ------------------------------------------------

class FakeOCRProvider(OCRProvider):
    """Детерминированный провайдер без внешнего процесса (unit-тесты)."""

    name = "fake_ocr"

    def __init__(self, *, text: str = "", blocks: Optional[List[OCRBlock]] = None,
                 status: Optional[str] = None, fail_times: int = 0,
                 fingerprint: str = "sha256:fake", version: str = "0.2.0",
                 no_text: bool = False, invalid_json: bool = False) -> None:
        self._text = text
        self._blocks = blocks
        self._status = status
        self._fail_times = fail_times
        self._calls = 0
        self._fingerprint = fingerprint
        self._version = version
        self._no_text = no_text
        self._invalid_json = invalid_json
        self.closed = False

    @property
    def call_count(self) -> int:
        return self._calls

    def health_check(self) -> Dict[str, Any]:
        return {"provider": self.name, "ok": True, "fingerprint": self._fingerprint}

    def recognize(self, image: bytes, *, profile: Optional[str] = None,
                  options: Optional[Dict[str, Any]] = None) -> OCRResult:
        self._calls += 1
        if self._calls <= self._fail_times:
            return OCRResult(status="failed", engine=self.name, engine_version=self._version,
                             profile=profile or "cyrillic", warnings=["ocr_failed_once"])
        if self._invalid_json:
            return OCRResult(status="failed", engine=self.name, engine_version=self._version,
                             profile=profile or "cyrillic", warnings=["ocr_invalid_response"])
        blocks = list(self._blocks or [])
        if not blocks and self._text:
            for i, line in enumerate(self._text.splitlines()):
                if line.strip():
                    blocks.append(OCRBlock(text=line.strip(), confidence=0.95, reading_order=i))
        text_raw = self._text or "\n".join(b.text for b in blocks)
        if self._no_text or (self._status == "no_text"):
            status = "no_text"
        elif self._status:
            status = self._status
        else:
            status = "success" if blocks else "no_text"
        return OCRResult(status=status, engine=self.name, engine_version=self._version,
                         model_fingerprint=self._fingerprint, profile=profile or "cyrillic",
                         text_raw=text_raw if status != "no_text" else "", blocks=blocks)

    def close(self) -> None:
        self.closed = True


def build_ocr_provider(**overrides: Any) -> OCRProvider:
    """Собрать OCR-провайдер по настройкам (``OCR_PROVIDER``)."""
    provider = overrides.pop("provider", None) or getattr(settings, "OCR_PROVIDER", "rapidocr_json")
    if provider in ("fake", "fake_ocr"):
        return FakeOCRProvider(**overrides)
    mode = str(getattr(settings, "OCR_MODE", "oneshot") or "oneshot").strip().lower()
    if mode == "pipe":
        # RapidOCR-json 0.2.0 не умеет stdin-протокол: процесс не отвечает,
        # жжёт 100% CPU и уходит в ocr_timeout. Работает только oneshot (--image=).
        logger.warning(
            "OCR_MODE=pipe не поддерживается движком RapidOCR-json %s: используем oneshot",
            getattr(settings, "OCR_ENGINE_VERSION", ""),
        )
        mode = "oneshot"
    return RapidOcrJsonProvider(mode=mode, **overrides)
