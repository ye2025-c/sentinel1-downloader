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

import requests

from core.config import DOWNLOAD_URL


def download(api, product_id, product_name, save_dir,
             username, password, log_cb=None, prog_cb=None,
             speed_cb=None, stop_event=None, max_retry=5):
    """
    支持断点续传 / 失败重试。

    修复要点（ConnectionResetError 10054）：
    1. max_retry 从 3 提升到 5
    2. timeout 拆为 (connect_timeout, read_timeout) 元组
    3. 重试等待改为指数退避（10s, 20s, 40s, 80s, 上限120s）
    4. ConnectionResetError 单独捕获，不刷新 Token（Token 未过期，刷新无意义）
    5. 所有异常重试时都正确利用断点续传（已有文件不删除）
    6. iter_content chunk_size 从 64KB 提升到 1MB，减少单次传输次数

    返回 (success: bool, save_path: str | None)
    """
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, product_name + ".zip")

    for attempt in range(1, max_retry + 1):
        try:
            api.refresh_if_needed(username, password)
            existing = os.path.getsize(save_path) if os.path.exists(save_path) else 0
            headers  = {"Authorization": f"Bearer {api.token}"}

            # ── 先用 HEAD 请求获取服务器文件大小，用于断点续传校验 ──
            head_resp = requests.head(
                DOWNLOAD_URL.format(id=product_id),
                headers=headers,
                timeout=(15, 30),       # (connect, read)
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

            url = DOWNLOAD_URL.format(id=product_id)
            # ── 关键修复：timeout 拆为元组，read_timeout 设 120s ────
            # connect_timeout=15s：建立 TCP 连接的最长等待
            # read_timeout=120s：两次 chunk 之间最长允许的空闲时间
            # 服务器一般在 60-90s 无数据后 RST，设 120s 是为了在此之前
            # 收到异常并进入重试，而不是被动等到系统层面报错
            resp = requests.get(url, headers=headers, stream=True, timeout=(15, 120))

            if resp.status_code == 416:
                # 双重保险：416 时再次校验大小
                actual_size = os.path.getsize(save_path) if os.path.exists(save_path) else 0
                if server_size and actual_size != server_size:
                    if log_cb:
                        log_cb(f"  ⚠️ 416 但文件大小不一致"
                               f"（本地 {actual_size}B vs 服务器 {server_size}B），重新下载", "warn")
                    existing = 0
                    headers.pop("Range", None)
                    resp = requests.get(url, headers=headers, stream=True, timeout=(15, 120))
                else:
                    if log_cb: log_cb("  文件已完整，跳过", "ok")
                    return True, save_path

            resp.raise_for_status()
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
                        prog_cb(downloaded / total * 100)

            if log_cb: log_cb(f"  ✅ 完成: {save_path}", "ok")
            if speed_cb: speed_cb(0)            # 完成后清零速度显示
            return True, save_path

        except (ConnectionResetError, ConnectionError) as e:
            # ── 连接被服务器重置：Token 没过期，不刷新；直接利用断点续传重试 ──
            done_mb = os.path.getsize(save_path) / 1024**2 if os.path.exists(save_path) else 0
            if log_cb:
                log_cb(f"  ⚠️ 第{attempt}次连接中断（服务器重置），"
                       f"已下载 {done_mb:.1f} MB 保留", "warn")
            if attempt < max_retry:
                wait = min(10 * (2 ** (attempt - 1)), 120)   # 10s, 20s, 40s, 80s, 上限120s
                if log_cb: log_cb(f"     {wait}秒后续传重试（第{attempt+1}/{max_retry}次）...", "info")
                time.sleep(wait)
            # 不刷新 Token，直接下一轮 attempt，利用已有文件断点续传

        except Exception as e:
            # ── 其他异常（Token 过期、网络超时等）：刷新 Token 再重试 ──
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
