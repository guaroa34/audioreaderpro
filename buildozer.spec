[app]

# ── Identidad ──────────────────────────────────────────────────────────────
title           = AudioReader Pro
package.name    = audioreaderpro
package.domain  = com.tudominio

source.dir      = .
source.include_exts = py,png,jpg,kv,atlas
source.exclude_dirs = .git, __pycache__, tests, .venv, .buildozer

version         = 1.0

# ── Requisitos ──────────────────────────────────────────────────────────────
# pygame e imageio-ffmpeg son solo para escritorio (el código los omite en Android)
requirements = python3,kivy==2.3.0,kivymd==1.2.0,yt-dlp,pyjnius,android,requests

# ── Icono y pantalla de carga ───────────────────────────────────────────────
# presplash.filename = %(source.dir)s/assets/presplash.png
# icon.filename      = %(source.dir)s/assets/icon.png

# ── Orientación ─────────────────────────────────────────────────────────────
orientation = portrait

# ── SDK de Android ──────────────────────────────────────────────────────────
android.minapi    = 23
android.api       = 33
android.ndk       = 25b
android.archs     = arm64-v8a, armeabi-v7a

# ── Permisos ────────────────────────────────────────────────────────────────
android.permissions = \
    READ_EXTERNAL_STORAGE, \
    WRITE_EXTERNAL_STORAGE, \
    INTERNET, \
    WAKE_LOCK, \
    FOREGROUND_SERVICE

# ── Extras de compilación ───────────────────────────────────────────────────
android.accept_sdk_license = True

# ── Buildozer / p4a ─────────────────────────────────────────────────────────
[buildozer]
log_level    = 2
warn_on_root = 1
