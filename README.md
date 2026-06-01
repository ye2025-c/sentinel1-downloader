# Sentinel-1 SAR 批量搜索 & 下载工具

海河"25·7"洪涝灾害遥感监测数据获取工具，数据源为 [Copernicus Data Space (ESA)](https://dataspace.copernicus.eu)。

可运行程序位于 [`sentinel_downloader/`](sentinel_downloader/)，由原 `数据下载3.0.py` 单文件版本**模块化重构**而来，拆分为 `core/`（业务逻辑）+ `ui/`（界面）两层，便于维护、打包与功能扩展。

> 历史版本：仓库根目录的 `数据下载3.0.py` 为重构前的单文件版本；`原始代码/` 保存更早的迭代，仅作备查。

## 功能

- GUI 图形界面操作（Tkinter）
- OData API 搜索 Sentinel-1 影像（轨道方向 / 极化 / 相对·绝对轨道号 / 成像模式等服务端筛选）
- 按产品名精确搜索（官网复制文件名直接粘贴搜索）
- 批量下载 / 断点续传 / 自动重试 / 并行下载
- Token 自动刷新
- 下载日志与速度实时显示

## 项目结构

```
sentinel_downloader/
├── main.py                 # 入口，只负责启动
├── requirements.txt
├── .gitignore
├── s1_config.json          # 本地配置（账号邮箱与保存路径），不纳入版本管理
│
├── core/                   # 业务逻辑层（无 UI 依赖）
│   ├── config.py           # 常量 + 配置读写
│   ├── api.py              # CopernicusAPI（Token + Search）
│   └── downloader.py       # download() 下载逻辑
│
└── ui/                     # 界面层
    ├── app.py              # App 主窗口 + 样式 + 共享工具
    ├── tab_auth.py         # 账号配置 Tab
    ├── tab_search.py       # 搜索影像 Tab
    └── tab_download.py     # 下载管理 Tab
```

## 依赖与运行

```bash
cd sentinel_downloader
pip install -r requirements.txt
python main.py
```

## 使用步骤

1. 注册 Copernicus 账号：https://dataspace.copernicus.eu （免费）
2. 「账号配置」页填写账号 → 测试登录 → 保存配置
3. 「搜索影像」页设置条件搜索，或在「按产品名搜索」栏粘贴官网复制的文件名
4. 勾选影像 → 加入下载队列 → 「下载管理」页开始下载

## 说明

- 本地配置文件 `s1_config.json`（含账号邮箱与保存路径）不纳入版本管理。
- 建议使用全局 VPN 提升访问 ESA 服务器速度。
