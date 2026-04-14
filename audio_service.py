"""
Módulo: Servicio de Audio en Segundo Plano (Android)
Usa Pyjnius para interactuar con MediaPlayer de Android y mantener
el audio activo con la pantalla bloqueada (WAKE_LOCK).

En escritorio (desarrollo), recae en el backend de Kivy SoundLoader.
"""
import os
import threading
from typing import Callable

# ─── Detección de plataforma ─────────────────────────────────────────────────
try:
    from jnius import autoclass, cast, PythonJavaClass, java_method  # type: ignore[import-untyped]
    from android.runnable import run_on_ui_thread          # type: ignore
    from android import mActivity                          # type: ignore

    _ON_ANDROID = True

    # Clases Java necesarias
    MediaPlayer        = autoclass("android.media.MediaPlayer")
    AudioManager       = autoclass("android.media.AudioManager")
    PowerManager       = autoclass("android.os.PowerManager")
    Context            = autoclass("android.content.Context")
    Uri                = autoclass("android.net.Uri")

except Exception:
    _ON_ANDROID = False


# ─── Backend escritorio (desarrollo / pruebas) ───────────────────────────────
if not _ON_ANDROID:
    import re as _re
    import subprocess
    import tempfile
    import time as _time
    import pygame as _pygame

    import imageio_ffmpeg as _imageio_ffmpeg
    _FFMPEG_EXE = _imageio_ffmpeg.get_ffmpeg_exe()

    # Extensiones que necesitan extracción de audio antes de reproducir
    _VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".m4v",
                   ".webm", ".flv", ".ts", ".3gp"}

    # Cache: (path, speed) → path_audio_extraído
    _audio_cache: dict[tuple, str] = {}

    def _build_atempo(speed: float) -> list[str]:
        """
        Construye la cadena de filtros atempo para FFmpeg.
        Cada filtro acepta valores entre 0.5 y 2.0, por lo que se encadenan
        múltiples filtros para velocidades fuera de ese rango.
        Retorna lista vacía si speed == 1.0 (sin filtro necesario).
        """
        if speed == 1.0:
            return []
        filters = []
        r = speed
        while r > 2.0:
            filters.append("atempo=2.0")
            r /= 2.0
        while r < 0.5:
            filters.append("atempo=0.5")
            r *= 2.0
        filters.append(f"atempo={r:.6f}")
        return filters

    def _extract_audio(src_path: str, speed: float = 1.0) -> str | None:
        """
        Extrae el audio de cualquier archivo (video o audio) a MP3
        aplicando la velocidad indicada con el filtro atempo de FFmpeg.
        Cachea el resultado para no re-procesar el mismo archivo+velocidad.
        """
        cache_key = (src_path, round(speed, 4))
        if cache_key in _audio_cache:
            cached = _audio_cache[cache_key]
            if os.path.exists(cached) and os.path.getsize(cached) > 0:
                return cached

        tmp = tempfile.NamedTemporaryFile(
            suffix=".mp3", prefix="audioreader_", delete=False
        )
        tmp.close()
        out_path = tmp.name

        cmd = [_FFMPEG_EXE, "-y", "-i", src_path, "-vn"]

        atempo = _build_atempo(speed)
        if atempo:
            cmd += ["-filter:a", ",".join(atempo)]

        cmd += ["-acodec", "libmp3lame", "-ab", "128k", "-ar", "44100", out_path]

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=600)
            if result.returncode == 0 and os.path.getsize(out_path) > 0:
                _audio_cache[cache_key] = out_path
                return out_path
            else:
                err = result.stderr.decode("utf-8", errors="replace")[-500:]
                print(f"[AudioService] FFmpeg error: {err}")
        except Exception as exc:
            print(f"[AudioService] FFmpeg exception: {exc}")
        return None

    def _probe_duration(path: str) -> float:
        """Obtiene la duración original del archivo en segundos usando FFmpeg."""
        try:
            r = subprocess.run(
                [_FFMPEG_EXE, "-i", path],
                capture_output=True, timeout=10,
            )
            output = r.stderr.decode("utf-8", errors="replace")
            m = _re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", output)
            if m:
                h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                return h * 3600 + mi * 60 + s
        except Exception:
            pass
        return 0.0

    class _DesktopPlayer:
        """
        Reproductor de escritorio con pygame.mixer + FFmpeg.

        Velocidad real:
          - Usa el filtro `atempo` de FFmpeg para generar un MP3 a la
            velocidad deseada (con preservación de tono).
          - La posición siempre se mide en segundos del audio ORIGINAL.
          - Al cambiar velocidad se extrae en hilo secundario y se reanuda
            en la posición correcta del nuevo archivo.
        """

        def __init__(self):
            self.on_complete: Callable | None = None
            self._src_path: str = ""
            self._duration: float = 0.0
            self._speed: float = 1.0
            self._orig_pos: float = 0.0        # posición en tiempo original
            self._play_start_real: float = 0.0  # reloj al llamar play()
            self._play_start_orig: float = 0.0  # orig_pos al llamar play()
            self._playing: bool = False
            self._monitor: threading.Thread | None = None
            self._stop_monitor = threading.Event()
            self._speed_lock = threading.Lock()

            try:
                _pygame.mixer.pre_init(44100, -16, 2, 2048)
                _pygame.mixer.init()
            except Exception as exc:
                print(f"[AudioService] pygame.mixer init: {exc}")

        # ── Carga ────────────────────────────────────────────────────────────

        def load(self, path: str) -> bool:
            self.release()
            self._src_path = path
            self._speed = 1.0
            self._orig_pos = 0.0
            self._duration = _probe_duration(path)
            # Pre-extraer a 1x en segundo plano para que play() sea inmediato
            audio = _extract_audio(path, 1.0)
            if audio is None:
                return False
            try:
                _pygame.mixer.music.load(audio)
                return True
            except Exception as exc:
                print(f"[AudioService] load error: {exc}")
                return False

        # ── Reproducción ─────────────────────────────────────────────────────

        def play(self, position: float = 0.0) -> None:
            """Reproduce desde `position` segundos en tiempo original."""
            # Calcular posición en el archivo sped-up: pos_speedup = orig_pos / speed
            seek = position / self._speed if self._speed else 0.0
            try:
                _pygame.mixer.music.play(start=seek)
                self._play_start_real = _time.time()
                self._play_start_orig = position
                self._orig_pos = position
                self._playing = True
                self._start_monitor()
            except Exception as exc:
                print(f"[AudioService] play error: {exc}")

        def pause(self) -> None:
            if self._playing:
                self._orig_pos = self.get_position()
                _pygame.mixer.music.stop()
                self._playing = False
                self._stop_monitor.set()

        def seek(self, position: float) -> None:
            was_playing = self._playing
            if was_playing:
                self._stop_monitor.set()
            seek = position / self._speed if self._speed else 0.0
            _pygame.mixer.music.play(start=seek)
            self._play_start_real = _time.time()
            self._play_start_orig = position
            self._orig_pos = position
            self._playing = True
            if was_playing:
                self._start_monitor()
            else:
                _pygame.mixer.music.stop()
                self._playing = False

        def set_speed(self, rate: float, on_ready: Callable | None = None) -> None:
            """
            Cambia la velocidad en tiempo real SIN silencio:
            1. Sigue reproduciendo el audio actual mientras FFmpeg procesa.
            2. Cuando el nuevo audio está listo, cambia y reanuda.
            3. Llama on_ready() cuando el cambio se completó.
            """
            if rate == self._speed:
                if on_ready:
                    on_ready()
                return

            orig_pos = self.get_position()
            was_playing = self._playing
            self._speed = rate

            def _apply():
                audio = _extract_audio(self._src_path, rate)
                if audio is None:
                    print(f"[AudioService] No se pudo extraer audio a {rate}x")
                    return
                # Ahora sí paramos el audio actual y cargamos el nuevo
                with self._speed_lock:
                    try:
                        self._stop_monitor.set()
                        current_pos = self.get_position()   # posición actualizada
                        _pygame.mixer.music.stop()
                        self._playing = False
                        _pygame.mixer.music.load(audio)
                        if was_playing:
                            seek = current_pos / rate if rate else 0.0
                            _pygame.mixer.music.play(start=seek)
                            self._play_start_real = _time.time()
                            self._play_start_orig = current_pos
                            self._orig_pos = current_pos
                            self._playing = True
                            self._start_monitor()
                        else:
                            self._orig_pos = current_pos
                    except Exception as exc:
                        print(f"[AudioService] set_speed apply error: {exc}")
                if on_ready:
                    on_ready()

            threading.Thread(target=_apply, daemon=True).start()

        # ── Estado ───────────────────────────────────────────────────────────

        def get_position(self) -> float:
            """Retorna posición en segundos del audio ORIGINAL."""
            if self._playing and _pygame.mixer.music.get_busy():
                elapsed = _time.time() - self._play_start_real
                return self._play_start_orig + elapsed * self._speed
            return self._orig_pos

        def get_duration(self) -> float:
            return self._duration

        def is_playing(self) -> bool:
            return self._playing and _pygame.mixer.music.get_busy()

        # ── Monitor de fin de pista ───────────────────────────────────────────

        def _start_monitor(self) -> None:
            self._stop_monitor.clear()
            self._monitor = threading.Thread(
                target=self._monitor_loop, daemon=True
            )
            self._monitor.start()

        def _monitor_loop(self) -> None:
            while not self._stop_monitor.is_set():
                _time.sleep(0.5)
                if self._playing and not _pygame.mixer.music.get_busy():
                    self._playing = False
                    self._orig_pos = self._duration
                    if self.on_complete:
                        self.on_complete()
                    break

        # ── Limpieza ─────────────────────────────────────────────────────────

        def release(self) -> None:
            self._stop_monitor.set()
            self._playing = False
            self._orig_pos = 0.0
            try:
                _pygame.mixer.music.stop()
                _pygame.mixer.music.unload()
            except Exception:
                pass



# ─── Backend Android ─────────────────────────────────────────────────────────
if _ON_ANDROID:

    class _AndroidCompletionListener(PythonJavaClass):
        __javainterfaces__ = ["android/media/MediaPlayer$OnCompletionListener"]

        def __init__(self, callback: Callable):
            super().__init__()
            self._cb = callback

        @java_method("(Landroid/media/MediaPlayer;)V")
        def onCompletion(self, mp):
            if self._cb:
                self._cb()

    class _AndroidPlayer:
        def __init__(self):
            self._mp = None
            self._wake_lock = None
            self._path: str = ""
            self.on_complete: Callable | None = None
            self._acquire_wake_lock()

        # ── WakeLock ────────────────────────────────────────────────────────
        def _acquire_wake_lock(self):
            try:
                power_mgr = cast(
                    PowerManager,
                    mActivity.getSystemService(Context.POWER_SERVICE),
                )
                self._wake_lock = power_mgr.newWakeLock(
                    PowerManager.PARTIAL_WAKE_LOCK,
                    "AudioReaderPro::AudioWakeLock",
                )
                self._wake_lock.setReferenceCounted(False)
            except Exception as exc:
                print(f"[AudioService] WakeLock error: {exc}")

        def _hold_wake(self, hold: bool):
            if self._wake_lock is None:
                return
            if hold and not self._wake_lock.isHeld():
                self._wake_lock.acquire()
            elif not hold and self._wake_lock.isHeld():
                self._wake_lock.release()

        # ── MediaPlayer ──────────────────────────────────────────────────────
        def load(self, path: str) -> bool:
            try:
                self._release_mp()
                self._mp = MediaPlayer()
                self._mp.setDataSource(path)
                self._mp.setAudioStreamType(AudioManager.STREAM_MUSIC)
                self._mp.prepare()
                self._mp.setOnCompletionListener(
                    _AndroidCompletionListener(self._handle_complete)
                )
                self._path = path
                return True
            except Exception as exc:
                print(f"[AudioService] load error: {exc}")
                return False

        def play(self, position: float = 0.0) -> None:
            if self._mp:
                self._mp.seekTo(int(position * 1000))
                self._mp.start()
                self._hold_wake(True)

        def pause(self) -> None:
            if self._mp and self._mp.isPlaying():
                self._mp.pause()
                self._hold_wake(False)

        def seek(self, position: float) -> None:
            if self._mp:
                self._mp.seekTo(int(position * 1000))

        def get_position(self) -> float:
            if self._mp:
                return self._mp.getCurrentPosition() / 1000.0
            return 0.0

        def get_duration(self) -> float:
            if self._mp:
                return self._mp.getDuration() / 1000.0
            return 0.0

        def set_speed(self, rate: float, on_ready=None) -> None:
            """Requiere API 23+ (Android 6+)."""
            if self._mp:
                try:
                    params = autoclass("android.media.PlaybackParams")()
                    params.setSpeed(float(rate))
                    self._mp.setPlaybackParams(params)
                except Exception as exc:
                    print(f"[AudioService] set_speed error: {exc}")
            if on_ready:
                on_ready()

        def is_playing(self) -> bool:
            return self._mp is not None and self._mp.isPlaying()

        def release(self) -> None:
            self._release_mp()
            self._hold_wake(False)

        def _release_mp(self):
            if self._mp:
                try:
                    self._mp.stop()
                    self._mp.release()
                except Exception:
                    pass
                self._mp = None

        def _handle_complete(self):
            self._hold_wake(False)
            if self.on_complete:
                self.on_complete()


# ─── Clase pública unificada ─────────────────────────────────────────────────

class AudioService:
    """
    Interfaz unificada de reproducción.
    Usa _AndroidPlayer en Android y _DesktopPlayer en escritorio.
    Guarda progreso automáticamente cada `autosave_interval` segundos.
    """

    def __init__(self, autosave_interval: float = 5.0):
        self._player = _AndroidPlayer() if _ON_ANDROID else _DesktopPlayer()
        self._file_id: int | None = None
        self._autosave_interval = autosave_interval
        self._save_timer: threading.Timer | None = None

        # Callback externo que puede asignar main.py
        self.on_track_complete: Callable | None = None
        self._player.on_complete = self._on_complete

    # ── Ciclo de vida ─────────────────────────────────────────────────────────

    def open(self, path: str, file_id: int, resume_position: float = 0.0) -> bool:
        """Carga un archivo y salta a la posición guardada."""
        self.stop()
        ok = self._player.load(path)
        if ok:
            self._file_id = file_id
            self._player.play(resume_position)
            self._schedule_autosave()
        return ok

    def play_pause(self) -> bool:
        """Alterna play/pause. Retorna True si queda en play."""
        if self._player.is_playing():
            self._player.pause()
            self._cancel_autosave()
            self._save_now()
            return False
        else:
            self._player.play(self._player.get_position())
            self._schedule_autosave()
            return True

    def seek(self, position: float) -> None:
        self._player.seek(position)

    def set_speed(self, rate: float, on_ready: Callable | None = None) -> None:
        self._player.set_speed(rate, on_ready=on_ready)

    def stop(self) -> None:
        self._cancel_autosave()
        if self._file_id is not None:
            self._save_now()
        self._player.release()
        self._file_id = None

    def get_position(self) -> float:
        return self._player.get_position()

    def get_duration(self) -> float:
        return self._player.get_duration()

    def is_playing(self) -> bool:
        return self._player.is_playing()

    def progress_ratio(self) -> float:
        """Retorna un valor entre 0 y 1 para la barra de progreso."""
        dur = self.get_duration()
        return (self.get_position() / dur) if dur > 0 else 0.0

    # ── Auto-guardado ─────────────────────────────────────────────────────────

    def _schedule_autosave(self):
        self._cancel_autosave()
        self._save_timer = threading.Timer(
            self._autosave_interval, self._autosave_tick
        )
        self._save_timer.daemon = True
        self._save_timer.start()

    def _autosave_tick(self):
        self._save_now()
        if self._player.is_playing():
            self._schedule_autosave()  # re-agenda solo si sigue reproduciendo

    def _cancel_autosave(self):
        if self._save_timer:
            self._save_timer.cancel()
            self._save_timer = None

    def _save_now(self):
        if self._file_id is not None:
            from database import save_progress
            save_progress(self._file_id, self._player.get_position())

    # ── Eventos ───────────────────────────────────────────────────────────────

    def _on_complete(self):
        self._cancel_autosave()
        self._save_now()
        if self.on_track_complete:
            self.on_track_complete()
