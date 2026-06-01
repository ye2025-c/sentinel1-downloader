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

    # ── 展示辅助 ─────────────────────────────────────────────
    @property
    def size_str(self) -> str:
        """队列 / 表格用的大小文案，如 '1.7 GB'。"""
        return f"{self.size_gb:.1f} GB"

    @property
    def online_str(self) -> str:
        return "✓在线" if self.online else "归档"

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

        # 平台：按名称前缀
        if   name.startswith("S1A"): platform = "S1A"
        elif name.startswith("S1C"): platform = "S1C"
        else:                         platform = "S1B"

        # Attributes 展开为 {名称: 值}
        attrs = {a["Name"]: a.get("Value", "—")
                 for a in raw.get("Attributes", []) if "Name" in a}

        pol = attrs.get("polarisationChannels", "—")
        if pol == "—":   # 退回按文件名推断
            pol = "VV&VH" if "DV" in name else ("HH&HV" if "DH" in name else "—")

        orbit_dir = attrs.get("orbitDirection", "—")
        orbit_dir = _ORBIT_SHORT.get(orbit_dir, orbit_dir)

        size_bytes = raw.get("ContentLength", _DEFAULT_SIZE_BYTES)

        return cls(
            product_id     = raw.get("Id", ""),
            name           = name,
            acquisition_time = acq,
            platform       = platform,
            mode           = attrs.get("operationalMode", "—"),
            polarization   = pol,
            orbit_direction= orbit_dir,
            relative_orbit = str(attrs.get("relativeOrbitNumber", "—")),
            absolute_orbit = str(attrs.get("absoluteOrbitNumber", "—")),
            size_gb        = size_bytes / 1024 ** 3,
            online         = bool(raw.get("Online", True)),
        )
