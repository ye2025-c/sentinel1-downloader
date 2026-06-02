#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sentinel-2 数据检索（Copernicus Data Space Ecosystem）
────────────────────────────────────────────────────────
SentinelS2API 继承 CopernicusAPI，认证 / 下载 URL 与 S1 完全相同，
只重写 search() 以支持 S2 专用参数（云量、处理级别、Tile ID）。
"""

import requests

from core.api import CopernicusAPI
from core.config import SEARCH_URL
from core.models import Product


class SentinelS2API(CopernicusAPI):
    """Sentinel-2 数据源。认证、下载内核与 S1 共用，只有搜索逻辑不同。"""

    name = "Copernicus CDSE (Sentinel-2)"

    def search(self, wkt, date_from, date_to, max_results=100,
               platforms=None, cloud_cover_max=None, tile_id=None,
               online_only=False, processing_level=None):
        """
        参数说明
        --------
        cloud_cover_max  : float | None  最大云量百分比（0-100），None=不限
        tile_id          : str | None    MGRS Tile，如 "T50TML"，None=不限
        online_only      : bool          True=仅在线产品
        processing_level : str | None    "S2MSI2A" / "S2MSI1C" / None=不限
        platforms        : list[str]     如 ["S2A","S2B"]，客户端过滤
        """
        def _str_attr(name, value):
            return (f"Attributes/OData.CSC.StringAttribute/any("
                    f"att:att/Name eq '{name}' and "
                    f"att/OData.CSC.StringAttribute/Value eq '{value}')")

        def _dbl_attr_lt(name, value):
            return (f"Attributes/OData.CSC.DoubleAttribute/any("
                    f"att:att/Name eq '{name}' and "
                    f"att/OData.CSC.DoubleAttribute/Value lt {value})")

        filters = [
            "Collection/Name eq 'SENTINEL-2'",
            f"ContentDate/Start gt {date_from}T00:00:00.000Z",
            f"ContentDate/Start lt {date_to}T23:59:59.999Z",
        ]

        if wkt:
            filters.append(f"OData.CSC.Intersects(area=geography'SRID=4326;{wkt}')")

        # ── 处理级别（L2A / L1C）────────────────────────────
        if processing_level:
            filters.append(_str_attr("productType", processing_level))

        # ── 最大云量 ─────────────────────────────────────────
        if cloud_cover_max is not None:
            filters.append(_dbl_attr_lt("cloudCover", float(cloud_cover_max)))

        # ── Tile ID ──────────────────────────────────────────
        if tile_id and tile_id.strip():
            clean_tile = tile_id.strip().upper().lstrip("T")
            filters.append(_str_attr("tileId", clean_tile))

        # ── 仅在线产品 ────────────────────────────────────────
        if online_only:
            filters.append("Online eq true")

        url = (f"{SEARCH_URL}?$filter={requests.utils.quote(' and '.join(filters), safe='')}"
               f"&$expand=Attributes"
               f"&$top={max_results}&$orderby=ContentDate/Start desc")

        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=60
        )
        resp.raise_for_status()
        products = resp.json().get("value", [])

        # ── 客户端过滤：卫星平台 ──────────────────────────────
        if platforms:
            products = [p for p in products
                        if any(p.get("Name", "").startswith(pl) for pl in platforms)]

        return [Product.from_odata(p) for p in products]
