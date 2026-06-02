#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AOI（研究区）管理
────────────────────────────────────────────────────────
AoiManager : AOI 的增删改查 + 文件解析（GeoJSON / Shapefile / KML）
             持久化到 data/aoi_library.json
"""

import json
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from core.config import DATA_DIR, AOI_PRESETS

_AOI_LIB_FILE = Path(DATA_DIR) / "aoi_library.json"

# GDAL 可选导入（用于 Shapefile 解析 + 投影转换）
try:
    from osgeo import ogr, osr
    _HAS_GDAL = True
except ImportError:
    _HAS_GDAL = False


class AoiManager:
    """AOI 库管理，线程安全（依赖调用方在 UI 线程调用，无额外锁需求）。"""

    # ── 内部读写 ──────────────────────────────────────────
    @classmethod
    def _load(cls) -> dict:
        if not _AOI_LIB_FILE.exists():
            return {"version": "1.0", "aois": []}
        try:
            return json.loads(_AOI_LIB_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"version": "1.0", "aois": []}

    @classmethod
    def _save(cls, data: dict):
        try:
            _AOI_LIB_FILE.parent.mkdir(parents=True, exist_ok=True)
            _AOI_LIB_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    # ── CRUD ──────────────────────────────────────────────
    @classmethod
    def get_all(cls) -> list:
        """返回所有用户自定义 AOI（不含内置预设），最新在前。"""
        return list(reversed(cls._load()["aois"]))

    @classmethod
    def get_display_list(cls) -> list[dict]:
        """返回供面板展示的完整列表：内置预设在前，用户 AOI 在后。

        每条为 {'id': ..., 'name': ..., 'wkt': ..., 'builtin': bool}
        """
        items = []
        for name, wkt in AOI_PRESETS.items():
            items.append({"id": f"__preset_{name}", "name": name,
                          "wkt": wkt, "builtin": True})
        for a in cls._load()["aois"]:
            items.append({**a, "builtin": False})
        return items

    @classmethod
    def add(cls, name: str, wkt: str, source: str = "manual") -> str:
        """新增 AOI，返回 id。"""
        aoi_id = str(uuid.uuid4())
        entry = {
            "id":         aoi_id,
            "name":       name,
            "wkt":        wkt,
            "bbox":       cls.wkt_to_bbox(wkt),
            "source":     source,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        data = cls._load()
        data["aois"].append(entry)
        cls._save(data)
        return aoi_id

    @classmethod
    def rename(cls, aoi_id: str, new_name: str):
        data = cls._load()
        for a in data["aois"]:
            if a["id"] == aoi_id:
                a["name"] = new_name
                break
        cls._save(data)

    @classmethod
    def delete(cls, aoi_id: str):
        data = cls._load()
        data["aois"] = [a for a in data["aois"] if a["id"] != aoi_id]
        cls._save(data)

    @classmethod
    def get_by_id(cls, aoi_id: str) -> dict | None:
        if aoi_id.startswith("__preset_"):
            name = aoi_id[len("__preset_"):]
            wkt  = AOI_PRESETS.get(name, "")
            return {"id": aoi_id, "name": name, "wkt": wkt, "builtin": True} if wkt else None
        for a in cls._load()["aois"]:
            if a["id"] == aoi_id:
                return a
        return None

    # ── 文件解析 ──────────────────────────────────────────
    @classmethod
    def parse_file(cls, filepath: str) -> tuple[str, str]:
        """解析 AOI 文件，返回 (wkt, source_type)。

        支持 .geojson/.json / .shp / .kml。
        """
        path = Path(filepath)
        ext  = path.suffix.lower()
        if ext in (".geojson", ".json"):
            return cls._parse_geojson(filepath), "geojson"
        elif ext == ".shp":
            return cls._parse_shapefile(filepath), "shapefile"
        elif ext == ".kml":
            return cls._parse_kml(filepath), "kml"
        else:
            raise ValueError(f"不支持的文件格式：{ext}（仅支持 .geojson / .shp / .kml）")

    @classmethod
    def _parse_geojson(cls, filepath: str) -> str:
        with open(filepath, encoding="utf-8") as f:
            gj = json.load(f)
        gtype = gj.get("type", "")
        if gtype == "FeatureCollection":
            features = gj.get("features", [])
            if not features:
                raise ValueError("GeoJSON FeatureCollection 中没有 Feature")
            geom = features[0].get("geometry", {})
        elif gtype == "Feature":
            geom = gj.get("geometry", {})
        else:
            geom = gj
        wkt = cls._geojson_geom_to_wkt(geom)
        if not wkt:
            raise ValueError("GeoJSON 几何解析失败，请检查坐标格式")
        return wkt

    @classmethod
    def _parse_shapefile(cls, filepath: str) -> str:
        if not _HAS_GDAL:
            raise RuntimeError("Shapefile 解析需要 GDAL（osgeo），请先安装")
        ds = ogr.Open(filepath)
        if not ds:
            raise ValueError(f"无法打开文件：{filepath}")
        layer = ds.GetLayer(0)
        source_srs = layer.GetSpatialRef()

        target_srs = osr.SpatialReference()
        target_srs.ImportFromEPSG(4326)
        target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

        geoms = []
        for feat in layer:
            g = feat.GetGeometryRef()
            if g is None:
                continue
            g = g.Clone()
            if source_srs and not source_srs.IsSame(target_srs):
                xform = osr.CoordinateTransformation(source_srs, target_srs)
                g.Transform(xform)
            geoms.append(g)

        if not geoms:
            raise ValueError("Shapefile 中没有有效几何")

        if len(geoms) == 1:
            result = geoms[0]
        else:
            union = geoms[0]
            for g in geoms[1:]:
                union = union.Union(g)
            result = union.ConvexHull()

        wkt = result.ExportToWkt()
        # 确保返回 POLYGON 形式（ExportToWkt 已是 WKT 标准格式）
        return wkt

    @classmethod
    def _parse_kml(cls, filepath: str) -> str:
        tree = ET.parse(filepath)
        root = tree.getroot()

        # KML 命名空间（2.2 / 2.3）
        ns22 = {"kml": "http://www.opengis.net/kml/2.2"}
        ns23 = {"kml": "http://www.opengis.net/kml/2.3"}

        coords_elem = (root.find(".//kml:coordinates", ns22) or
                       root.find(".//kml:coordinates", ns23) or
                       root.find(".//coordinates"))

        if coords_elem is None or not (coords_elem.text or "").strip():
            raise ValueError("KML 中未找到坐标数据")

        points = []
        for token in coords_elem.text.strip().split():
            parts = token.split(",")
            if len(parts) >= 2:
                try:
                    lon, lat = float(parts[0]), float(parts[1])
                    points.append((lon, lat))
                except ValueError:
                    continue

        if len(points) < 3:
            raise ValueError("KML 坐标点不足（至少需要 3 个）")

        coord_str = ", ".join(f"{lon} {lat}" for lon, lat in points)
        return f"POLYGON(({coord_str}))"

    # ── 工具方法 ──────────────────────────────────────────
    @staticmethod
    def _geojson_geom_to_wkt(geom: dict) -> str:
        gtype  = geom.get("type", "")
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

    @staticmethod
    def wkt_to_bbox(wkt: str) -> list | None:
        """从 WKT POLYGON 提取 [min_lon, min_lat, max_lon, max_lat]。"""
        if not wkt:
            return None
        try:
            pairs = re.findall(r"(-?\d+\.?\d*)\s+(-?\d+\.?\d*)", wkt)
            if not pairs:
                return None
            lons = [float(p[0]) for p in pairs]
            lats = [float(p[1]) for p in pairs]
            return [min(lons), min(lats), max(lons), max(lats)]
        except Exception:
            return None

    @staticmethod
    def wkt_to_positions(wkt: str) -> list[tuple]:
        """将 WKT POLYGON 转为 [(lat, lon), ...] 列表（供 tkintermapview 使用）。"""
        if not wkt:
            return []
        try:
            pairs = re.findall(r"(-?\d+\.?\d*)\s+(-?\d+\.?\d*)", wkt)
            return [(float(p[1]), float(p[0])) for p in pairs]
        except Exception:
            return []

    @staticmethod
    def bbox_zoom(bbox: list) -> int:
        """根据 bbox 大小估算合适的地图缩放级别。"""
        if not bbox:
            return 8
        span = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
        if span > 10: return 5
        if span > 5:  return 6
        if span > 2:  return 7
        if span > 1:  return 8
        if span > 0.5: return 9
        if span > 0.2: return 10
        if span > 0.1: return 11
        return 12
