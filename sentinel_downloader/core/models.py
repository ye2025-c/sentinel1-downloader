#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据模型
────────────────────────────────────────────────────────
把 OData 返回的裸 dict 收敛成类型化对象，解析逻辑集中在
Product.from_odata() 一处。UI 渲染、CSV 导出、下载队列都用
同一个 Product，后续加字段只改这里。

设计原则：保持简单。只放检索 / 展示 / 下载真正用到的字段，
不堆砌冗余字段（下载 URL 由 id 构造，不单独存储）。
"""

import re
from dataclasses import dataclass

# OData 默认大小回退：单景 S1 GRD 约 1.7 GB（部分检索结果不含 ContentLength）
_DEFAULT_SIZE_BYTES = 1700 * 1024 * 1024

_ORBIT_SHORT = {"ASCENDING": "ASC", "DESCENDING": "DESC"}


@dataclass
class Product:
    """一景遥感影像产品。字段均为展示友好的字符串 / 数值，便于直接渲染与导出。"""
    product_id: str          # OData Id，下载与去重的唯一键
    name: str                # 产品名（含或不含 .SAFE）
    acquisition_time: str    # 感测时间 UTC，形如 "2025-07-20 12:34"
    platform: str            # S1A / S1B / S1C
    mode: str                # IW / EW / SM / WV
    polarization: str        # VV&VH / VV / HH&HV ...
    orbit_direction: str     # ASC / DESC（已简写）
    relative_orbit: str      # 相对轨道号（字符串，缺失为 "—"）
    absolute_orbit: str      # 绝对轨道号（字符串，缺失为 "—"）
    size_gb: float           # 文件大小（GB）
    online: bool             # True=在线可直接下载，False=归档
    footprint: str = ""      # 影像覆盖范围 WKT（来自 GeoFootprint，V3.3 引入）
    cloud_cover: float = -1.0  # 云量百分比（S2 专用，-1 表示 N/A）
    tile_id: str = ""          # MGRS Tile ID（S2 专用，如 T50TML）

    # ── 展示辅助 ─────────────────────────────────────────────
    @property
    def size_str(self) -> str:
        return f"{self.size_gb:.1f} GB"

    @property
    def online_str(self) -> str:
        return "✓在线" if self.online else "归档"

    @property
    def cloud_cover_str(self) -> str:
        return f"{self.cloud_cover:.0f}%" if self.cloud_cover >= 0 else "—"

    # ── 解析辅助 ────────────────────────────────────────────
    @staticmethod
    def _geojson_to_wkt(geom: dict) -> str:
        """将 GeoJSON Polygon/MultiPolygon geometry 转为 WKT 字符串。"""
        if not geom:
            return ""
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])
        try:
            if gtype == "Polygon" and coords:
                ring = coords[0]
            elif gtype == "MultiPolygon" and coords:
                ring = coords[0][0]
            else:
                return ""
            pts = ", ".join(f"{c[0]} {c[1]}" for c in ring)
            return f"POLYGON(({pts}))"
        except Exception:
            return ""

    # ── 解析 ────────────────────────────────────────────────
    @classmethod
    def from_odata(cls, raw: dict) -> "Product":
        """从 OData Products 单条记录构造 Product。

        与旧 render_results 的解析口径保持一致：平台按名称前缀判断，
        极化缺失时按文件名 DV/DH 推断，大小缺失回退 1.7 GB。
        """
        name = raw.get("Name", raw.get("Id", "—"))

        # 感测时间："2025-07-20T12:34:56.000Z" → "2025-07-20 12:34"
        acq = raw.get("ContentDate", {}).get("Start", "")[:16].replace("T", " ")

        # 平台：按名称前缀（兼容 S1 / S2）
        if   name.startswith("S1A"): platform = "S1A"
        elif name.startswith("S1B"): platform = "S1B"
        elif name.startswith("S1C"): platform = "S1C"
        elif name.startswith("S2A"): platform = "S2A"
        elif name.startswith("S2B"): platform = "S2B"
        elif name.startswith("S2C"): platform = "S2C"
        else:                         platform = name[:3] if len(name) >= 3 else "—"

        is_s2 = platform.startswith("S2")

        # Attributes 展开为 {名称: 值}
        attrs = {a["Name"]: a.get("Value", "—")
                 for a in raw.get("Attributes", []) if "Name" in a}

        orbit_dir = attrs.get("orbitDirection", "—")
        orbit_dir = _ORBIT_SHORT.get(orbit_dir, orbit_dir)

        size_bytes = raw.get("ContentLength", _DEFAULT_SIZE_BYTES)
        footprint  = cls._geojson_to_wkt(raw.get("GeoFootprint", {}))

        if is_s2:
            # S2A_MSIL2A_20250723T... → mode = L2A / L1C
            mode = "L2A" if "MSIL2A" in name else ("L1C" if "MSIL1C" in name else "MSI")
            pol  = "—"
            # tile_id：产品名第 6 段，如 T50TML
            parts   = name.split("_")
            tile_id = parts[5] if len(parts) > 5 else ""
            try:
                cloud_cover = float(attrs.get("cloudCover", -1))
            except (ValueError, TypeError):
                cloud_cover = -1.0
            # S2 默认大小约 800 MB
            if size_bytes == _DEFAULT_SIZE_BYTES:
                size_bytes = 800 * 1024 * 1024
        else:
            mode  = attrs.get("operationalMode", "—")
            pol   = attrs.get("polarisationChannels", "—")
            if pol == "—":
                pol = "VV&VH" if "DV" in name else ("HH&HV" if "DH" in name else "—")
            tile_id     = ""
            cloud_cover = -1.0

        return cls(
            product_id      = raw.get("Id", ""),
            name            = name,
            acquisition_time= acq,
            platform        = platform,
            mode            = mode,
            polarization    = pol,
            orbit_direction = orbit_dir,
            relative_orbit  = str(attrs.get("relativeOrbitNumber", "—")),
            absolute_orbit  = str(attrs.get("absoluteOrbitNumber", "—")),
            size_gb         = size_bytes / 1024 ** 3,
            online          = bool(raw.get("Online", True)),
            footprint       = footprint,
            cloud_cover     = cloud_cover,
            tile_id         = tile_id,
        )
