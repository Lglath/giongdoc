# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for GiongDoc.app (macOS, windowed, onedir bundle).

Build (from the repo root):
    pyinstaller --noconfirm --clean packaging/GiongDoc.spec

Environment knobs:
    GIONGDOC_VERSION              bundle version (default 1.0.0)
    GIONGDOC_FFMPEG_SRC           path to an ffmpeg binary to embed
                                  (default: packaging/vendor/ffmpeg if present)
    GIONGDOC_BUNDLE_CUSTOM_VOICE  "1" to stop excluding torch/f5-tts/TTS
                                  (makes the app several GB; off by default)
    GIONGDOC_TARGET_ARCH          arm64 | x86_64 | universal2 (default: native)
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PACKAGING = Path(SPECPATH).resolve()  # noqa: F821  (SPECPATH is injected by PyInstaller)
ROOT = PACKAGING.parent

APP_NAME = "GiongDoc"
BUNDLE_ID = "com.cuong.giongdoc"
VERSION = os.environ.get("GIONGDOC_VERSION", "1.0.0")
ICON = PACKAGING / "assets" / "GiongDoc.icns"
TARGET_ARCH = os.environ.get("GIONGDOC_TARGET_ARCH") or None
BUNDLE_CUSTOM_VOICE = os.environ.get("GIONGDOC_BUNDLE_CUSTOM_VOICE") == "1"

# --------------------------------------------------------------------------- #
# Data files & hidden imports
# --------------------------------------------------------------------------- #
datas = []
datas += collect_data_files("edge_tts")
datas += collect_data_files("certifi")  # TLS roots for edge-tts (aiohttp)
datas += collect_data_files("giongdoc", excludes=["**/__pycache__", "**/*.pyc"])

hiddenimports = []
hiddenimports += collect_submodules("giongdoc")  # engines/registry load lazily
hiddenimports += collect_submodules("edge_tts")
hiddenimports += ["soundfile"]  # optional; ignored by PyInstaller if not installed

# --------------------------------------------------------------------------- #
# ffmpeg: embedded at Contents/Resources/bin/ffmpeg (audio code looks there,
# and GIONGDOC_FFMPEG overrides at runtime). PyInstaller also collects any
# non-system dylibs it links against and rewrites their load paths.
# --------------------------------------------------------------------------- #
binaries = []
ffmpeg_src = Path(os.environ.get("GIONGDOC_FFMPEG_SRC") or PACKAGING / "vendor" / "ffmpeg")
if ffmpeg_src.is_file():
    print(f"[GiongDoc.spec] embedding ffmpeg from {ffmpeg_src}")
    binaries.append((str(ffmpeg_src), "bin"))
else:
    print("[GiongDoc.spec] WARNING: no ffmpeg found; MP3/M4A export will need a system ffmpeg")

# --------------------------------------------------------------------------- #
# Excludes: trim unused Qt modules and heavy optional stacks.
# The app uses QtCore/QtGui/QtWidgets/QtMultimedia (+ QtNetwork via Multimedia).
# --------------------------------------------------------------------------- #
qt_excludes = [
    "QtWebEngine", "QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick",
    "QtWebChannel", "QtWebSockets", "QtWebView",
    "Qt3DCore", "Qt3DRender", "Qt3DInput", "Qt3DLogic", "Qt3DAnimation", "Qt3DExtras",
    "QtQuick", "QtQuick3D", "QtQuickWidgets", "QtQuickControls2", "QtQml",
    "QtCharts", "QtDataVisualization", "QtGraphs",
    "QtPdf", "QtPdfWidgets", "QtDesigner", "QtUiTools", "QtHelp",
    "QtBluetooth", "QtNfc", "QtPositioning", "QtLocation", "QtSensors",
    "QtSerialPort", "QtSerialBus", "QtRemoteObjects", "QtScxml", "QtStateMachine",
    "QtSql", "QtTest", "QtXml", "QtTextToSpeech", "QtVirtualKeyboard",
    "QtOpenGLWidgets", "QtSpatialAudio", "QtHttpServer",
]
excludes = [f"PySide6.{m}" for m in qt_excludes]
excludes += [
    "tkinter", "_tkinter", "matplotlib", "IPython", "jupyter", "notebook",
    "pytest", "PyQt5", "PyQt6", "PySide2", "pandas", "scipy.tests", "numpy.tests",
]
if not BUNDLE_CUSTOM_VOICE:
    # Custom voice cloning is an optional extra (requirements-custom-voice.txt);
    # the app soft-imports these and disables the feature when absent.
    excludes += ["torch", "torchaudio", "torchvision", "f5_tts", "TTS", "transformers",
                 "librosa", "numba", "llvmlite", "accelerate"]

# --------------------------------------------------------------------------- #
a = Analysis(  # noqa: F821
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX breaks macOS code signatures
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

app = BUNDLE(  # noqa: F821
    coll,
    name=f"{APP_NAME}.app",
    icon=str(ICON) if ICON.exists() else None,
    bundle_identifier=BUNDLE_ID,
    version=VERSION,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "CFBundleDevelopmentRegion": "vi",
        "LSMinimumSystemVersion": "12.0",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,  # allow dark mode
        "NSMicrophoneUsageDescription": (
            "GiongDoc cần dùng micro để ghi âm mẫu giọng nói của chính bạn "
            "(dùng cho tính năng giọng tùy chỉnh)."
        ),
        "NSHumanReadableCopyright": "© 2026 Cuong. All rights reserved.",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "GiongDoc Project",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Owner",
                "CFBundleTypeExtensions": ["giongdoc"],
            }
        ],
    },
)
