#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build script  (venv-isolated, ~50 MB target)
Run:    python build.py
Output: SentinelDownloader.exe  (project root)
Cleans: _build_env/  build/  dist/  *.spec  temp icon -- only the exe remains

Why venv isolation?
  Running PyInstaller inside the full Anaconda environment pulls in hundreds of
  packages (scipy, sklearn, PyQt5, GDAL, tensorflow ...) that the app never
  uses, bloating the exe to 600+ MB.  A minimal venv with only the 4 runtime
  deps produces a ~50 MB exe that starts instantly.
"""

import io
import os
import sys
import shutil
import subprocess
import tempfile

# Force UTF-8 output so GBK terminal doesn't mangle print
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT    = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(ROOT, "sentinel_downloader")
ENTRY   = os.path.join(APP_DIR, "main.py")
ICO     = os.path.join(tempfile.gettempdir(), "_icon.ico")
VENV    = os.path.join(ROOT, "_build_env")
OUT_EXE = os.path.join(ROOT, "SentinelDownloader.exe")

# Only what the app actually needs at runtime.
# Optional deps (osgeo / numpy / netCDF4 / h5py) are intentionally excluded:
# the app already handles their absence gracefully (try/except at import time).
RUNTIME_PACKAGES = [
    "requests",
    "tqdm",
    "ttkbootstrap",
    "tkintermapview",
]


# ─── 图标生成 ────────────────────────────────────────────────
def _generate_icon():
    from PIL import Image, ImageDraw

    def _frame(size: int) -> Image.Image:
        s = size
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        cx  = cy = s // 2

        # 深色圆角背景
        try:
            d.rounded_rectangle([0, 0, s - 1, s - 1],
                                 radius=max(s // 6, 2),
                                 fill=(13, 27, 42, 255))
        except AttributeError:          # Pillow < 8.2
            d.rectangle([0, 0, s - 1, s - 1], fill=(13, 27, 42, 255))

        # 地球（蓝色圆 + 绿色大陆）
        er  = int(s * 0.29)
        ecy = int(s * 0.67)
        d.ellipse([cx - er, ecy - er, cx + er, ecy + er],
                  fill=(20, 88, 165, 255))
        if s >= 32:
            lw = int(er * 0.72)
            lh = int(er * 0.62)
            d.ellipse([cx - lw // 2, ecy - lh, cx + lw // 2 - 2, ecy],
                      fill=(34, 125, 62, 255))
            d.ellipse([cx - er, ecy - er, cx + er, ecy + er],
                      outline=(60, 130, 210, 180), width=max(1, s // 64))

        # 卫星本体（银白色矩形）
        bw  = max(int(s * 0.09), 2)
        bh  = max(int(s * 0.065), 2)
        scy = int(s * 0.27)
        d.rectangle([cx - bw, scy - bh, cx + bw, scy + bh],
                    fill=(210, 215, 225, 255))
        if s >= 48:
            d.rectangle([cx - bw, scy - bh, cx + bw, scy + bh],
                        outline=(150, 165, 180, 255), width=1)

        # 太阳能板（蓝色横板）
        pw  = max(int(s * 0.135), 3)
        ph  = max(int(s * 0.038), 1)
        gap = max(1, s // 80)
        d.rectangle([cx - bw - gap - pw, scy - ph,
                     cx - bw - gap,      scy + ph], fill=(45, 125, 200, 255))
        d.rectangle([cx + bw + gap,      scy - ph,
                     cx + bw + gap + pw, scy + ph], fill=(45, 125, 200, 255))
        if s >= 64:
            mid_l = cx - bw - gap - pw // 2
            mid_r = cx + bw + gap + pw // 2
            d.line([mid_l, scy - ph, mid_l, scy + ph],
                   fill=(30, 95, 160, 255), width=1)
            d.line([mid_r, scy - ph, mid_r, scy + ph],
                   fill=(30, 95, 160, 255), width=1)

        # 信号弧（青色，从卫星向地球扩散）
        if s >= 32:
            arc_top = scy + bh + max(1, s // 48)
            for i, ratio in enumerate([0.17, 0.26, 0.35]):
                r_a   = int(s * ratio)
                alpha = max(255 - i * 60, 90)
                d.arc([cx - r_a, arc_top, cx + r_a, arc_top + r_a],
                      start=205, end=335,
                      fill=(0, 200, 232, alpha),
                      width=max(1, s // 48))
        return img

    sizes  = [256, 128, 64, 48, 32, 16]
    frames = [_frame(s) for s in sizes]
    frames[0].save(ICO, format="ICO",
                   sizes=[(s, s) for s in sizes],
                   append_images=frames[1:])
    print(f"[OK] Icon generated ({len(sizes)} sizes)")


# ─── 隔离 venv ───────────────────────────────────────────────
def _create_venv():
    print("[*] Creating isolated build venv...")
    if os.path.exists(VENV):
        shutil.rmtree(VENV)
    subprocess.check_call([sys.executable, "-m", "venv", VENV],
                          stdout=subprocess.DEVNULL)

    pip = os.path.join(VENV, "Scripts", "pip.exe")
    pkgs = RUNTIME_PACKAGES + ["pyinstaller"]
    print(f"[*] Installing {len(pkgs)} packages: {', '.join(pkgs)}")
    subprocess.check_call([pip, "install", "-q"] + pkgs)
    print("[OK] Venv ready")


# ─── 清理构建产物 ────────────────────────────────────────────
def _cleanup():
    removed = []
    for target in (VENV, os.path.join(ROOT, "build"), os.path.join(ROOT, "dist")):
        if os.path.isdir(target):
            shutil.rmtree(target)
            removed.append(os.path.basename(target) + "/")
    spec = os.path.join(ROOT, "SentinelDownloader.spec")
    if os.path.isfile(spec):
        os.remove(spec)
        removed.append("SentinelDownloader.spec")
    if os.path.isfile(ICO):
        os.remove(ICO)
        removed.append(os.path.basename(ICO))
    if removed:
        print(f"[OK] Cleaned: {', '.join(removed)}")


# ─── 主流程 ─────────────────────────────────────────────────
def build():
    print("[*] Generating icon...")
    _generate_icon()

    _create_venv()
    venv_py = os.path.join(VENV, "Scripts", "python.exe")

    sep      = ";" if sys.platform == "win32" else ":"
    add_data = f"{ICO}{sep}."       # bundle icon; accessible via sys._MEIPASS

    cmd = [
        venv_py, "-m", "PyInstaller",
        "--clean",
        "--onefile",
        "--windowed",               # no console window
        "--name", "SentinelDownloader",
        f"--icon={ICO}",
        f"--add-data={add_data}",
        "--collect-all", "ttkbootstrap",    # themes + CSS
        "--collect-all", "tkintermapview",  # map widget assets
        "--hidden-import", "certifi",       # SSL certs for requests
        "--paths", APP_DIR,                 # resolve core/ ui/ local packages
        ENTRY,
    ]

    print("\n[*] Packaging (--onefile, ~2-3 min)...\n")
    ret = subprocess.run(cmd, cwd=ROOT)

    if ret.returncode != 0:
        print("\n[ERROR] PyInstaller failed -- see output above")
        _cleanup()
        sys.exit(1)

    src = os.path.join(ROOT, "dist", "SentinelDownloader.exe")
    if os.path.isfile(src):
        if os.path.isfile(OUT_EXE):
            os.remove(OUT_EXE)
        shutil.move(src, OUT_EXE)
        size_mb = os.path.getsize(OUT_EXE) / 1024 / 1024
        print(f"\n[DONE] Build complete! ({size_mb:.0f} MB)")
        print(f"       {OUT_EXE}")
    else:
        print("\n[ERROR] Output exe not found -- check dist/ directory")

    _cleanup()


if __name__ == "__main__":
    build()
