#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单产品下载逻辑
────────────────────────────────────────────────────────
从原 CopernicusAPI.download 方法提取为独立函数。
第一个参数 api 传入 CopernicusAPI 实例，用于调用 refresh_if_needed / get_token。
"""

import os
import time
import zipfile

import requests

from core.config import get_setting


class IncompleteDownloadError(Exception):
    """下载结束后完整性校验未通过（大小不足 / ZIP 结构损坏）。

    归入"续传重试、不刷 Token"分支：保留已下文件，退避后用 Range 续传补齐。
    """


def download(api, product_id, product_name, save_dir,
             username, password, log_cb=None, prog_cb=None,
             speed_cb=None, stop_event=None, max_retry=None):
    """
    支持断点续传 / 失败重试。

    修复要点（ConnectionResetError 10054）：
    1. max_retry 从 3 提升到 5
    2. timeout 拆为 (connect_timeout, read_timeout) 元组
    3. 重试等待改为指数退避（10s, 20s, 40s, 80s, 上限120s）
    4. ConnectionResetError 单独捕获，不刷新 Token（Token 未过期，刷新无意义）
    5. 所有异常重试时都正确利用断点续传（已有文件不删除）
    6. iter_content chunk_size 从 64KB 提升到 1MB，减少单次传输次数
    7. requests.exceptions.ConnectionError / ChunkedEncodingError / Timeout
       并非内置 ConnectionError 子类，必须显式归入「续传不刷 Token」分支，
       否则连接中断会被误当作 Token 问题，白白刷新并丢失退避节奏
    8. 续传守卫：请求了 Range 却返回 200（服务器忽略续传、从头发整文件）时，
       重置为覆盖写，避免把完整文件追加到已有数据后导致损坏

    返回 (success: bool, save_path: str | None)
    """
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, product_name + ".zip")

    # 可调参数统一从设置读取（缺省回退默认，见 core/config.py:_DEFAULT_SETTINGS）
    if max_retry is None:
        max_retry = get_setting("max_retry")
    connect_timeout  = get_setting("connect_timeout")
    read_timeout     = get_setting("read_timeout")
    verify_integrity = get_setting("verify_integrity")

    for attempt in range(1, max_retry + 1):
        try:
            api.refresh_if_needed(username, password)
            existing = os.path.getsize(save_path) if os.path.exists(save_path) else 0
            headers  = api.get_auth_headers()
            url      = api.get_download_url(product_id)

            # ── 先用 HEAD 请求获取服务器文件大小，用于断点续传校验 ──
            head_resp = requests.head(
                url,
                headers=headers,
                timeout=(connect_timeout, 30),   # (connect, read)；HEAD 只取元数据
                allow_redirects=True
            )
            server_size = int(head_resp.headers.get("content-length", 0))

            if existing and server_size:
                if existing == server_size:
                    if log_cb:
                        log_cb(f"  文件已完整（{existing/1024**2:.1f} MB），跳过", "ok")
                    return True, save_path
                elif existing < server_size:
                    headers["Range"] = f"bytes={existing}-"
                    if log_cb:
                        log_cb(f"  断点续传，已有 {existing/1024**2:.1f} MB"
                               f" / 共 {server_size/1024**2:.1f} MB", "info")
                else:
                    # 本地比服务器大，文件可能损坏，重新下载
                    if log_cb:
                        log_cb("  本地文件异常，重新下载", "warn")
                    existing = 0
                    headers.pop("Range", None)

            # ── 关键修复：timeout 拆为元组，read_timeout 设 120s ────
            # connect_timeout=15s：建立 TCP 连接的最长等待
            # read_timeout=120s：两次 chunk 之间最长允许的空闲时间
            # 服务器一般在 60-90s 无数据后 RST，设 120s 是为了在此之前
            # 收到异常并进入重试，而不是被动等到系统层面报错
            resp = requests.get(url, headers=headers, stream=True,
                                 timeout=(connect_timeout, read_timeout))

            if resp.status_code == 416:
                # 双重保险：416 时再次校验大小
                actual_size = os.path.getsize(save_path) if os.path.exists(save_path) else 0
                if server_size and actual_size != server_size:
                    if log_cb:
                        log_cb(f"  ⚠️ 416 但文件大小不一致"
                               f"（本地 {actual_size}B vs 服务器 {server_size}B），重新下载", "warn")
                    existing = 0
                    headers.pop("Range", None)
                    resp = requests.get(url, headers=headers, stream=True,
                                 timeout=(connect_timeout, read_timeout))
                else:
                    if log_cb: log_cb("  文件已完整，跳过", "ok")
                    return True, save_path

            resp.raise_for_status()

            # ── 续传守卫：请求了 Range 却返回 200（而非 206）─────────────
            # 说明服务器忽略了 Range，正在从第 0 字节发送完整文件。
            # 若此时仍以 "ab" 追加，会把完整文件接在已有数据之后导致损坏，
            # 必须重置为从头覆盖写。
            if existing and resp.status_code == 200:
                if log_cb:
                    log_cb("  ⚠️ 服务器忽略续传请求（返回 200），从头重新下载", "warn")
                existing = 0

            total      = int(resp.headers.get("content-length", 0)) + existing
            mode       = "ab" if existing else "wb"
            downloaded = existing

            # ── 实时速度计算 ──
            speed_window_bytes = 0
            speed_window_start = time.time()

            with open(save_path, mode) as f:
                # ── chunk_size 提升到 1MB，减少循环次数 ───────────────
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    # ── 每个 chunk 检查停止信号，立即响应 ──
                    if stop_event and stop_event.is_set():
                        if log_cb: log_cb("  ⏹ 下载已中止（文件保留，支持续传）", "warn")
                        if speed_cb: speed_cb(0)
                        return False, None

                    if not chunk:
                        continue
                    f.write(chunk)
                    chunk_len           = len(chunk)
                    downloaded          += chunk_len
                    speed_window_bytes  += chunk_len

                    now     = time.time()
                    elapsed = now - speed_window_start
                    if elapsed >= 1.0:          # 每秒更新一次速度
                        speed_bps          = speed_window_bytes / elapsed
                        speed_window_bytes = 0
                        speed_window_start = now
                        if speed_cb:
                            speed_cb(speed_bps)

                    if total and prog_cb:
                        prog_cb(downloaded / total * 100, downloaded, total)

            # ── 完整性校验：服务器声明了大小却没下满 → 判不完整、续传重试 ──
            final_size = os.path.getsize(save_path)
            if server_size and final_size < server_size:
                raise IncompleteDownloadError(
                    f"文件不完整 {final_size}/{server_size} 字节")
            # ZIP 结构校验（只读尾部中央目录，快）；可在设置关闭
            if verify_integrity and not zipfile.is_zipfile(save_path):
                raise IncompleteDownloadError("ZIP 结构校验未通过")

            if log_cb: log_cb(f"  ✅ 完成: {save_path}", "ok")
            if speed_cb: speed_cb(0)            # 完成后清零速度显示
            return True, save_path

        except (ConnectionResetError,
                ConnectionError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.Timeout,
                IncompleteDownloadError) as e:
            # ── 连接中断 / 完整性校验未过：服务器重置(10054) / 分块传输中断 /
            #    读超时 / 下载不完整 ───────────────────────────────────────
            # 这类错误 Token 并未过期，刷新无意义；只需保留已下载部分、
            # 退避后断点续传重试。
            # 注意：requests.exceptions.ConnectionError 等并非内置 ConnectionError
            # 的子类，必须显式列出，否则会漏到下面的 Token 刷新分支。
            done_mb = os.path.getsize(save_path) / 1024**2 if os.path.exists(save_path) else 0
            if log_cb:
                log_cb(f"  ⚠️ 第{attempt}次传输中断/校验未过（{type(e).__name__}），"
                       f"已下载 {done_mb:.1f} MB 保留", "warn")
            if attempt < max_retry:
                wait = min(10 * (2 ** (attempt - 1)), 120)   # 10s, 20s, 40s, 80s, 上限120s
                if log_cb: log_cb(f"     {wait}秒后续传重试（第{attempt+1}/{max_retry}次）...", "info")
                time.sleep(wait)
            # 不刷新 Token，直接下一轮 attempt，利用已有文件断点续传

        except Exception as e:
            # ── 其他异常（Token 过期 401、服务端 5xx 等）：刷新 Token 再重试 ──
            if log_cb: log_cb(f"  ⚠️ 第{attempt}次失败: {e}", "warn")
            if attempt < max_retry:
                wait = min(10 * attempt, 60)
                if log_cb: log_cb(f"     {wait}秒后重试...", "info")
                time.sleep(wait)
                try:
                    api.get_token(username, password)
                except Exception:
                    pass

    if log_cb: log_cb(f"  ❌ 最终失败，已跳过", "err")
    if speed_cb: speed_cb(0)
    return False, None
