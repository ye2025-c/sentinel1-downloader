#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地图预览 / 画框窗口
────────────────────────────────────────────────────────
open_map_window(app) 打开一个 Toplevel 窗口，内嵌 tkintermapview。

功能：
  - 显示当前 AOI 轮廓（蓝色高亮多边形）
  - 叠加显示搜索结果各景 footprint 覆盖范围（橙色细线）
  - 两次点击绘制矩形范围（不干扰地图平移/缩放）
  - 确认后将 WKT 写回 app.ent_wkt，并触发 AOI 面板刷新
  - 底图加载失败时静默降级，显示提示文字，坐标功能正常

降级策略：
  级别 1 — 正常：tkintermapview 内嵌地图 + AOI 轮廓 + footprint 叠加
  级别 2 — 失败：显示"底图加载失败"文字，bbox 坐标仍可显示
"""

import os
import re
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from core.aoi_manager import AoiManager
from core.config import DATA_DIR

# 单次叠加绘制的 footprint 上限，过多会拖慢地图渲染
_MAX_FOOTPRINTS = 200


class MapPanel(ttk.Frame):
    """可内嵌的常驻地图面板，供搜索 Tab 右侧上半区使用。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app           = app
        self._has_map      = False
        self._current_poly = None
        self._fp_polys     = []
        self._drawn_wkt    = ""
        self._draw_clicks  = []
        self._drawing      = False

        self._build_toolbar()
        self._build_map_area()
        app.after(100, self._load_map)

    def _build_toolbar(self):
        C  = self.app.colors
        tb = ttk.Frame(self)
        tb.pack(fill="x", padx=6, pady=(4, 2))

        self.btn_draw = ttk.Button(tb, text="✏ 绘制矩形",
                                   style="Accent.TButton",
                                   command=self.start_draw)
        self.btn_draw.pack(side="left")

        ttk.Button(tb, text="清除",
                   command=self._clear_draw).pack(side="left", padx=(4, 0))

        ttk.Button(tb, text="✅ 使用此 AOI",
                   style="Green.TButton",
                   command=self._apply).pack(side="right")

        ttk.Button(tb, text="保存到 AOI 库",
                   command=self._save_to_lib).pack(side="right", padx=(0, 6))

        self.status_var = tk.StringVar(value="点击「✏ 绘制矩形」在地图上框选范围")
        tk.Label(tb, textvariable=self.status_var,
                 fg=C["DIS"], font=(self.app.FONT_UI, 9),
                 bg=C["BG"]).pack(side="left", padx=8)

    def _build_map_area(self):
        self.map_frame = ttk.Frame(self)
        self.map_frame.pack(fill="both", expand=True, padx=6, pady=(0, 4))

    def _load_map(self):
        try:
            from tkintermapview import TkinterMapView
            os.makedirs(DATA_DIR, exist_ok=True)
            self.map_widget = TkinterMapView(
                self.map_frame, width=600, height=240, corner_radius=4,
                database_path=os.path.join(DATA_DIR, "tile_cache.db"))
            self.map_widget.pack(fill="both", expand=True)
            self.map_widget.set_position(39.5, 116.0, marker=False)
            self.map_widget.set_zoom(7)
            self._has_map = True
        except Exception:
            self._has_map = False
            tk.Label(
                self.map_frame,
                text="底图加载失败，请检查网络连接\n\n手动输入坐标或导入文件后\n点击「使用此 AOI」仍可正常使用",
                fg=self.app.colors["DIS"],
                font=(self.app.FONT_UI, 10),
                bg=self.app.colors["BG"]
            ).pack(expand=True)

    # ── 绘制矩形 ──────────────────────────────────────────
    def start_draw(self):
        if not self._has_map:
            return
        self._drawing     = True
        self._draw_clicks = []
        self._clear_draw()
        self.map_widget.add_left_click_map_command(self._on_map_click)
        self.status_var.set("请点击第一个角点（如西北角）…")
        self.btn_draw.config(state="disabled")

    def _on_map_click(self, coords):
        if not self._drawing:
            return
        lat, lon = coords
        self._draw_clicks.append((lat, lon))
        if len(self._draw_clicks) == 1:
            self.status_var.set(
                f"第一点 ({lat:.4f}°N, {lon:.4f}°E)  —  再点击对角点")
        elif len(self._draw_clicks) >= 2:
            self._finish_draw()

    def _finish_draw(self):
        self._drawing = False
        self.map_widget.add_left_click_map_command(None)
        self.btn_draw.config(state="normal")

        (lat1, lon1), (lat2, lon2) = self._draw_clicks[0], self._draw_clicks[1]
        min_lat, max_lat = min(lat1, lat2), max(lat1, lat2)
        min_lon, max_lon = min(lon1, lon2), max(lon1, lon2)

        wkt = (f"POLYGON(({min_lon:.6f} {min_lat:.6f}, "
               f"{max_lon:.6f} {min_lat:.6f}, "
               f"{max_lon:.6f} {max_lat:.6f}, "
               f"{min_lon:.6f} {max_lat:.6f}, "
               f"{min_lon:.6f} {min_lat:.6f}))")
        self._drawn_wkt = wkt
        self.show_aoi(wkt)
        self.status_var.set(
            f"矩形已绘制  [{min_lon:.4f}°, {min_lat:.4f}°] → [{max_lon:.4f}°, {max_lat:.4f}°]"
        )

    def _clear_draw(self):
        if self._has_map and self._current_poly:
            try:
                self._current_poly.delete()
            except Exception:
                pass
            self._current_poly = None

    # ── AOI 显示 ──────────────────────────────────────────
    def show_aoi(self, wkt: str):
        if not self._has_map or not wkt:
            return
        self._clear_draw()
        positions = AoiManager.wkt_to_positions(wkt)
        if not positions:
            return
        try:
            self._current_poly = self.map_widget.set_polygon(
                position_list = positions,
                fill_color    = "",
                outline_color = "#2288FF",
                border_width  = 3,
            )
            bbox = AoiManager.wkt_to_bbox(wkt)
            if bbox:
                center_lat = (bbox[1] + bbox[3]) / 2
                center_lon = (bbox[0] + bbox[2]) / 2
                self.map_widget.set_position(center_lat, center_lon, marker=False)
                self.map_widget.set_zoom(AoiManager.bbox_zoom(bbox))
        except Exception:
            pass

    # ── 搜索结果 footprint 叠加 ───────────────────────────
    def show_products(self, products):
        if not self._has_map or not products:
            return
        all_lats, all_lons = [], []
        drawn = 0
        for p in products[:_MAX_FOOTPRINTS]:
            positions = AoiManager.wkt_to_positions(getattr(p, "footprint", ""))
            if not positions:
                continue
            try:
                poly = self.map_widget.set_polygon(
                    position_list = positions,
                    fill_color    = "",
                    outline_color = "#FF8800",
                    border_width  = 1,
                    name          = getattr(p, "name", ""),
                )
                self._fp_polys.append(poly)
                all_lats.extend(lat for lat, _ in positions)
                all_lons.extend(lon for _, lon in positions)
                drawn += 1
            except Exception:
                continue

        if all_lats and all_lons:
            bbox = [min(all_lons), min(all_lats), max(all_lons), max(all_lats)]
            center_lat = (bbox[1] + bbox[3]) / 2
            center_lon = (bbox[0] + bbox[2]) / 2
            self.map_widget.set_position(center_lat, center_lon, marker=False)
            self.map_widget.set_zoom(AoiManager.bbox_zoom(bbox))

        total = len(products)
        extra = f"（仅显示前 {_MAX_FOOTPRINTS} 景）" if total > _MAX_FOOTPRINTS else ""
        self.status_var.set(f"已叠加 {drawn} 景覆盖范围{extra}")

    def clear_footprints(self):
        for poly in self._fp_polys:
            try:
                poly.delete()
            except Exception:
                pass
        self._fp_polys.clear()

    # ── 按钮回调 ──────────────────────────────────────────
    def _apply(self):
        wkt = self._drawn_wkt
        if not wkt:
            messagebox.showinfo("提示", "请先绘制矩形范围")
            return
        self.app.ent_wkt.delete("1.0", "end")
        self.app.ent_wkt.insert("1.0", wkt)
        if callable(getattr(self.app, "aoi_panel_refresh", None)):
            self.app.aoi_panel_refresh()

    def _save_to_lib(self):
        wkt = self._drawn_wkt
        if not wkt:
            messagebox.showinfo("提示", "请先绘制矩形范围")
            return
        name = simpledialog.askstring("保存 AOI", "请输入 AOI 名称：")
        if not name or not name.strip():
            return
        AoiManager.add(name.strip(), wkt, source="drawn")
        if callable(getattr(self.app, "aoi_panel_refresh", None)):
            self.app.aoi_panel_refresh()
        messagebox.showinfo("✅", f"已保存到 AOI 库：{name.strip()}")


def open_map_window(app, initial_wkt: str = "", products=None):
    """打开地图预览 / 画框 Toplevel。

    products : Product 列表，传入时在地图上叠加各景 footprint 覆盖范围。
    """
    win = _MapWindow(app, initial_wkt, products)
    win.grab_set()
    win.focus_set()


class _MapWindow(tk.Toplevel):
    def __init__(self, app, initial_wkt: str = "", products=None):
        super().__init__(app)
        self.app          = app
        self._products    = products or []
        self.title("搜索结果地图预览" if self._products else "地图预览 / 画框")
        self.geometry("740x560")
        self.minsize(600, 440)
        self.resizable(True, True)

        self._has_map       = False
        self._current_poly  = None   # 当前 AOI polygon 对象
        self._fp_polys      = []     # 搜索结果 footprint polygon 对象列表
        self._drawn_wkt     = ""     # 最新绘制 / 来自文件的 WKT
        self._draw_clicks   = []     # 画框时收集的两个角点
        self._drawing       = False

        self._build_ui()
        self._load_map()

        # 先叠加搜索结果 footprint，再叠加 AOI（AOI 在最上层）
        if self._products:
            self.after(800, self._show_products)
        if initial_wkt:
            self._drawn_wkt = initial_wkt
            self.after(900, lambda: self._show_aoi(initial_wkt))

    # ── 界面构建 ──────────────────────────────────────────
    def _build_ui(self):
        C = self.app.colors

        # 工具栏
        tb = ttk.Frame(self)
        tb.pack(fill="x", padx=10, pady=(8, 4))

        self.btn_draw = ttk.Button(tb, text="✏ 绘制矩形",
                                   style="Accent.TButton",
                                   command=self._start_draw)
        self.btn_draw.pack(side="left")

        ttk.Button(tb, text="清除",
                   command=self._clear_draw).pack(side="left", padx=(4, 0))

        ttk.Button(tb, text="✅ 使用此 AOI",
                   style="Green.TButton",
                   command=self._apply).pack(side="right")

        ttk.Button(tb, text="保存到 AOI 库",
                   command=self._save_to_lib).pack(side="right", padx=(0, 6))

        self.status_var = tk.StringVar(value="点击「✏ 绘制矩形」在地图上框选范围")
        tk.Label(tb, textvariable=self.status_var,
                 fg=C["DIS"], font=(self.app.FONT_UI, 9),
                 bg=C["BG"]).pack(side="left", padx=10)

        # 地图区
        self.map_frame = ttk.Frame(self)
        self.map_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _load_map(self):
        """异步加载地图；失败时显示提示文字，不阻塞窗口。"""
        try:
            from tkintermapview import TkinterMapView
            os.makedirs(DATA_DIR, exist_ok=True)
            self.map_widget = TkinterMapView(
                self.map_frame, width=700, height=460, corner_radius=4,
                database_path=os.path.join(DATA_DIR, "tile_cache.db"))
            self.map_widget.pack(fill="both", expand=True)
            self.map_widget.set_position(39.5, 116.0, marker=False)
            self.map_widget.set_zoom(7)
            self._has_map = True
        except Exception:
            self._has_map = False
            tk.Label(
                self.map_frame,
                text="底图加载失败，请检查网络连接\n\n手动输入坐标或导入文件后\n点击「使用此 AOI」仍可正常使用",
                fg=self.app.colors["DIS"],
                font=(self.app.FONT_UI, 11),
                bg=self.app.colors["BG"]
            ).pack(expand=True)

    # ── 绘制矩形（两次点击）───────────────────────────────
    def _start_draw(self):
        if not self._has_map:
            messagebox.showinfo("提示", "地图未加载，无法在地图上绘制\n请直接在搜索页面输入 WKT 坐标",
                                parent=self)
            return
        self._drawing   = True
        self._draw_clicks = []
        self._clear_draw()
        self.map_widget.add_left_click_map_command(self._on_map_click)
        self.status_var.set("请点击第一个角点（如西北角）…")
        self.btn_draw.config(state="disabled")

    def _on_map_click(self, coords):
        if not self._drawing:
            return
        lat, lon = coords
        self._draw_clicks.append((lat, lon))

        if len(self._draw_clicks) == 1:
            self.status_var.set(
                f"第一点 ({lat:.4f}°N, {lon:.4f}°E)  —  再点击对角点")
        elif len(self._draw_clicks) >= 2:
            self._finish_draw()

    def _finish_draw(self):
        self._drawing = False
        self.map_widget.add_left_click_map_command(None)
        self.btn_draw.config(state="normal")

        (lat1, lon1), (lat2, lon2) = self._draw_clicks[0], self._draw_clicks[1]
        min_lat, max_lat = min(lat1, lat2), max(lat1, lat2)
        min_lon, max_lon = min(lon1, lon2), max(lon1, lon2)

        wkt = (f"POLYGON(({min_lon:.6f} {min_lat:.6f}, "
               f"{max_lon:.6f} {min_lat:.6f}, "
               f"{max_lon:.6f} {max_lat:.6f}, "
               f"{min_lon:.6f} {max_lat:.6f}, "
               f"{min_lon:.6f} {min_lat:.6f}))")
        self._drawn_wkt = wkt
        self._show_aoi(wkt)
        self.status_var.set(
            f"矩形已绘制  [{min_lon:.4f}°, {min_lat:.4f}°] → [{max_lon:.4f}°, {max_lat:.4f}°]"
        )

    def _clear_draw(self):
        if self._has_map and self._current_poly:
            try:
                self._current_poly.delete()
            except Exception:
                pass
            self._current_poly = None

    # ── AOI 显示 ──────────────────────────────────────────
    def _show_aoi(self, wkt: str):
        if not self._has_map or not wkt:
            return
        self._clear_draw()
        positions = AoiManager.wkt_to_positions(wkt)
        if not positions:
            return
        try:
            self._current_poly = self.map_widget.set_polygon(
                position_list=positions,
                fill_color     = "",
                outline_color  = "#2288FF",
                border_width   = 3,
            )
            # 缩放到 AOI 范围
            bbox = AoiManager.wkt_to_bbox(wkt)
            if bbox:
                center_lat = (bbox[1] + bbox[3]) / 2
                center_lon = (bbox[0] + bbox[2]) / 2
                zoom = AoiManager.bbox_zoom(bbox)
                self.map_widget.set_position(center_lat, center_lon, marker=False)
                self.map_widget.set_zoom(zoom)
        except Exception:
            pass

    # ── 搜索结果 footprint 叠加 ───────────────────────────
    def _show_products(self):
        """在地图上叠加绘制所有景的 footprint，并缩放到总范围。"""
        if not self._has_map or not self._products:
            return

        drawn = 0
        all_lats, all_lons = [], []
        for p in self._products[:_MAX_FOOTPRINTS]:
            positions = AoiManager.wkt_to_positions(getattr(p, "footprint", ""))
            if not positions:
                continue
            try:
                poly = self.map_widget.set_polygon(
                    position_list = positions,
                    fill_color    = "",
                    outline_color = "#FF8800",
                    border_width  = 1,
                    name          = getattr(p, "name", ""),
                )
                self._fp_polys.append(poly)
                all_lats.extend(lat for lat, _ in positions)
                all_lons.extend(lon for _, lon in positions)
                drawn += 1
            except Exception:
                continue

        # 缩放到所有 footprint 的总范围
        if all_lats and all_lons:
            bbox = [min(all_lons), min(all_lats), max(all_lons), max(all_lats)]
            center_lat = (bbox[1] + bbox[3]) / 2
            center_lon = (bbox[0] + bbox[2]) / 2
            self.map_widget.set_position(center_lat, center_lon, marker=False)
            self.map_widget.set_zoom(AoiManager.bbox_zoom(bbox))

        total = len(self._products)
        extra = f"（仅显示前 {_MAX_FOOTPRINTS} 景）" if total > _MAX_FOOTPRINTS else ""
        no_fp = total - drawn if total <= _MAX_FOOTPRINTS else 0
        msg = f"已叠加 {drawn} 景覆盖范围{extra}"
        if no_fp > 0:
            msg += f"，{no_fp} 景无 footprint 数据"
        self.status_var.set(msg)

    # ── 按钮回调 ──────────────────────────────────────────
    def _apply(self):
        """将 WKT 写回主窗口 ent_wkt，关闭地图窗口。"""
        wkt = self._drawn_wkt
        if not wkt:
            messagebox.showinfo("提示", "请先绘制矩形范围", parent=self)
            return
        self.app.ent_wkt.delete("1.0", "end")
        self.app.ent_wkt.insert("1.0", wkt)
        if callable(getattr(self.app, "aoi_panel_refresh", None)):
            self.app.aoi_panel_refresh()
        self.destroy()

    def _save_to_lib(self):
        """将当前 WKT 命名后存入 AOI 库。"""
        wkt = self._drawn_wkt
        if not wkt:
            messagebox.showinfo("提示", "请先绘制矩形范围", parent=self)
            return
        name = simpledialog.askstring("保存 AOI", "请输入 AOI 名称：", parent=self)
        if not name or not name.strip():
            return
        AoiManager.add(name.strip(), wkt, source="drawn")
        if callable(getattr(self.app, "aoi_panel_refresh", None)):
            self.app.aoi_panel_refresh()
        messagebox.showinfo("✅", f"已保存到 AOI 库：{name.strip()}", parent=self)
