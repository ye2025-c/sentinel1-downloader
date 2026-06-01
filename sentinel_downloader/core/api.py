#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copernicus Data Space API 封装
────────────────────────────────────────────────────────
负责 Token 获取/刷新与 OData 影像检索，不含任何 UI 依赖。
下载逻辑见 core/downloader.py。
"""

import time
import threading

import requests

from core.config import TOKEN_URL, SEARCH_URL


class CopernicusAPI:
    def __init__(self):
        self.token = None
        self.token_time = 0
        self._token_lock = threading.Lock()   # 防止多线程并发刷新 token

    def get_token(self, username, password):
        resp = requests.post(TOKEN_URL, data={
            "client_id": "cdse-public",
            "grant_type": "password",
            "username": username,
            "password": password,
        }, timeout=30)
        resp.raise_for_status()
        self.token = resp.json()["access_token"]
        self.token_time = time.time()
        return self.token

    def refresh_if_needed(self, username, password):
        """Token 有效期约10分钟，提前刷新。加锁确保多 worker 并发时只刷新一次。"""
        with self._token_lock:
            if time.time() - self.token_time > 540:
                self.get_token(username, password)
        return self.token

    def search(self, wkt, date_from, date_to, product_type, max_results=100,
               platforms=None, orbit_dir=None, polarisation=None,
               relative_orbit=None, online_only=False,
               acq_mode=None, absolute_orbit=None,
               name_filter=None):
        """
        参数说明
        --------
        orbit_dir       : "ASCENDING" | "DESCENDING" | None（服务端过滤）
        polarisation    : "VV&VH" | "VV" | "VH" | "HH&HV" | None（服务端过滤）
        relative_orbit  : int | None  相对轨道号（服务端过滤）
        online_only     : bool  True=仅在线产品（服务端过滤）
        platforms       : list[str]  如 ["S1A","S1B"]（客户端名称前缀过滤）
        """
        # ── 按产品名精确搜索（优先级最高，有值时跳过其他 filter）────────
        if name_filter:
            results = []
            for raw_name in name_filter:
                # 去掉 .SAFE 后缀（官网复制的名称可能带也可能不带）
                clean = raw_name.strip().removesuffix(".SAFE").strip()
                if not clean:
                    continue
                # OData 精确匹配：Name eq '...' 或 Name eq '....SAFE'
                # 服务端存储的名称带 .SAFE，所以查询时加上
                f_with    = f"Name eq '{clean}.SAFE'"
                f_without = f"Name eq '{clean}'"
                for name_f in (f_with, f_without):
                    url = (f"{SEARCH_URL}?$filter={requests.utils.quote(name_f, safe='')}"
                           f"&$expand=Attributes&$top=1")
                    resp = requests.get(
                        url,
                        headers={"Authorization": f"Bearer {self.token}"},
                        timeout=60
                    )
                    resp.raise_for_status()
                    hits = resp.json().get("value", [])
                    if hits:
                        results.extend(hits)
                        break   # 找到了就不用试另一种格式
            return results

        def _str_attr(name, value):
            return (f"Attributes/OData.CSC.StringAttribute/any("
                    f"att:att/Name eq '{name}' and "
                    f"att/OData.CSC.StringAttribute/Value eq '{value}')")

        def _int_attr(name, value):
            return (f"Attributes/OData.CSC.IntegerAttribute/any("
                    f"att:att/Name eq '{name}' and "
                    f"att/OData.CSC.IntegerAttribute/Value eq {value})")

        filters = [
            "Collection/Name eq 'SENTINEL-1'",
            _str_attr("productType", product_type),
            f"ContentDate/Start gt {date_from}T00:00:00.000Z",
            f"ContentDate/Start lt {date_to}T23:59:59.999Z",
            f"OData.CSC.Intersects(area=geography'SRID=4326;{wkt}')",
        ]

        # ── 服务端筛选：轨道方向 ──────────────────────────────────────
        if orbit_dir and orbit_dir in ("ASCENDING", "DESCENDING"):
            filters.append(_str_attr("orbitDirection", orbit_dir))

        # ── 服务端筛选：极化方式 ──────────────────────────────────────
        # OData 值示例: "VV&VH"  "VV"  "HH&HV"
        if polarisation:
            filters.append(_str_attr("polarisationChannels", polarisation))

        # ── 服务端筛选：相对轨道号 ────────────────────────────────────
        if relative_orbit is not None:
            try:
                filters.append(_int_attr("relativeOrbitNumber", int(relative_orbit)))
            except (ValueError, TypeError):
                pass

        # ── 服务端筛选：仅在线产品 ────────────────────────────────────
        if online_only:
            filters.append("Online eq true")

        # ── 服务端筛选：成像模式 ─────────────────────────────────────
        if acq_mode:
            filters.append(_str_attr("operationalMode", acq_mode))

        # ── 服务端筛选：绝对轨道号（支持多个，OR 关系）────────────────
        if absolute_orbit:
            abs_parts = [_int_attr("absoluteOrbitNumber", int(n))
                         for n in absolute_orbit if str(n).strip().isdigit()]
            if len(abs_parts) == 1:
                filters.append(abs_parts[0])
            elif len(abs_parts) > 1:
                filters.append("(" + " or ".join(abs_parts) + ")")

        url = (f"{SEARCH_URL}?$filter={requests.utils.quote(' and '.join(filters), safe='')}"
               f"&$expand=Attributes"
               f"&$top={max_results}&$orderby=ContentDate/Start desc")

        resp = requests.get(url, headers={"Authorization": f"Bearer {self.token}"}, timeout=60)
        resp.raise_for_status()
        products = resp.json().get("value", [])

        # ── 客户端过滤：卫星平台（OData 不支持 startswith 在此场景）────
        if platforms:
            products = [p for p in products
                        if any(p.get("Name", "").startswith(pl) for pl in platforms)]

        return products
