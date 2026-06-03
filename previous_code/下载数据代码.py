#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NASA Earthdata 批量下载工具
────────────────────────────────────────────────────────
通过 NASA 提供的 .txt URL 列表批量下载卫星数据（如 OMI OMSO2 等 HE5 产品）。

认证方式：.netrc 文件（推荐）
    在用户主目录创建 .netrc（Windows 为 %USERPROFILE%\\_netrc，Linux/Mac 为 ~/.netrc）：
        machine urs.earthdata.nasa.gov
            login 你的Earthdata用户名
            password 你的Earthdata密码

依赖：
    pip install requests tqdm
"""

import os
import time
import requests

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None   # 没装 tqdm 也能跑，只是没有进度条

# 禁用 SSL 警告（仅在 VERIFY_SSL=False 时有意义）
requests.packages.urllib3.disable_warnings()

# ───────────────────────────── 配置 ─────────────────────────────
URL_LIST_FILE = r"G:\浏览器下载\subset_OMSO2_004_20260402_032024_moxic.txt"
SAVE_DIR      = r"F:\MOXICO\MOXICOdata_v004_omi"

VERIFY_SSL = False   # 证书报错时设为 False；网络正常建议改 True 更安全
MAX_RETRY  = 3       # 单文件最大重试次数
DELAY      = 2       # 每个文件下载之间的间隔（秒），避免请求过密
TIMEOUT    = 600     # 单次请求超时（秒），大文件需较长时间
CHUNK      = 1024 * 256   # 流式下载块大小（256 KB）

AUTH_URL = "https://urs.earthdata.nasa.gov/home"   # 预认证用，注意末尾不能有空格


def make_session():
    """创建带 Earthdata 认证的会话（依赖 .netrc）。"""
    session = requests.Session()
    session.trust_env = True   # 关键：自动读取 .netrc 文件
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    })
    return session


def download_one(session, url, save_dir, idx, total):
    """
    下载单个文件，支持断点续传 + 失败重试 + 原子落盘。

    返回 True 表示成功（或已存在完整文件），False 表示最终失败。
    """
    filename  = url.split("/")[-1].split("?")[0]
    save_path = os.path.join(save_dir, filename)
    tmp_path  = save_path + ".part"

    # 最终文件只在“校验通过后”才会出现，因此存在即视为完整，可安全跳过
    if os.path.exists(save_path):
        print(f"[{idx}/{total}] 已存在(跳过): {filename} "
              f"({os.path.getsize(save_path)/1024/1024:.1f}MB)")
        return True

    for attempt in range(1, MAX_RETRY + 1):
        try:
            # 已有 .part 则尝试断点续传
            existing = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            headers  = {"Range": f"bytes={existing}-"} if existing else {}

            with session.get(url, headers=headers, stream=True,
                             verify=VERIFY_SSL, timeout=TIMEOUT,
                             allow_redirects=True) as resp:

                # 认证失败时 Earthdata 通常返回 HTML 登录页
                ctype = resp.headers.get("Content-Type", "")
                if "text/html" in ctype:
                    print("  ✗ 认证失败：返回 HTML 登录页，请检查 .netrc 用户名/密码")
                    return False

                # 服务器忽略 Range、从头返回 → 重置续传
                mode = "ab" if existing else "wb"
                if existing and resp.status_code == 200:
                    existing, mode = 0, "wb"
                # 416 = Range 越界，说明 .part 已是完整大小
                elif resp.status_code == 416:
                    os.replace(tmp_path, save_path)
                    print(f"[{idx}/{total}] ✓ 已完成(续传校验): {filename}")
                    return True

                resp.raise_for_status()

                total_size = int(resp.headers.get("Content-Length", 0)) + existing

                bar = None
                if tqdm:
                    bar = tqdm(total=total_size or None, initial=existing,
                               unit="B", unit_scale=True, unit_divisor=1024,
                               desc=filename[:28], leave=False)

                with open(tmp_path, mode) as f:
                    for chunk in resp.iter_content(chunk_size=CHUNK):
                        if chunk:
                            f.write(chunk)
                            if bar:
                                bar.update(len(chunk))
                if bar:
                    bar.close()

            # 大小校验：服务器声明了大小但本地不足 → 视为不完整，触发重试
            final_size = os.path.getsize(tmp_path)
            if total_size and final_size < total_size:
                raise IOError(f"文件不完整 {final_size}/{total_size} 字节")

            # 原子落盘：校验通过后才改名为最终文件
            os.replace(tmp_path, save_path)
            print(f"[{idx}/{total}] ✓ 完成: {filename} ({final_size/1024/1024:.2f} MB)")
            return True

        except Exception as e:
            print(f"  ⚠ 第 {attempt}/{MAX_RETRY} 次失败: {e}")
            if attempt < MAX_RETRY:
                wait = 5 * attempt
                print(f"     {wait}s 后重试...")
                time.sleep(wait)

    print(f"[{idx}/{total}] ✗ 最终失败: {filename}（已保留 .part，下次可续传）")
    return False


def main():
    if not os.path.exists(URL_LIST_FILE):
        print(f"✗ 找不到 URL 列表文件: {URL_LIST_FILE}")
        return

    os.makedirs(SAVE_DIR, exist_ok=True)

    # 读取 URL 列表（去空行、去首尾空白，跳过注释行）
    with open(URL_LIST_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f
                if line.strip() and not line.lstrip().startswith("#")]

    if not urls:
        print("✗ URL 列表为空")
        return

    print(f"共 {len(urls)} 个文件待下载")
    print(f"保存目录: {SAVE_DIR}\n")

    session = make_session()

    # 预认证：先访问 Earthdata Login 获取初始 Cookies
    print("正在连接 Earthdata Login...")
    try:
        r = session.get(AUTH_URL, verify=VERIFY_SSL, timeout=30)
        print(f"认证服务状态: {r.status_code}\n")
    except Exception as e:
        print(f"✗ 认证连接失败: {e}")
        return

    ok = 0
    for i, url in enumerate(urls, 1):
        if download_one(session, url, SAVE_DIR, i, len(urls)):
            ok += 1
        time.sleep(DELAY)   # 文件之间的礼貌性延迟

    print(f"\n═══ 全部结束：成功 {ok}/{len(urls)} 个 ═══")


if __name__ == "__main__":
    main()
