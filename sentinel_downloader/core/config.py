#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
常量与配置读写
────────────────────────────────────────────────────────
集中存放各类 URL / 预设区域 / 产品类型常量，并提供配置文件读写。

本地数据统一放在项目内 data/ 目录（不纳入版本管理）：
    data/config.json            账号邮箱、保存路径、默认时间范围
    data/logs/                  下载日志（按天分文件）
    data/download_history.json  下载历史（V3.2 引入）
    data/search_cache.json      搜索结果缓存，TTL=24h（V3.2 引入）

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
