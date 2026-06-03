#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
常量与配置读写
────────────────────────────────────────────────────────
集中存放各类 URL / 预设区域 / 产品类型常量，并提供配置文件读写。

本地数据统一放在项目内 data/ 目录（不纳入版本管理）：
    data/config.json            账号邮箱、保存路径、默认时间范围、settings 设置项
    data/logs/                  下载日志（按天分文件）
    data/download_history.json  下载历史（V3.2 引入）
    data/search_cache.json      搜索结果缓存，TTL 可设（V3.2 引入）
    data/queue.json             下载队列持久化（V4.1 引入）

可调设置统一存在 config.json 的 "settings" 子字典，唯一真相源是本文件的
_DEFAULT_SETTINGS：缺键自动回退默认值，向后兼容老配置（V4.1 引入）。

历史版本把配置存在 sentinel_downloader/s1_config.json，
load_config 仍会回退读取并自动迁移到 data/config.json，老用户不丢配置。
"""

import os
import json
from datetime import datetime

# ── 接口地址 ──────────────────────────────────────────────────────────
TOKEN_URL    = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SEARCH_URL   = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
DOWNLOAD_URL = "https://download.dataspace.copernicus.eu/odata/v1/Products({id})/$value"

# ── 路径（core/ 的上一级即 sentinel_downloader/）──────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.normpath(os.path.join(BASE_DIR, ".."))
DATA_DIR    = os.path.join(PROJECT_DIR, "data")
LOG_DIR     = os.path.join(DATA_DIR, "logs")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

# 历史配置位置，仅用于一次性迁移
_OLD_CONFIG_FILE = os.path.join(PROJECT_DIR, "s1_config.json")

# ── 研究区 AOI 预设（WKT）─────────────────────────────────────────────
AOI_PRESETS = {
    "密云水库区":       "POLYGON((116.8 40.1,117.5 40.1,117.5 40.8,116.8 40.8,116.8 40.1))",
    "怀柔-密云山洪区":  "POLYGON((116.4 40.2,117.0 40.2,117.0 40.7,116.4 40.7,116.4 40.2))",
    "承德兴隆县":       "POLYGON((117.3 40.3,117.9 40.3,117.9 40.8,117.3 40.8,117.3 40.3))",
    "海河北系全域":     "POLYGON((115.8 39.8,118.5 39.8,118.5 41.2,115.8 41.2,115.8 39.8))",
}

# ── Sentinel-1 产品类型 ────────────────────────────────────────────────
PRODUCT_TYPES = {
    "Level-1 GRD（推荐，强度图）": "IW_GRDH_1S",
    "Level-1 SLC（相干分析）":     "IW_SLC__1S",
}

# ── Sentinel-2 产品类型 ────────────────────────────────────────────────
S2_PRODUCT_TYPES = {
    "不限（L1C + L2A）": None,
    "L2A（大气校正，推荐）": "S2MSI2A",
    "L1C（大气层顶反射率）": "S2MSI1C",
}


def _ensure_data_dirs() -> None:
    """确保 data/ 与 data/logs/ 存在。"""
    os.makedirs(LOG_DIR, exist_ok=True)


def save_config(data: dict) -> None:
    """将配置字典写入 data/config.json（UTF-8，缩进2）。"""
    _ensure_data_dirs()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_config() -> dict:
    """读取配置；优先 data/config.json，缺失时回退旧 s1_config.json 并自动迁移。

    文件不存在或解析失败时返回空字典。
    """
    # 新位置
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # 旧位置：读取并一次性迁移到 data/config.json
    if os.path.exists(_OLD_CONFIG_FILE):
        try:
            with open(_OLD_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            return {}
        try:
            save_config(cfg)   # 迁移到新位置，后续以新位置为准
        except Exception:
            pass
        return cfg

    return {}


def log_line(msg: str) -> None:
    """把一行日志追加到 data/logs/download_YYYYMMDD.log（带时间戳）。

    纯文本、按天分文件；写盘失败静默忽略，绝不影响下载主流程。
    """
    try:
        _ensure_data_dirs()
        fname = f"download_{datetime.now():%Y%m%d}.log"
        with open(os.path.join(LOG_DIR, fname), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {msg}\n")
    except Exception:
        pass


# ── 可调设置（V4.1）──────────────────────────────────────────────────
# 所有写死的"魔法数"集中到这里，作为唯一默认真相源。设置页读写 config.json
# 的 "settings" 子字典；任何缺失的键都回退到下表，老配置无缝兼容。
_DEFAULT_SETTINGS = {
    "parallel":         3,      # 默认并行下载景数（CDSE）
    "max_retry":        5,      # 单文件最大重试次数
    "connect_timeout":  15,     # TCP 连接超时（秒）
    "read_timeout":     120,    # 两次数据块之间的读超时（秒）
    "nasa_delay":       2,      # NASA 文件间礼貌延迟（秒）
    "cache_ttl_hours":  24,     # 搜索结果缓存有效期（小时）
    "verify_integrity": True,   # 下载后做 ZIP 结构校验
    "log_keep_days":    30,     # 日志保留天数（超期自动清理；0=不清理）
}


def get_setting(key: str):
    """读取单个设置项；缺失/异常时回退默认值。"""
    try:
        val = load_config().get("settings", {}).get(key)
        return val if val is not None else _DEFAULT_SETTINGS.get(key)
    except Exception:
        return _DEFAULT_SETTINGS.get(key)


def get_settings() -> dict:
    """返回完整设置字典（默认值 + 用户覆盖）。供设置页填充。"""
    try:
        user = load_config().get("settings", {})
    except Exception:
        user = {}
    return {k: user.get(k, v) for k, v in _DEFAULT_SETTINGS.items()}


def save_settings(new_settings: dict) -> None:
    """合并并保存设置项到 config.json（只写已知键，未知键忽略）。"""
    cfg = load_config() or {}
    merged = {k: v for k, v in _DEFAULT_SETTINGS.items()}
    merged.update(cfg.get("settings", {}))
    merged.update({k: new_settings[k] for k in _DEFAULT_SETTINGS if k in new_settings})
    cfg["settings"] = merged
    save_config(cfg)


# ── NASA 下载后裁剪（瘦身）配置 ──────────────────────────────────────
# 与 settings 分开存：settings 放标量调参，这里放结构化的裁剪配置。
# 存在 config.json 的 "nasa_proc" 子字典；缺键 / bbox 子键回退下表默认。
_DEFAULT_NASA_PROC = {
    "enabled":         False,
    "delete_original": False,
    "bbox": {"lat_min": 39.8, "lat_max": 41.2,
             "lon_min": 115.8, "lon_max": 118.5},   # 默认海河北系，可改
}


def get_nasa_proc() -> dict:
    """读取 NASA 下载后裁剪配置（缺键 / bbox 子键自动回退默认）。"""
    try:
        user = load_config().get("nasa_proc", {}) or {}
    except Exception:
        user = {}
    out = {
        "enabled":         bool(user.get("enabled", _DEFAULT_NASA_PROC["enabled"])),
        "delete_original": bool(user.get("delete_original",
                                         _DEFAULT_NASA_PROC["delete_original"])),
    }
    bb = dict(_DEFAULT_NASA_PROC["bbox"])
    if isinstance(user.get("bbox"), dict):
        bb.update({k: user["bbox"][k] for k in bb if k in user["bbox"]})
    out["bbox"] = bb
    return out


def save_nasa_proc(proc: dict) -> None:
    """合并保存 NASA 裁剪配置到 config.json 的 nasa_proc 子字典（不动其它键）。"""
    cfg = load_config() or {}
    cur = cfg.get("nasa_proc", {}) or {}
    if "enabled" in proc:
        cur["enabled"] = bool(proc["enabled"])
    if "delete_original" in proc:
        cur["delete_original"] = bool(proc["delete_original"])
    if isinstance(proc.get("bbox"), dict):
        cur["bbox"] = {k: float(proc["bbox"][k])
                       for k in ("lat_min", "lat_max", "lon_min", "lon_max")
                       if k in proc["bbox"]}
    cfg["nasa_proc"] = cur
    save_config(cfg)


def purge_old_logs(days: int = None) -> None:
    """删除 data/logs/ 下修改时间超过保留天数的日志文件。失败静默。

    程序启动时调用一次。days=0 或 None→读取设置；<=0 表示不清理。
    """
    try:
        if days is None:
            days = get_setting("log_keep_days")
        if not days or days <= 0:
            return
        cutoff = datetime.now().timestamp() - days * 86400
        for fn in os.listdir(LOG_DIR):
            fp = os.path.join(LOG_DIR, fn)
            if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                os.remove(fp)
    except Exception:
        pass
