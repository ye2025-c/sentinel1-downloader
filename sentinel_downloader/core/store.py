#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载历史与搜索缓存（JSON 存储，无外部依赖）
────────────────────────────────────────────────────────
HistoryStore : 下载历史，记录每景的下载结果（data/download_history.json）
SearchCache  : 搜索结果缓存，TTL=24h（data/search_cache.json）

设计原则：
  - 零依赖：只用标准库 json / hashlib / threading / pathlib / datetime
  - 线程安全：所有写操作加 Lock，适应并行下载场景
  - 容错：任何读写异常都静默处理，绝不影响主流程
"""

import json
import hashlib
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

from core.config import DATA_DIR

_HISTORY_FILE      = Path(DATA_DIR) / "download_history.json"
_SEARCH_CACHE_FILE = Path(DATA_DIR) / "search_cache.json"


# ─────────────────────────────────────────────────────────
#  下载历史
# ─────────────────────────────────────────────────────────
class HistoryStore:
    """下载历史 JSON 存储，线程安全。

    每条记录对应一次下载，同一 product_id 重新下载会覆盖旧记录。
    """
    _lock = Lock()

    @classmethod
    def _load(cls) -> dict:
        if not _HISTORY_FILE.exists():
            return {"version": "1.0", "records": []}
        try:
            return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"version": "1.0", "records": []}

    @classmethod
    def _save(cls, data: dict):
        try:
            _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            _HISTORY_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    @classmethod
    def add(cls, product_id: str, product_name: str, size_str: str, save_dir: str,
            footprint: str = ""):
        """新增或覆盖一条下载记录（初始状态 downloading）。"""
        record = {
            "product_id":   product_id,
            "product_name": product_name,
            "size":         size_str,
            "save_dir":     save_dir,
            "footprint":    footprint,
            "status":       "downloading",
            "started_at":   datetime.now().isoformat(timespec="seconds"),
            "finished_at":  None,
        }
        with cls._lock:
            data = cls._load()
            # 同一产品覆盖旧记录，避免重复
            data["records"] = [r for r in data["records"]
                               if r.get("product_id") != product_id]
            data["records"].append(record)
            cls._save(data)

    @classmethod
    def update_status(cls, product_id: str, status: str):
        """将指定产品的状态更新为 completed 或 failed。"""
        with cls._lock:
            data = cls._load()
            for r in data["records"]:
                if r.get("product_id") == product_id:
                    r["status"]      = status
                    r["finished_at"] = datetime.now().isoformat(timespec="seconds")
                    break
            cls._save(data)

    @classmethod
    def get_all(cls) -> list:
        """返回所有历史记录，最新在前。"""
        try:
            return list(reversed(cls._load()["records"]))
        except Exception:
            return []

    @classmethod
    def downloaded_ids(cls) -> set:
        """返回所有已成功下载的 product_id 集合，供搜索结果打标记用。"""
        try:
            return {r["product_id"] for r in cls._load()["records"]
                    if r.get("status") == "completed"}
        except Exception:
            return set()

    @classmethod
    def clear(cls):
        """清空所有历史记录。"""
        with cls._lock:
            cls._save({"version": "1.0", "records": []})


# ─────────────────────────────────────────────────────────
#  搜索结果缓存
# ─────────────────────────────────────────────────────────
class SearchCache:
    """搜索结果 JSON 缓存，默认 TTL=24h。

    仅缓存条件搜索（_do_search），按产品名搜索不缓存。
    """
    _lock     = Lock()
    TTL_HOURS = 24

    @classmethod
    def _make_key(cls, params: dict) -> str:
        raw = json.dumps(params, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()

    @classmethod
    def _load(cls) -> dict:
        if not _SEARCH_CACHE_FILE.exists():
            return {"version": "1.0", "entries": []}
        try:
            return json.loads(_SEARCH_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"version": "1.0", "entries": []}

    @classmethod
    def _save(cls, data: dict):
        try:
            _SEARCH_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _SEARCH_CACHE_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    @classmethod
    def get(cls, params: dict):
        """命中且未过期时返回 Product 列表，否则返回 None。"""
        from core.models import Product
        key  = cls._make_key(params)
        now  = datetime.now()
        try:
            for entry in cls._load()["entries"]:
                if entry.get("cache_key") == key:
                    if datetime.fromisoformat(entry["expires_at"]) > now:
                        return [Product(**r) for r in entry["results"]]
        except Exception:
            pass
        return None

    @classmethod
    def set(cls, params: dict, results: list):
        """将搜索结果（Product 列表）写入缓存。"""
        key = cls._make_key(params)
        now = datetime.now()
        entry = {
            "cache_key":    key,
            "params":       params,
            "results":      [asdict(p) for p in results],
            "result_count": len(results),
            "cached_at":    now.isoformat(timespec="seconds"),
            "expires_at":   (now + timedelta(hours=cls.TTL_HOURS)).isoformat(timespec="seconds"),
        }
        with cls._lock:
            data = cls._load()
            for i, e in enumerate(data["entries"]):
                if e.get("cache_key") == key:
                    data["entries"][i] = entry
                    break
            else:
                data["entries"].append(entry)
            cls._save(data)

    @classmethod
    def clear_expired(cls):
        """清理过期条目，程序启动时调用一次。"""
        now = datetime.now()
        with cls._lock:
            data = cls._load()
            before = len(data["entries"])
            data["entries"] = [
                e for e in data["entries"]
                if datetime.fromisoformat(e.get("expires_at", "2000-01-01")) > now
            ]
            if len(data["entries"]) < before:
                cls._save(data)

    @classmethod
    def clear(cls):
        """清空所有缓存条目。"""
        with cls._lock:
            cls._save({"version": "1.0", "entries": []})
