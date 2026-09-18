# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把 SellPilot 打成单文件可执行程序。

请通过 `python build.py` 调用（它会做环境检查与产物提示）。

说明：
- PyInstaller 不支持交叉编译 —— Windows 的 .exe 必须在 Windows 上执行本配置生成；
  在 macOS / Linux 上执行则得到对应平台的可执行文件。
- config.RESOURCE_DIR 在单文件模式下指向解包临时目录，因此 ui/ 会随包释放；
  config.BASE_DIR 指向可执行文件所在目录，.env 与日志都落在程序旁边。
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)

hiddenimports = [
    "dotenv",
    # uvicorn 的循环 / 协议 / 生命周期实现都是按字符串动态挑选的，静态分析扫不到
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "webview",
]

# 这些库大量使用动态导入，显式收集子模块；未安装时跳过
# （缺少 langgraph 时应用会退化为「本地规则兜底模式」，仍然可用）
for _pkg in ("langchain_openai", "langgraph", "langchain_core"):
    try:
        hiddenimports += collect_submodules(_pkg)
    except Exception:  # noqa: BLE001 - 收集失败不影响其它模块打包
        pass

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "ui"), "ui"),                 # 前端资源（只读，从 _MEIPASS 读取）
        (str(ROOT / ".env.example"), "."),        # 配置模板，首次运行可照抄
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "_pytest", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SellPilot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # 未安装 UPX 时不压缩，避免构建告警
    runtime_tmpdir=None,
    console=False,             # 窗口程序：无控制台，运行日志写到程序旁的 sellpilot.log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
