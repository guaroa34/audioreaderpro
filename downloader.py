"""
Módulo B: Motor de Descarga con yt-dlp
Descarga audio o video desde YouTube en un hilo secundario.
FFmpeg extrae el audio si se elige modo 'video'.
"""
import os
import threading
from typing import Callable

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False

# ── Utilidad: detectar FFmpeg ────────────────────────────────────────────────
def _ffmpeg_available() -> bool:
    """Retorna True si FFmpeg está instalado y disponible en el PATH."""
    import shutil
    return shutil.which("ffmpeg") is not None


# Directorio de descargas por defecto (Android: almacenamiento externo)
try:
    from jnius import autoclass  # type: ignore[import-untyped]
    Environment = autoclass("android.os.Environment")
    _DOWNLOADS_DIR = str(
        Environment.getExternalStoragePublicDirectory(
            Environment.DIRECTORY_DOWNLOADS
        ).getAbsolutePath()
    )
except Exception:
    _DOWNLOADS_DIR = os.path.join(os.path.expanduser("~"), "Downloads")


class DownloadProgress:
    """Contenedor de estado de descarga para callbacks de UI."""
    def __init__(self):
        self.percent: float = 0.0
        self.speed: str = ""
        self.eta: str = ""
        self.status: str = "idle"   # idle | downloading | processing | done | error
        self.filename: str = ""
        self.error: str = ""


class YouTubeDownloader:
    """
    Descarga audio o video de YouTube de forma asíncrona.

    Parámetros de callbacks (todos opcionales, se llaman desde el hilo secundario):
        on_progress(DownloadProgress) — actualización de progreso
        on_done(filepath: str)        — descarga completada con éxito
        on_error(message: str)        — error durante la descarga
    """

    def __init__(
        self,
        download_dir: str = _DOWNLOADS_DIR,
        on_progress: Callable[[DownloadProgress], None] | None = None,
        on_done: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        self.download_dir = download_dir
        self.on_progress = on_progress
        self.on_done = on_done
        self.on_error = on_error
        self._progress = DownloadProgress()
        self._thread: threading.Thread | None = None

    # ── API pública ──────────────────────────────────────────────────────────

    def download_audio(self, url: str) -> None:
        """Inicia la descarga solo del audio (MP3 128 kbps) en segundo plano."""
        self._start(url, mode="audio")

    def download_video(self, url: str) -> None:
        """Inicia la descarga del video completo en segundo plano."""
        self._start(url, mode="video")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Implementación interna ───────────────────────────────────────────────

    def _start(self, url: str, mode: str) -> None:
        if self.is_running():
            return  # ya hay una descarga en curso
        if not YT_DLP_AVAILABLE:
            self._emit_error("yt-dlp no está instalado. Ejecuta: pip install yt-dlp")
            return

        self._progress = DownloadProgress()
        self._thread = threading.Thread(
            target=self._run,
            args=(url, mode),
            daemon=True,
        )
        self._thread.start()

    def _run(self, url: str, mode: str) -> None:
        os.makedirs(self.download_dir, exist_ok=True)
        self._progress.status = "downloading"
        self._progress.filename = ""

        ydl_opts = self._build_opts(mode)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            self._emit_error(str(exc))
            return
        except Exception as exc:
            self._emit_error(f"Error inesperado: {exc}")
            return

        filepath = self._progress.filename
        if not filepath:
            self._emit_error("No se pudo determinar la ruta del archivo descargado.")
            return

        self._progress.status = "done"
        if self.on_done:
            self.on_done(filepath)

    def _build_opts(self, mode: str) -> dict:
        has_ffmpeg = _ffmpeg_available()
        base = {
            "outtmpl": os.path.join(self.download_dir, "%(title)s.%(ext)s"),
            "progress_hooks": [self._hook],
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": False,
        }

        if mode == "audio":
            if has_ffmpeg:
                base.update({
                    "format": "bestaudio/best",
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "128",
                    }],
                })
            else:
                # Sin FFmpeg: descarga audio nativo m4a/webm/opus (no necesita post-proceso)
                base.update({
                    "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
                })
        else:  # video
            if has_ffmpeg:
                base.update({
                    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "merge_output_format": "mp4",
                })
            else:
                # Sin FFmpeg: descarga el mejor single-file mp4 disponible
                base.update({
                    "format": "best[ext=mp4]/best",
                })

        return base

    def _hook(self, d: dict) -> None:
        """Llamado internamente por yt-dlp en cada actualización."""
        if d["status"] == "downloading":
            raw = d.get("_percent_str", "0%").strip().replace("%", "")
            try:
                self._progress.percent = float(raw)
            except ValueError:
                pass
            self._progress.speed = d.get("_speed_str", "").strip()
            self._progress.eta   = d.get("_eta_str", "").strip()
            self._progress.status = "downloading"
        elif d["status"] == "finished":
            self._progress.percent = 100.0
            self._progress.status = "processing"
            # Guardar el filepath real que yt-dlp usó
            filename = d.get("filename") or d.get("info_dict", {}).get("_filename", "")
            if filename and isinstance(filename, str):
                self._progress.filename = filename

        if self.on_progress:
            self.on_progress(self._progress)

    def _emit_error(self, message: str) -> None:
        self._progress.status = "error"
        self._progress.error = message
        if self.on_error:
            self.on_error(message)


# ── Utilidad: obtener metadatos sin descargar ────────────────────────────────

def fetch_metadata(url: str) -> dict | None:
    """
    Retorna {'title', 'duration', 'thumbnail'} de una URL de YouTube
    sin descargar el archivo. Retorna None si falla.
    """
    if not YT_DLP_AVAILABLE:
        return None
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "title":     info.get("title", "Sin título"),
                "duration":  info.get("duration", 0.0),
                "thumbnail": info.get("thumbnail", None),
            }
    except Exception:
        return None
