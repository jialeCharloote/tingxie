"""py2app build config for Tingxie.app — run via ./make-app.sh.

Why a real .app bundle: macOS TCC permissions (Microphone, Accessibility,
Input Monitoring) attach to the process image. Run from the venv and that's
the Homebrew python binary — every Homebrew python upgrade or unrelated
python script shares (and can invalidate) the grants. py2app's launcher
binary dlopens the embedded Python framework instead of exec'ing python, so
the process stays Tingxie.app/Contents/MacOS/Tingxie and the permissions
stick to the bundle. (A shell-script wrapper .app would NOT achieve this.)

The 230MB models/ dir is deliberately NOT bundled — config.BASE_DIR finds it
via $TINGXIE_HOME or ~/Library/Application Support/Tingxie.
"""

from setuptools import setup

PLIST = {
    "CFBundleName": "Tingxie",
    "CFBundleDisplayName": "Tingxie",
    "CFBundleIdentifier": "com.tingxie.dictation",
    "CFBundleShortVersionString": "1.0.0",
    "CFBundleVersion": "1",
    # Menu-bar app: no Dock icon, no Cmd+Tab entry.
    "LSUIElement": True,
    "LSMinimumSystemVersion": "13.0",
    "NSMicrophoneUsageDescription": (
        "Tingxie records the microphone while you hold fn to dictate."
    ),
    "NSHumanReadableCopyright": "MIT License",
    # App processes get a C/ASCII locale — without this, printing or reading
    # 中文 (transcripts, history.json) dies with Unicode errors. Covers Finder
    # launches; the LaunchAgent plist sets the same variable for launchd runs.
    "LSEnvironment": {"PYTHONUTF8": "1"},
}

OPTIONS = {
    "plist": PLIST,
    # Copied wholesale (unzipped) — these carry native dylibs or data files
    # that don't survive py2app's zip-import packaging.
    "packages": [
        "sherpa_onnx",        # SenseVoice STT + Silero VAD (bundles onnxruntime dylibs)
        "_sounddevice_data",  # libportaudio for sounddevice
        "rumps",
        "pynput",
        "numpy",
        "rich",               # lazy-loads _unicode_data.unicode<N> by computed name
    ],
    "includes": ["sounddevice", "_cffi_backend"],
    # Alternative STT backends and their heavy dep trees — transcribe.py only
    # imports the configured backend, but modulegraph sees all three branches.
    "excludes": [
        "mlx",
        "mlx_whisper",
        "mlx_metal",
        "faster_whisper",
        "ctranslate2",
        "tokenizers",
        "huggingface_hub",
        "transformers",
        "av",
        "onnxruntime",  # VAD goes through sherpa_onnx, not raw onnxruntime
        "soundfile",
        "_soundfile_data",
        "scipy",
        "numba",
        "llvmlite",
        "sympy",
        "pandas",
        "matplotlib",
        "tkinter",
        "setuptools",
        "pip",
        "wheel",
    ],
}

setup(
    name="Tingxie",
    app=["main.py"],
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
