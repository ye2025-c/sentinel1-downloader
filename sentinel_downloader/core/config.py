#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
常量与配置读写
────────────────────────────────────────────────────────
集中存放各类 URL / 预设区域 / 产品类型常量，并提供配置文件读写。

CONFIG_FILE 指向项目根目录（本文件位于 core/ 子目录，故需向上一级）的
s1_config.json。该文件含账号邮箱与本地保存路径，不纳入版本管理。
"""

import os
import json

# ── 接口地址 ──────────────────────────────────────────────────────────
TOKEN_URL    = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SEARCH_URL   = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
DOWNLOAD_URL = "https://download.dataspace.copernicus.eu/odata/v1/Products({id})/$value"

# ── 配置文件路径（项目根目录，即 core/ 的上一级）──────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.normpath(os.path.join(BASE_DIR, "..", "s1_config.json"))

# ── 研究区 AOI 预设（WKT）─────────────────────────────────────────────
AOI_PRESETS = {
    "密云水库区":       "POLYGON((116.8 40.1,117.5 40.1,117.5 40.8,116.8 40.8,116.8 40.1))",
    "怀柔-密云山洪区":  "POLYGON((116.4 40.2,117.0 40.2,117.0 40.7,116.4 40.7,116.4 40.2))",
    "承德兴隆县":       "POLYGON((117.3 40.3,117.9 40.3,117.9 40.8,117.3 40.8,117.3 40.3))",
    "海河北系全域":     "POLYGON((115.8 39.8,118.5 39.8,118.5 41.2,115.8 41.2,115.8 39.8))",
}

# ── 产品类型 ──────────────────────────────────────────────────────────
PRODUCT_TYPES = {
    "Level-1 GRD（推荐，强度图）": "IW_GRDH_1S",
    "Level-1 SLC（相干分析）":     "IW_SLC__1S",
}


def save_config(data: dict) -> None:
    """将配置字典写入 s1_config.json（UTF-8，缩进2）。"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_config() -> dict:
    """读取 s1_config.json，返回字典；文件不存在或解析失败时返回空字典。"""
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
