#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NASA 数据下载后空间裁剪（瘦身）内核
────────────────────────────────────────────────────────
目的只有一个：把全球轨道的 L2 swath 文件按研究区 bbox 裁掉无关区域，
大幅减小本地占用（实测 OMPS 单轨 14MB → 海河区 ~0.2MB）。这是「下载附属
功能」，不做重投影 / 反演 / 可视化——与项目「数据获取工具，非分析平台」
的定位一致。

核心思路（通用，不认卫星、不认维名）：
  1. 自动找到 lat/lon（2D 浮点、名字含 lat/lon，递归所有 group）；
  2. 取 lat/lon 所在的「两个空间维」（OMPS=nTimes×nXtrack，
     S5P=scanline×ground_pixel，名字各异但都是 lat/lon 的那两维）；
  3. 算 bbox 掩膜，在这两维上各取命中的连续索引范围；
  4. 遍历所有变量，凡用到这两维的就跟着切，其余维原样保留。
引擎只认「lat/lon 用了哪两维」，因此同类 swath 产品自动适配。

格式分支：
  ✅ netCDF4 groups swath（OMPS / S5P-TROPOMI）——_crop_netcdf_swath
  ✅ HDF-EOS5 .he5 swath（OMI，h5py）——_crop_hdf5，同步改写 StructMetadata 维度
  ⏳ netCDF4 网格（1D lat + 1D lon）——_crop_netcdf 内占位
  ❌ HDF4 .hdf（MODIS L1B/L2）——库不同、地理定位粗网格，不在本工具范围

依赖 numpy + netCDF4 / h5py，按 GDAL 同样的"可选"原则惰性导入：.nc 需
netCDF4、.he5 需 h5py，缺失则对应格式跳过、原始文件保留，下载主流程不受影响。

由 ui/tab_nasa.py 在 download_one 成功落盘后调用；下载内核
core/earthdata.py 保持纯净、不掺入裁剪逻辑。

⚠️ Windows 非 ASCII 路径：netCDF C 库无法直接打开中文路径的文件，
本模块自动在 ASCII 临时工作区读写、完成后再搬回中文目录。
"""

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Optional


# ── 配置对象 ──────────────────────────────────────────────────────────
@dataclass
class ProcessConfig:
    """裁剪参数。bbox 为 {lat_min, lat_max, lon_min, lon_max}。"""
    enabled: bool = False
    bbox: dict = field(default_factory=dict)
    delete_original: bool = False           # 裁剪成功后删除原始大文件
    out_dir: Optional[str] = None           # 输出目录，None=与原文件同目录
    lat_var: Optional[str] = None           # 手动指定纬度变量（自动探测失败时）
    lon_var: Optional[str] = None           # 手动指定经度变量
    compress: bool = True                   # 输出启用 zlib 压缩，再省一截
    out_suffix: str = "_subset"             # 输出文件名后缀

    def bbox_ok(self) -> bool:
        b = self.bbox or {}
        return all(k in b for k in ("lat_min", "lat_max", "lon_min", "lon_max"))


# ── 依赖可用性（惰性，缺失则优雅降级）────────────────────────────────
def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def is_available() -> bool:
    """numpy 在、且 netCDF4 / h5py 至少有一个 → 裁剪可用。

    .nc（OMPS/S5P）需 netCDF4，.he5（OMI）需 h5py；缺失时对应格式跳过、
    不影响下载。"""
    return _has("numpy") and (_has("netCDF4") or _has("h5py"))


# ── 对外主入口 ────────────────────────────────────────────────────────
def crop_file(file_path: str, config: ProcessConfig, log_cb=None):
    """对单个已下载文件做空间裁剪瘦身。

    返回 (status, out_path)：
      'cropped'     —— 已裁剪，out_path 为新文件路径
      'skipped'     —— 该轨道不经过研究区 / 已存在 / 未启用，原始保留
      'unsupported' —— 格式暂不支持（网格 / HDF-EOS / HDF4），原始保留
      'error'       —— 处理出错，原始保留
    任何非 'cropped' 情况都不动原始文件。
    """
    def _log(msg, tag="info"):
        if log_cb:
            log_cb(msg, tag)

    if not config or not config.enabled:
        return "skipped", None
    if not config.bbox_ok():
        _log("  ⚠️ 未设置有效研究区 bbox，跳过裁剪", "warn")
        return "skipped", None
    if not os.path.exists(file_path):
        return "error", None
    if not is_available():
        _log("  ⚠️ 未安装 netCDF4/numpy，跳过裁剪（原始文件保留）", "warn")
        return "unsupported", None

    ext = os.path.splitext(file_path)[1].lower()

    # 计算输出路径
    out_dir = config.out_dir or os.path.dirname(file_path)
    stem, real_ext = os.path.splitext(os.path.basename(file_path))
    out_path = os.path.join(out_dir, f"{stem}{config.out_suffix}{real_ext}")

    # 幂等：输出已存在直接跳过，沿用下载侧"存在即完整"的思路
    if os.path.exists(out_path):
        _log(f"  裁剪输出已存在，跳过（{os.path.basename(out_path)}）", "info")
        return "skipped", out_path

    try:
        # ── 格式分发 ──────────────────────────────────────
        if ext in (".nc", ".nc4", ".cdf"):
            if not _has("netCDF4"):
                _log("  ⚠️ 未安装 netCDF4，跳过 .nc 裁剪（原始保留）", "warn")
                return "unsupported", None
            status = _crop_netcdf(file_path, out_path, config, _log)
        elif ext in (".he5", ".h5", ".hdf5"):
            if not _has("h5py"):
                _log("  ⚠️ 未安装 h5py，跳过 .he5 裁剪（原始保留）", "warn")
                return "unsupported", None
            status = _crop_hdf5(file_path, out_path, config, _log)
        elif ext == ".hdf":
            _log("  ⚠️ HDF4（MODIS 等）不在裁剪范围，原始保留", "warn")
            status = "unsupported"
        else:
            _log(f"  ⚠️ 未知格式 {ext}，跳过裁剪", "warn")
            status = "unsupported"
    except Exception as e:
        _log(f"  ⚠️ 裁剪失败：{e}（原始文件保留）", "warn")
        # 失败时清理可能产生的半成品输出
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        return "error", None

    if status != "cropped":
        return status, None

    # ── 裁剪成功：体积日志 + 可选删原始 ──────────────────
    try:
        in_mb = os.path.getsize(file_path) / 1024**2
        out_mb = os.path.getsize(out_path) / 1024**2
        ratio = (out_mb / in_mb * 100) if in_mb else 0
        _log(f"  ✂️ 裁剪完成：{in_mb:.1f}MB → {out_mb:.1f}MB（{ratio:.0f}%）", "ok")
    except Exception:
        pass

    if config.delete_original and os.path.abspath(out_path) != os.path.abspath(file_path):
        try:
            os.remove(file_path)
            _log("  🗑 已删除原始文件", "info")
        except Exception as e:
            _log(f"  ⚠️ 删除原始失败（保留）：{e}", "warn")

    return "cropped", out_path


# ── 轻量探测（供 UI 显示自动识别结果 / 让用户手动覆盖）──────────────
def probe_file(file_path: str):
    """探测文件的格式与坐标变量，返回 dict（失败返回带 error 的 dict）。

    {
      'format': 'netcdf4' | 'hdf5' | 'hdf4' | 'unknown',
      'kind':   'swath' | 'gridded' | 'unknown',
      'lat_var', 'lon_var':  探测到的坐标变量路径（含 group），可能为 None,
      'spatial_dims': [dimA, dimB]  swath 的两个空间维名,
      'all_2d_floats': [...]        所有候选 2D 浮点变量（供手动下拉）,
    }
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in (".nc", ".nc4", ".cdf"):
        return {"format": _ext_to_format(ext), "kind": "unknown",
                "lat_var": None, "lon_var": None, "error": "暂只探测 netCDF4"}
    if not is_available():
        return {"format": "netcdf4", "kind": "unknown",
                "lat_var": None, "lon_var": None, "error": "未安装 netCDF4"}

    import netCDF4
    work, cleanup = _ascii_workspace_in(file_path)
    try:
        ds = netCDF4.Dataset(work)
        lat_path, lon_path = _find_latlon(ds)
        cands = [p for p, _ in _iter_2d_floats(ds)]
        kind, spatial = "unknown", []
        if lat_path:
            latvar = _getvar(ds, lat_path)
            ndim_eff = sum(1 for s in latvar.shape if s > 1)
            if ndim_eff >= 2:
                kind = "swath"
                spatial = [d for d, s in zip(latvar.dimensions, latvar.shape) if s > 1]
            elif ndim_eff == 1:
                kind = "gridded"
        ds.close()
        return {"format": "netcdf4", "kind": kind,
                "lat_var": lat_path, "lon_var": lon_path,
                "spatial_dims": spatial, "all_2d_floats": cands}
    finally:
        cleanup()


# ─────────────────────────────────────────────────────────────────────
#  netCDF4 实现
# ─────────────────────────────────────────────────────────────────────
def _crop_netcdf(in_path, out_path, config, log):
    """netCDF4 顶层分发：ASCII 工作区 + swath / 网格 选择。"""
    import netCDF4

    work_in, cleanup_in = _ascii_workspace_in(in_path)
    # 输出也走 ASCII 临时，再搬回最终（最终可能是中文目录）
    out_ascii = out_path.isascii()
    if out_ascii:
        work_out = out_path
        tmp_out_dir = None
    else:
        tmp_out_dir = tempfile.mkdtemp(prefix="ncproc_out_")
        work_out = os.path.join(tmp_out_dir, "out.nc")

    try:
        src = netCDF4.Dataset(work_in)
        src.set_auto_maskandscale(False)   # 读原始存储值，scale/offset/fill 作为属性原样复制

        lat_path = config.lat_var or None
        lon_path = config.lon_var or None
        if not (lat_path and lon_path):
            lat_path, lon_path = _find_latlon(src)
        if not (lat_path and lon_path):
            src.close()
            log("  ⚠️ 未能自动识别经纬度变量，跳过裁剪", "warn")
            return "unsupported"

        latvar = _getvar(src, lat_path)
        ndim_eff = sum(1 for s in latvar.shape if s > 1)

        if ndim_eff >= 2:
            status = _crop_netcdf_swath(src, work_out, lat_path, lon_path, config, log)
        elif ndim_eff == 1:
            src.close()
            log("  ⚠️ 网格产品（1D 经纬度）暂未实现，原始保留", "warn")
            return "unsupported"
        else:
            src.close()
            log("  ⚠️ 经纬度维度异常，跳过裁剪", "warn")
            return "unsupported"

        if status == "cropped" and not out_ascii:
            shutil.move(work_out, out_path)
        return status
    finally:
        cleanup_in()
        if tmp_out_dir:
            shutil.rmtree(tmp_out_dir, ignore_errors=True)


def _crop_netcdf_swath(src, work_out, lat_path, lon_path, config, log):
    """2D swath 裁剪：按 lat/lon 的两个空间维各取命中索引范围、连续切片。

    src 为已打开的 netCDF4.Dataset（auto_maskandscale 已关闭）；写出到
    work_out（保证 ASCII 路径）。返回 'cropped' / 'skipped' / 'unsupported'。
    """
    import netCDF4
    import numpy as np

    latvar = _getvar(src, lat_path)
    lonvar = _getvar(src, lon_path)

    # 空间两维（按原始顺序、剔除单维）。squeeze 后轴顺序与之一致
    spatial = [d for d, s in zip(latvar.dimensions, latvar.shape) if s > 1]
    if len(spatial) < 2:
        src.close()
        log("  ⚠️ 经纬度不是 2D，跳过 swath 裁剪", "warn")
        return "unsupported"
    dim0, dim1 = spatial[0], spatial[1]

    lat = np.squeeze(np.asarray(latvar[:], dtype="float64"))
    lon = np.squeeze(np.asarray(lonvar[:], dtype="float64"))
    if lat.ndim != 2 or lat.shape != lon.shape:
        src.close()
        log("  ⚠️ 经纬度形状异常，跳过裁剪", "warn")
        return "unsupported"

    b = config.bbox
    mask = ((lat >= b["lat_min"]) & (lat <= b["lat_max"]) &
            (lon >= b["lon_min"]) & (lon <= b["lon_max"]))
    if not mask.any():
        src.close()
        log("  ⤳ 该轨道未覆盖研究区，跳过（原始保留）", "info")
        return "skipped"

    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    r0, r1 = int(rows.min()), int(rows.max()) + 1
    c0, c1 = int(cols.min()), int(cols.max()) + 1
    hit = {dim0: (r0, r1), dim1: (c0, c1)}
    log(f"  命中 {dim0}[{r0}:{r1}] × {dim1}[{c0}:{c1}]", "info")

    # ── 写出裁剪后的新文件，保持 group / 维度 / 属性 ──────
    out = netCDF4.Dataset(work_out, "w", format=src.data_model)
    try:
        _copy_attrs(src, out)
        _walk_copy(src, out, hit, config.compress)
        out.close()
    except Exception:
        try:
            out.close()
        except Exception:
            pass
        raise
    finally:
        src.close()
    return "cropped"


def _walk_copy(srcg, dstg, hit, compress):
    """递归复制一个 group：维度 → 变量 → 子 group。空间维按 hit 缩短。"""
    # 维度（空间维用命中范围长度，其余保持；无限维保持无限）
    for dname, dim in srcg.dimensions.items():
        if dname in hit:
            r0, r1 = hit[dname]
            dstg.createDimension(dname, r1 - r0)
        else:
            dstg.createDimension(dname, None if dim.isunlimited() else len(dim))

    # 变量
    for vname, var in srcg.variables.items():
        _copy_var(var, dstg, hit, compress)

    # 子 group
    for gn, sub in srcg.groups.items():
        ng = dstg.createGroup(gn)
        _copy_attrs(sub, ng)
        _walk_copy(sub, ng, hit, compress)


def _copy_var(srcvar, dstgrp, hit, compress):
    """复制单个变量，沿命中的空间维切片；保留 _FillValue 与其余属性。"""
    dt = srcvar.dtype
    is_vlen_str = (dt is str) or (dt == str)
    fv = srcvar._FillValue if "_FillValue" in srcvar.ncattrs() else None
    use_zlib = bool(compress) and srcvar.ndim > 0 and not is_vlen_str

    newv = dstgrp.createVariable(
        srcvar.name, dt, srcvar.dimensions,
        zlib=use_zlib, complevel=4 if use_zlib else 0,
        fill_value=fv,
    )
    # _FillValue 已在创建时给定，复制其余属性
    newv.setncatts({k: srcvar.getncattr(k) for k in srcvar.ncattrs()
                    if k != "_FillValue"})

    if any(d in hit for d in srcvar.dimensions):
        sl = tuple(slice(*hit[d]) if d in hit else slice(None)
                   for d in srcvar.dimensions)
        newv[:] = srcvar[sl]
    else:
        newv[:] = srcvar[:]


# ─────────────────────────────────────────────────────────────────────
#  HDF-EOS5 .he5 实现（OMI 等，h5py）
# ─────────────────────────────────────────────────────────────────────
def _crop_hdf5(in_path, out_path, config, log):
    """HDF-EOS5 .he5（OMI 等）swath 裁剪。

    与 netCDF4 同思路（按 lat/lon 两维切），但走 h5py 读写。OMI 不用 netCDF
    维度，维度信息记在 StructMetadata 文本里——这里同步改写其 nTimes/nXtrack
    的 Size，保证元数据与裁剪后数据一致（严格 HDF-EOS 工具也认）。

    其它维（每个数据集的轴）按「轴长 == 原沿轨/刈幅长」匹配切片：OMI 的
    nTimes/nXtrack 尺寸唯一，不会误伤。
    """
    import h5py
    import numpy as np

    work_in, cleanup_in = _ascii_workspace_in(in_path)
    out_ascii = out_path.isascii()
    if out_ascii:
        work_out, tmp_out_dir = out_path, None
    else:
        tmp_out_dir = tempfile.mkdtemp(prefix="ncproc_out_")
        work_out = os.path.join(tmp_out_dir, "out.he5")

    try:
        src = h5py.File(work_in, "r")

        lat_path = config.lat_var or None
        lon_path = config.lon_var or None
        if not (lat_path and lon_path):
            lat_path, lon_path = _find_latlon_h5(src)
        if not (lat_path and lon_path):
            src.close()
            log("  ⚠️ 未能识别经纬度数据集，跳过裁剪", "warn")
            return "unsupported"

        lat = np.asarray(src[lat_path][:], dtype="float64")
        lon = np.asarray(src[lon_path][:], dtype="float64")
        if lat.ndim != 2 or lat.shape != lon.shape:
            src.close()
            log("  ⚠️ 经纬度非 2D，跳过裁剪", "warn")
            return "unsupported"
        R_orig, C_orig = lat.shape

        b = config.bbox
        mask = ((lat >= b["lat_min"]) & (lat <= b["lat_max"]) &
                (lon >= b["lon_min"]) & (lon <= b["lon_max"]))
        if not mask.any():
            src.close()
            log("  ⤳ 该轨道未覆盖研究区，跳过（原始保留）", "info")
            return "skipped"
        rows = np.where(mask.any(axis=1))[0]
        cols = np.where(mask.any(axis=0))[0]
        r0, r1 = int(rows.min()), int(rows.max()) + 1
        c0, c1 = int(cols.min()), int(cols.max()) + 1
        log(f"  命中 沿轨[{r0}:{r1}] × 刈幅[{c0}:{c1}]（原 {R_orig}×{C_orig}）", "info")

        out = h5py.File(work_out, "w")
        try:
            _h5_copy_attrs(src, out)
            _h5_walk_copy(src, out, R_orig, C_orig, (r0, r1), (c0, c1),
                          config.compress)
            out.close()
        except Exception:
            try:
                out.close()
            except Exception:
                pass
            raise
        finally:
            src.close()

        if not out_ascii:
            shutil.move(work_out, out_path)
        return "cropped"
    finally:
        cleanup_in()
        if tmp_out_dir:
            shutil.rmtree(tmp_out_dir, ignore_errors=True)


# 命名里带这些词的坐标数据集优先级降低（角点 / 瓦片角 / 星下点等）
_H5_LATLON_DEMOTE = ("corner", "tiled", "spacecraft", "sub", "bound", "anchor")


def _find_latlon_h5(f):
    """在 h5py 文件里递归找主纬度 / 经度数据集，返回 (lat_path, lon_path)。"""
    import h5py

    cands = []

    def visit(name, obj):
        if isinstance(obj, h5py.Dataset) and getattr(obj.dtype, "kind", None) == "f":
            if sum(1 for s in obj.shape if s > 1) >= 2:
                cands.append((name, obj.shape))

    f.visititems(visit)

    def best(key):
        ranked = []
        for name, shape in cands:
            base = name.split("/")[-1].lower()
            if key not in base:
                continue
            s = 0
            if base in ("latitude", "longitude", "lat", "lon"):
                s += 100
            elif base.endswith(("latitude", "longitude")):
                s += 60
            else:
                s += 30
            if any(w in name.lower() for w in _H5_LATLON_DEMOTE):
                s -= 80
            s -= (sum(1 for x in shape if x > 1) - 2) * 20
            ranked.append((s, name))
        ranked.sort(reverse=True)
        return ranked[0][1] if ranked and ranked[0][0] >= 0 else None

    return best("lat"), best("lon")


def _h5_copy_attrs(src_obj, dst_obj):
    """逐条复制 HDF5 对象属性，单条失败（如对象引用）静默跳过。"""
    for k, v in src_obj.attrs.items():
        try:
            dst_obj.attrs.create(k, v)
        except Exception:
            pass


def _h5_walk_copy(src, dst, R_orig, C_orig, rr, cc, compress):
    """递归复制 h5py group 树；数据集按空间维切片，StructMetadata 改写 Size。"""
    import h5py

    for key in src.keys():
        item = src[key]
        if isinstance(item, h5py.Group):
            ng = dst.create_group(key)
            _h5_copy_attrs(item, ng)
            _h5_walk_copy(item, ng, R_orig, C_orig, rr, cc, compress)
        else:
            _copy_h5_dataset(key, item, dst, R_orig, C_orig, rr, cc, compress)


def _copy_h5_dataset(name, dset, dgroup, R_orig, C_orig, rr, cc, compress):
    """复制单个 HDF5 数据集，沿匹配空间维的轴切片。"""
    import numpy as np

    base = name.split("/")[-1]

    # StructMetadata.0：文本元数据，改写 nTimes/nXtrack 的 Size 后原样写回
    if base.startswith("StructMetadata"):
        raw = dset[()]
        txt = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, np.bytes_)) else str(raw)
        txt = _rewrite_struct_sizes(txt, R_orig, C_orig, rr[1] - rr[0], cc[1] - cc[0])
        try:
            d = dgroup.create_dataset(name, data=np.bytes_(txt.encode("utf-8")),
                                      dtype=dset.dtype)
        except Exception:
            d = dgroup.create_dataset(name, data=np.bytes_(txt.encode("utf-8")))
        _h5_copy_attrs(dset, d)
        return

    shape = dset.shape
    if shape == ():                       # 标量（如 CoreMetadata.0）原样拷
        d = dgroup.create_dataset(name, data=dset[()], dtype=dset.dtype)
        _h5_copy_attrs(dset, d)
        return

    # 按轴长匹配空间维切片（OMI 的 nTimes/nXtrack 尺寸唯一，不会误伤）
    r0, r1 = rr
    c0, c1 = cc
    sl, touched = [], False
    for s in shape:
        if s == R_orig:
            sl.append(slice(r0, r1)); touched = True
        elif s == C_orig:
            sl.append(slice(c0, c1)); touched = True
        else:
            sl.append(slice(None))
    data = dset[tuple(sl)] if touched else dset[()]

    kw = {}
    if compress and getattr(data, "ndim", 0) >= 1 and data.size > 0:
        kw = dict(compression="gzip", compression_opts=4, chunks=True)
    try:
        d = dgroup.create_dataset(name, data=data, dtype=dset.dtype, **kw)
    except (ValueError, TypeError):
        d = dgroup.create_dataset(name, data=data, dtype=dset.dtype)   # 退化：不压缩
    _h5_copy_attrs(dset, d)


def _rewrite_struct_sizes(txt, R_orig, C_orig, R_new, C_new):
    """改写 StructMetadata 文本里 沿轨/刈幅 维的 Size=NNN。

    按「原 Size 值唯一对应一个 DimensionName」精确定位再替换；若某 size 对应
    多个维（罕见）则跳过该维不改，宁可不动也不误伤。
    """
    import re

    dims = re.findall(r'DimensionName="([^"]+)"\s+Size=(\d+)', txt)

    def repl(t, orig, new):
        names = [n for n, s in dims if int(s) == orig]
        if len(names) != 1:
            return t
        nm = names[0]
        return re.sub(r'(DimensionName="%s"\s+Size=)\d+' % re.escape(nm),
                      lambda m: m.group(1) + str(new), t)

    return repl(repl(txt, R_orig, R_new), C_orig, C_new)


# ─────────────────────────────────────────────────────────────────────
#  辅助函数
# ─────────────────────────────────────────────────────────────────────
def _getvar(ds, path):
    """按 'GROUP/SUB/Name' 路径取变量。"""
    g = ds
    *groups, name = path.split("/")
    for gp in groups:
        if gp:
            g = g.groups[gp]
    return g.variables[name]


def _iter_2d_floats(ds):
    """遍历所有「有效维>=2 的浮点变量」，产出 (path, var)。"""
    out = []

    def walk(g, path=""):
        for name, var in g.variables.items():
            full = f"{path}/{name}".lstrip("/")
            eff = sum(1 for s in var.shape if s > 1)
            # vlen 字符串等非 numpy dtype 无 .kind，getattr 兜底跳过
            if getattr(var.dtype, "kind", None) == "f" and eff >= 2:
                out.append((full, var))
        for gn, sub in g.groups.items():
            walk(sub, f"{path}/{gn}")

    walk(ds)
    return out


# 命名里带这些词的坐标变量优先级降低（角点 / 边界 / 星下点等，非主几何）
_LATLON_DEMOTE = ("corner", "bound", "center", "centre", "spacecraft",
                  "sub", "anchor", "tie")


def _find_latlon(ds):
    """自动识别主纬度 / 经度变量，返回 (lat_path, lon_path)，找不到为 None。

    候选：有效维>=2 的浮点变量且名字含 lat / lon。打分优先「名字干净、
    维度少（2D 优于 3D）」，避开 LatitudeCorner 这类衍生几何。
    """
    cands = _iter_2d_floats(ds)

    def score(name, var, key):
        n = name.lower()
        if key not in n:
            return -1
        s = 0
        base = name.split("/")[-1].lower()
        if base in ("latitude", "longitude", "lat", "lon"):
            s += 100
        elif base.endswith(("latitude", "longitude")):
            s += 60
        else:
            s += 30
        if any(w in n for w in _LATLON_DEMOTE):
            s -= 80
        eff = sum(1 for sz in var.shape if sz > 1)
        s -= (eff - 2) * 20         # 维度越多越靠后（优先纯 2D）
        return s

    def best(key):
        ranked = sorted(((score(p, v, key), p) for p, v in cands), reverse=True)
        return ranked[0][1] if ranked and ranked[0][0] >= 0 else None

    return best("lat"), best("lon")


def _copy_attrs(srcobj, dstobj):
    """复制一个 Dataset/Group 的全局属性。"""
    dstobj.setncatts({k: srcobj.getncattr(k) for k in srcobj.ncattrs()})


def _ext_to_format(ext):
    return {".nc": "netcdf4", ".nc4": "netcdf4", ".cdf": "netcdf4",
            ".he5": "hdf5", ".h5": "hdf5", ".hdf5": "hdf5",
            ".hdf": "hdf4"}.get(ext.lower(), "unknown")


def _ascii_workspace_in(path):
    """为「netCDF C 库打不开非 ASCII 路径」准备只读输入。

    路径全 ASCII → 直接用原路径，cleanup 为空操作；
    含非 ASCII → 复制到临时 ASCII 文件，cleanup 负责删除临时目录。
    返回 (work_path, cleanup_callable)。
    """
    if path.isascii():
        return path, (lambda: None)
    tmpd = tempfile.mkdtemp(prefix="ncproc_in_")
    work = os.path.join(tmpd, "in" + (os.path.splitext(path)[1] or ".nc"))
    shutil.copy(path, work)
    return work, (lambda: shutil.rmtree(tmpd, ignore_errors=True))
