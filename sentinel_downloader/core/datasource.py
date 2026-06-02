#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源基类（V4.0 多数据源扩展接口）
────────────────────────────────────────────────────────
DataSource 定义所有数据源必须实现的最小接口，供 downloader.py 调用。

设计原则：
  - 极简：只抽象 downloader.py 真正依赖的三件事
      ① 认证刷新    refresh_if_needed(username, password)
      ② 请求头构造  get_auth_headers() → dict
      ③ 下载 URL    get_download_url(product_id) → str
  - 不强制 ABC：子类按需重写，未重写时抛 NotImplementedError 而非静默错误
  - 搜索接口不在此抽象（各数据源参数差异太大，强行统一反而碍事）

扩展方式：
  新数据源在 core/ 下新建文件（如 core/s2_api.py），继承 DataSource，
  重写三个方法即可接入现有下载内核，无需修改 downloader.py 和 UI。
"""

import threading


class DataSource:
    """所有数据源的基类。子类只需重写下面三个方法。"""

    name: str = "Unknown DataSource"

    def __init__(self):
        self.token      = None
        self.token_time = 0
        self._token_lock = threading.Lock()

    # ── 子类必须重写的三个方法 ─────────────────────────────

    def refresh_if_needed(self, username: str, password: str):
        """Token 过期时刷新；多线程安全。

        应自行维护 self.token 和 self.token_time。
        """
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 refresh_if_needed()")

    def get_auth_headers(self) -> dict:
        """返回下载请求所需的认证头（如 Bearer Token / API Key）。

        默认实现为 Bearer Token；不用 Bearer 的子类直接重写。
        """
        return {"Authorization": f"Bearer {self.token}"}

    def get_download_url(self, product_id: str) -> str:
        """根据产品 ID 构造下载 URL。"""
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 get_download_url()")
