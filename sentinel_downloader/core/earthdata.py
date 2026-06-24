#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NASA Earthdata 批量下载内核
────────────────────────────────────────────────────────
独立于 CDSE 下载内核（core/downloader.py）。NASA Earthdata 没有检索 API，
工作流是「官网勾选 → 导出 .txt URL 列表 → 批量下载」，认证使用 Earthdata
账号（HTTP Basic，经 urs.earthdata.nasa.gov 重定向）。

由 ui/tab_nasa.py 调用。下载策略照搬历史脚本「原始代码/下载数据代码.py」：
流式分块 + .part 断点续传 + 原子落盘 + 失败退避重试 + HTML 登录页检测，
并补充 GUI 所需的 日志 / 进度 / 速度 / 停止 回调。

为什么单独一套内核（不复用 downloader.download）：
  CDSE 内核以 product_id → get_download_url 拼 URL、Bearer Token 认证、
  固定存 .zip；NASA 是现成 URL、Basic 认证经登录重定向、文件名从 URL 取、
  扩展名各异（.he5 等）。两者差异大，分开维护比硬塞进同一函数更稳更清晰。
"""

import os
import time

import requests

# 证书报错时 verify=False 才有意义；这里先关掉 urllib3 的相关告警噪声
requests.packages.urllib3.disable_warnings()

AUTH_HOST = "urs.earthdata.nasa.gov"
AUTH_URL  = "https://urs.earthdata.nasa.gov/home"   # 预认证用，末尾不能有空格

_TIMEOUT   = (15, 600)        # (连接, 读取)；大文件读超时给足
_CHUNK     = 1024 * 256       # 流式分块 256 KB
_MAX_RETRY = 3                # 单文件最大重试次数


class EarthdataSession(requests.Session):
    """保持 Authorization 头跨 Earthdata 登录重定向的会话。

    NASA 官方推荐写法：数据服务器会把请求 302 到 urs.earthdata.nasa.gov
    做认证再跳回。requests 默认在跨主机重定向时丢弃 Authorization 头，
    这里重写 rebuild_auth —— 只在与认证主机相关的跳转中保留账号密码，
    其余跨主机仍然丢弃，避免把凭据泄露给第三方主机。
    """

    def __init__(self, username, password):
        super().__init__()
        self.auth = (username, password)
        self.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })

    def rebuild_auth(self, prepared_request, response):
        headers = prepared_request.headers
        if "Authorization" in headers:
            orig  = requests.utils.urlparse(response.request.url).hostname
            redir = requests.utils.urlparse(prepared_request.url).hostname
            if orig != redir and redir != AUTH_HOST and orig != AUTH_HOST:
                del headers["Authorization"]
        return


def parse_url_list(txt_path):
    """读取 NASA 导出的 .txt URL 列表。

    去空行、去首尾空白、跳过注释行（以 # 开头）。返回 URL 字符串列表。
    """
    with open(txt_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f
                if line.strip() and not line.lstrip().startswith("#")]


def filename_from_url(url):
    """从 URL 取文件名（去掉查询串 ?... 部分）。"""
    return url.split("/")[-1].split("?")[0]


def preauth(session, verify_ssl=False, log_cb=None):
    """预认证：先访问 Earthdata Login 拿到初始 Cookies。

    返回 (ok: bool, status_or_err)。连接失败时 ok=False。
    """
    try:
        r = session.get(AUTH_URL, verify=verify_ssl, timeout=30)
        if log_cb:
            log_cb(f"认证服务状态: {r.status_code}", "info")
        return True, r.status_code
    except Exception as e:
        if log_cb:
            log_cb(f"✗ 认证连接失败: {e}", "err")
        return False, str(e)


def verify_credentials(username, password, verify_ssl=False, timeout=30):
    """验证 Earthdata 账号密码是否有效（HTTP Basic）。

    使用 Earthdata User API 的只读端点 /api/users/tokens —— 专为编程访问设计、
    接受 Basic 认证、不产生副作用（不会新建 token）。判定：
      200 → 账密有效
      401 → 账号或密码错误
      其他 → 无法确认（网络/接口问题），建议直接试下载，下载时仍有
             HTML 登录页检测兜底，避免把边缘情况误判成账密错

    返回 (ok, msg)：ok 为 True/False/None，None 表示"无法确认"。
    """
    url = "https://urs.earthdata.nasa.gov/api/users/tokens"
    try:
        r = requests.get(
            url, auth=(username, password),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            verify=verify_ssl, timeout=timeout,
        )
    except Exception as e:
        return None, f"连接失败：{e}"

    if r.status_code == 200:
        return True, "账号密码有效"
    if r.status_code == 401:
        return False, "账号或密码错误（HTTP 401）"
    return None, f"无法确认（HTTP {r.status_code}），可直接尝试下载"


def download_one(session, url, save_dir, log_cb=None, prog_cb=None,
                 speed_cb=None, stop_event=None,
                 max_retry=_MAX_RETRY, verify_ssl=False):
    """下载单个 URL，支持 .part 断点续传 + 失败重试 + 原子落盘。

    返回 (success: bool, save_path: str | None)。
    认证失败（服务器返回 HTML 登录页）直接判失败，不再重试。
    """
    os.makedirs(save_dir, exist_ok=True)
    filename  = filename_from_url(url)
    save_path = os.path.join(save_dir, filename)
    tmp_path  = save_path + ".part"

    # 最终文件只在校验通过后才会出现，存在即视为完整，可安全跳过
    if os.path.exists(save_path):
        if log_cb:
            log_cb(f"  已存在，跳过（{os.path.getsize(save_path)/1024**2:.1f} MB）", "ok")
        return True, save_path

    for attempt in range(1, max_retry + 1):
        try:
            if stop_event and stop_event.is_set():
                if log_cb: log_cb("  ⏹ 已中止（.part 保留，支持续传）", "warn")
                if speed_cb: speed_cb(0)
                return False, None

            # 已有 .part 则尝试断点续传
            existing = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            headers  = {"Range": f"bytes={existing}-"} if existing else {}

            with session.get(url, headers=headers, stream=True,
                             verify=verify_ssl, timeout=_TIMEOUT,
                             allow_redirects=True) as resp:

                # 认证失败时 Earthdata 通常返回 HTML 登录页
                ctype = resp.headers.get("Content-Type", "")
                if "text/html" in ctype:
                    if log_cb:
                        log_cb("  ✗ 认证失败：返回 HTML 登录页，请检查 Earthdata 账号密码", "err")
                    if speed_cb: speed_cb(0)
                    return False, None

                mode = "ab" if existing else "wb"
                if existing and resp.status_code == 200:
                    # 服务器忽略 Range、从头返回 → 重置续传，避免把整文件追加致损坏
                    if log_cb: log_cb("  ⚠️ 服务器忽略续传（返回200），从头下载", "warn")
                    existing, mode = 0, "wb"
                elif resp.status_code == 416:
                    # 416 = Range 越界，说明 .part 已是完整大小
                    os.replace(tmp_path, save_path)
                    if log_cb: log_cb("  ✅ 已完成（续传校验）", "ok")
                    if speed_cb: speed_cb(0)
                    return True, save_path
                elif existing and resp.status_code == 206:
                    # 206 Partial Content = 服务器接受续传，从断点继续
                    if log_cb:
                        log_cb(f"  ↪ 断点续传：从 {existing/1024**2:.1f} MB 处继续下载", "info")

                resp.raise_for_status()

                total      = int(resp.headers.get("Content-Length", 0)) + existing
                downloaded = existing
                win_bytes, win_start = 0, time.time()

                with open(tmp_path, mode) as f:
                    for chunk in resp.iter_content(chunk_size=_CHUNK):
                        if stop_event and stop_event.is_set():
                            if log_cb: log_cb("  ⏹ 已中止（.part 保留，支持续传）", "warn")
                            if speed_cb: speed_cb(0)
                            return False, None
                        if not chunk:
                            continue
                        f.write(chunk)
                        n           = len(chunk)
                        downloaded += n
                        win_bytes  += n

                        now     = time.time()
                        elapsed = now - win_start
                        if elapsed >= 1.0:              # 每秒更新一次速度
                            if speed_cb: speed_cb(win_bytes / elapsed)
                            win_bytes, win_start = 0, now

                        if prog_cb:
                            # 多带 已下载/总大小（字节），供 UI 显示单文件大小。
                            # 服务器未给 Content-Length 时 total=0、pct 记 0。
                            pct = (downloaded / total * 100) if total else 0
                            prog_cb(pct, downloaded, total)

            # 大小校验：服务器声明了大小但本地不足 → 视为不完整，触发重试
            final_size = os.path.getsize(tmp_path)
            if total and final_size < total:
                raise IOError(f"文件不完整 {final_size}/{total} 字节")

            # 原子落盘：校验通过后才改名为最终文件
            os.replace(tmp_path, save_path)
            if log_cb: log_cb(f"  ✅ 完成（{final_size/1024**2:.1f} MB）", "ok")
            if speed_cb: speed_cb(0)
            return True, save_path

        except Exception as e:
            if log_cb: log_cb(f"  ⚠️ 第{attempt}/{max_retry}次失败: {e}", "warn")
            if attempt < max_retry:
                wait = 5 * attempt
                if log_cb: log_cb(f"     {wait}秒后续传重试...", "info")
                time.sleep(wait)

    if log_cb: log_cb("  ❌ 最终失败（.part 保留，下次可续传）", "err")
    if speed_cb: speed_cb(0)
    return False, None
