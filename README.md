# Sentinel 卫星数据批量搜索 & 下载工具

面向遥感科研的桌面数据获取工具，支持 **Sentinel-1（SAR）** 与 **Sentinel-2（光学）** 影像的可视化搜索与批量下载，数据源为 [Copernicus Data Space Ecosystem (ESA)](https://dataspace.copernicus.eu)；并额外支持 **NASA Earthdata** 数据的 URL 列表批量下载，含**下载后按研究区裁剪瘦身**（OMPS / OMI / S5P 等 L2 swath）。

内置海河"25·7"洪涝灾害遥感监测研究区（AOI）预设。

## 下载 / 运行

### 方式一：直接下载 exe（Windows，推荐）

前往 [Releases 页面](../../releases/latest) 下载 `SentinelDownloader.exe`，双击即可运行，**无需安装 Python 或任何依赖**。

> - exe 约 23 MB，首次启动解压需几秒，属正常现象。
> - 运行数据（账号配置、下载历史、日志）保存在 exe 同目录的 `data/` 文件夹，不会写入系统目录。
> - Shapefile / KML 导入及 NASA 下载后裁剪在 exe 版中不可用（依赖 GDAL / h5py，未打包）；GeoJSON 导入与全部下载功能正常。

### 方式二：从源码运行（开发 / 自定义）

```bash
cd sentinel_downloader
pip install -r requirements.txt
python main.py
```

主要依赖：`requests`、`tqdm`、`ttkbootstrap`、`tkintermapview`。

> Shapefile / KML 导入依赖 **GDAL**（`osgeo`），需通过 conda 等方式安装；未安装时 GeoJSON 导入仍可用。
>
> 「下载后裁剪」依赖 **netCDF4 / h5py / numpy**；未安装时该功能自动跳过，下载主流程不受影响。

---

## 功能

### 数据搜索
- 双数据源切换：**Sentinel-1**（轨道方向 / 极化 / 相对·绝对轨道号 / 成像模式）与 **Sentinel-2**（云量上限 / 处理级别 L1C·L2A / Tile ID / 相对轨道号 / 处理基线 / 卫星平台 / 仅在线产品）
- WKT 或 Tile ID 单独用作搜索条件（S2 无需两者同时提供）
- OData 服务端筛选 + 客户端关键字实时过滤
- 按产品名精确搜索（官网复制文件名直接粘贴）
- 搜索结果统计（均云量显示）、CSV 导出
- **搜索结果缓存**（默认 24h，可在设置调整）：重复搜索秒级响应

### 空间范围管理（AOI）
- 内置研究区预设 + 用户自定义 AOI 库
- **文件导入**：GeoJSON / Shapefile / KML（自动投影转 WGS84）
- **地图画框**：内嵌地图上两次点击绘制矩形范围
- Footprint 地图叠加：搜索结果实时叠加各景覆盖范围

### 下载管理
- 批量并行下载 / 断点续传 / 自动重试 / Token 自动刷新
- **完整性校验**：下载收尾校验文件大小与 ZIP 结构，不完整 / 损坏自动续传重试
- **队列持久化**：下载队列实时落盘，程序关闭或崩溃后重启自动恢复未完成任务
- **失败任务一键重试**：「↻ 重试失败」批量重置失败任务；下载历史「重新下载」可重新入队
- 下载日志与速度实时显示
- **下载历史**：记录每景下载状态，搜索结果中已下载产品自动标记 ✓

### NASA Earthdata 下载（独立 Tab）
- 工作流：官网勾选 → 导出 `.txt` URL 列表 → 导入工具批量下载
- 复用同款下载策略：`.part` 断点续传 / 失败退避重试 / 原子落盘 / 实时进度与速度
- 认证使用「账号配置」页的 Earthdata 账号（HTTP Basic，经 `urs.earthdata.nasa.gov` 重定向）
- 文件列表支持 Ctrl/Shift 多选、Delete 键删除，可在下载前手动剔除不需要的项
- **失败任务一键重试**：「↻ 重试失败」把列表里失败的项重置为等待并重新下载
- **单文件大小**：下载中显示「当前/总 MB」，完成后在列表/历史持久显示大小；断点续传显式提示「从 X MB 处继续」
- **NASA 下载历史**：独立记录每个文件的结果（文件名 / 大小 / 状态 / 是否裁剪 / 时间），落盘 `nasa_history.json`，重启后仍可浏览，选中可「重新下载」

### 下载后裁剪（按研究区瘦身）
全球轨道的 L2 swath 文件动辄十几 MB，但研究区只占其中一小段扫描线。可选地在下载完成后按经纬度 bbox 裁掉研究区以外的数据（实测 OMI 单景 18 MB → 0.6 MB）。

- 支持格式：OMPS / Sentinel-5P `.nc`（netCDF4）、OMI `.he5`（HDF-EOS5）
- 不经过研究区的轨道自动跳过并保留原始文件
- 依赖 **netCDF4 / h5py / numpy**（可选，未安装时自动跳过）

### 设置
- 集中调整：并行数、单文件最大重试、连接 / 读取超时、NASA 文件间隔、搜索缓存有效期、ZIP 完整性校验开关、日志保留天数

---

## 使用步骤

### Sentinel（CDSE）
1. 注册 Copernicus 账号：https://dataspace.copernicus.eu （免费，S1/S2 同一账号）
2. 「账号配置」页填写账号 → 测试登录 → 保存配置
3. 「搜索影像」页选择数据源（Sentinel-1 / Sentinel-2），设置时间范围、AOI 与筛选条件 → 执行搜索
4. 勾选影像 → 加入下载队列 → 「下载管理」页开始下载

### NASA Earthdata
1. 注册 Earthdata 账号：https://urs.earthdata.nasa.gov （免费）
2. 「账号配置」页填写 Earthdata 账号 → 测试登录
3. 在 NASA 官网（Earthdata Search / GES DISC）勾选数据，导出 `.txt` URL 列表
4. 「NASA 下载」页导入列表 → 设置保存目录 →（可选）勾选「下载后裁剪」并填研究区 bbox → 开始下载

---

## 项目结构

```
sentinel_downloader/
├── main.py
├── requirements.txt
├── core/
│   ├── config.py           # 常量 + 配置读写 + 设置项（get_setting）
│   ├── datasource.py       # 数据源基类
│   ├── api.py              # CopernicusAPI（Sentinel-1）
│   ├── s2_api.py           # SentinelS2API（Sentinel-2）
│   ├── downloader.py       # CDSE 下载内核（续传 / 重试 / 完整性校验）
│   ├── earthdata.py        # NASA Earthdata 下载内核
│   ├── nc_processor.py     # 下载后空间裁剪（netCDF4 / HDF-EOS5 swath）
│   ├── models.py           # Product 数据模型
│   ├── store.py            # 下载历史 + 搜索缓存 + 队列持久化
│   └── aoi_manager.py      # AOI 解析 / 库管理
└── ui/
    ├── app.py              # 主窗口 + 样式 + 队列持久化
    ├── tab_auth.py         # 账号配置 Tab
    ├── tab_search.py       # 搜索影像 Tab（S1/S2 切换）
    ├── tab_download.py     # 下载管理 Tab（含下载历史）
    ├── tab_nasa.py         # NASA 下载 Tab
    ├── tab_settings.py     # 设置 Tab
    ├── aoi_panel.py        # AOI 管理面板
    └── map_widget.py       # 地图预览 / 画框窗口
```

运行时数据（账号配置、下载历史、缓存、AOI 库、队列、日志）统一存于 exe 同级 `data/`，不纳入版本管理。

---

## 说明

- 建议使用全局 VPN 提升访问 ESA / NASA 服务器速度。
- 扩展新数据源：在 `core/` 下新建文件实现认证与搜索逻辑，即可复用现有下载内核，无需改动 UI。
- `build.py`：运行 `python build.py` 可从源码重新打包为 exe（需 Python 环境 + Pillow，其余依赖自动在隔离 venv 中安装）。
