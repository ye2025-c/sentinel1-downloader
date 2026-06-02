# Sentinel 卫星数据批量搜索 & 下载工具

面向遥感科研的桌面数据获取工具，支持 **Sentinel-1（SAR）** 与 **Sentinel-2（光学）** 影像的可视化搜索与批量下载，数据源为 [Copernicus Data Space Ecosystem (ESA)](https://dataspace.copernicus.eu)；并额外支持 **NASA Earthdata** 数据的 URL 列表批量下载。

内置海河"25·7"洪涝灾害遥感监测研究区（AOI）预设。

可运行程序位于 [`sentinel_downloader/`](sentinel_downloader/)，采用 `core/`（业务逻辑）+ `ui/`（界面）两层结构，便于维护、打包与扩展新数据源。

> 历史版本：仓库根目录的 `数据下载3.0.py` 为重构前的单文件版本；`原始代码/` 保存更早的迭代，仅作备查，不再维护。

## 功能

### 数据搜索
- 双数据源切换：**Sentinel-1**（轨道方向 / 极化 / 相对·绝对轨道号 / 成像模式）与 **Sentinel-2**（云量 / 处理级别 L1C·L2A / Tile ID）
- OData 服务端筛选 + 客户端关键字实时过滤
- 按产品名精确搜索（官网复制文件名直接粘贴）
- 搜索结果统计、CSV 导出
- **搜索结果缓存**（24h TTL）：重复搜索秒级响应

### 空间范围管理（AOI）
- 内置研究区预设 + 用户自定义 AOI 库
- **文件导入**：GeoJSON / Shapefile / KML（自动投影转 WGS84）
- **地图画框**：内嵌地图上两次点击绘制矩形范围
- 从下载历史的影像 footprint 反向存为 AOI

### 下载管理
- 批量并行下载 / 断点续传 / 自动重试 / Token 自动刷新
- 下载日志与速度实时显示
- **下载历史**：记录每景下载状态，搜索结果中已下载产品自动标记 ✓

### NASA Earthdata 下载（独立 Tab）
- NASA Earthdata 无检索 API，工作流为「官网勾选 → 导出 `.txt` URL 列表 → 批量下载」
- 导入并解析 URL 列表 → 串行批量下载（文件间礼貌延迟，避免请求过密）
- 复用同款下载策略：`.part` 断点续传 / 失败退避重试 / 原子落盘 / 实时进度与速度
- 认证使用「账号配置」页填写的 Earthdata 账号（HTTP Basic，经 `urs.earthdata.nasa.gov` 重定向）

## 项目结构

```
sentinel_downloader/
├── main.py                 # 入口，只负责启动
├── requirements.txt
│
├── core/                   # 业务逻辑层（无 UI 依赖）
│   ├── config.py           # 常量 + 配置读写
│   ├── datasource.py       # 数据源基类（多数据源扩展接口）
│   ├── api.py              # CopernicusAPI（Sentinel-1）
│   ├── s2_api.py           # SentinelS2API（Sentinel-2）
│   ├── downloader.py       # download() 下载内核（CDSE，数据源无关）
│   ├── earthdata.py        # NASA Earthdata 下载内核（独立于 CDSE）
│   ├── models.py           # Product 数据模型
│   ├── store.py            # 下载历史 + 搜索缓存（JSON 存储）
│   └── aoi_manager.py      # AOI 解析 / 库管理
│
├── ui/                     # 界面层
│   ├── app.py              # App 主窗口 + 样式 + 共享工具
│   ├── tab_auth.py         # 账号配置 Tab（CDSE + Earthdata）
│   ├── tab_search.py       # 搜索影像 Tab（S1/S2 切换）
│   ├── tab_download.py     # 下载管理 Tab（含下载历史）
│   ├── tab_nasa.py         # NASA 下载 Tab（URL 列表批量下载）
│   ├── aoi_panel.py        # AOI 管理面板
│   └── map_widget.py       # 地图预览 / 画框窗口
│
└── data/                   # 本地数据（不纳入版本管理）
    ├── config.json             # 账号邮箱 / Earthdata 用户名 / 保存路径 / 默认时间范围
    ├── download_history.json   # 下载历史
    ├── search_cache.json       # 搜索结果缓存
    ├── aoi_library.json        # 用户自定义 AOI 库
    └── logs/                   # 下载日志（按天分文件）
```

## 依赖与运行

```bash
cd sentinel_downloader
pip install -r requirements.txt
python main.py
```

主要依赖：`requests`、`tqdm`、`ttkbootstrap`（界面主题）、`tkintermapview`（内嵌地图）。

> Shapefile / KML 导入及投影转换依赖 **GDAL**（`osgeo`），需自行通过 conda 等方式安装；未安装时 GeoJSON 导入仍可正常使用。

## 使用步骤

### Sentinel（CDSE）
1. 注册 Copernicus 账号：https://dataspace.copernicus.eu （免费，S1/S2 同一账号）
2. 「账号配置」页填写账号 → 测试登录 → 保存配置
3. 「搜索影像」页顶部选择数据源（Sentinel-1 / Sentinel-2）
4. 设置时间范围、研究区 AOI（预设 / 导入文件 / 地图画框）与产品参数 → 执行搜索
5. 勾选影像 → 加入下载队列 → 「下载管理」页开始下载

### NASA Earthdata
1. 注册 Earthdata 账号：https://urs.earthdata.nasa.gov （免费）
2. 「账号配置」页填写 Earthdata 账号 → 测试登录（HTTP Basic 校验）
3. 在 NASA 官网（如 Earthdata Search / GES DISC）勾选数据并导出 `.txt` URL 列表
4. 「NASA 下载」页导入并解析列表 → 设置保存目录 → 开始下载

## 说明

- 本地数据（账号配置、下载历史、缓存、AOI 库、日志）统一存于 `data/`，通过 `.gitignore` 排除，不纳入版本管理。
- 建议使用全局 VPN 提升访问 ESA 服务器速度。
- 扩展新数据源：在 `core/` 下新建文件继承 `DataSource` 基类，实现认证与搜索逻辑即可复用现有下载内核，无需改动 UI。
