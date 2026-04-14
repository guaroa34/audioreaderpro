"""
AudioReader Pro — Interfaz principal en Flet
Pantallas:
  • LibraryScreen  — lista de audiolibros con barra de progreso
  • PlayerScreen   — reproductor con controles completos
  • ImportScreen   — importar desde YouTube o archivo local
"""
import os
import threading

import flet as ft

import database as db
from downloader import YouTubeDownloader, fetch_metadata

# ── Colores ───────────────────────────────────────────────────────────────────
BG   = "#1a1a2e"
CARD = "#16213e"
BLUE  = ft.Colors.BLUE_700
AMBER = ft.Colors.AMBER_400


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s   = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def main(page: ft.Page):
    page.title      = "AudioReader Pro"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor    = BG
    page.padding    = 0

    # ── Estado ────────────────────────────────────────────────────────────────
    state = {
        "current_file":      None,
        "selected_category": None,
        "import_category":   "Sin categoría",
        "is_playing":        False,
        "position_ms":       0,
        "duration_ms":       0,
        "sleep_timer":       None,
    }

    # ── Audio y FilePicker ────────────────────────────────────────────────────
    audio = ft.Audio(src="", autoplay=False, volume=1.0, playback_rate=1.0)

    def on_file_picked(e: ft.FilePickerResultEvent):
        if e.files:
            path = e.files[0].path
            name = os.path.splitext(os.path.basename(path))[0]
            db.add_file(title=name, path=path, source="local",
                        category=state["import_category"])
            refresh_library()
            snack(f'"{name}" importado.')

    file_picker = ft.FilePicker(on_result=on_file_picked)
    page.overlay.extend([audio, file_picker])

    # ── Snackbar ──────────────────────────────────────────────────────────────
    def snack(text: str):
        page.open(ft.SnackBar(content=ft.Text(text)))

    # ══════════════════════════════════════════════════════════════════════════
    # BIBLIOTECA
    # ══════════════════════════════════════════════════════════════════════════
    book_list     = ft.ListView(expand=True, spacing=4,
                                padding=ft.Padding.symmetric(horizontal=8, vertical=4))
    cat_chips_row = ft.Row(scroll=ft.ScrollMode.AUTO, spacing=6)

    def build_category_chips():
        cat_chips_row.controls.clear()
        for cat in ["Todos"] + db.get_categories():
            is_active = (cat == "Todos" and state["selected_category"] is None) \
                        or (cat == state["selected_category"])
            cat_chips_row.controls.append(ft.ElevatedButton(
                content=ft.Text(cat, size=12),
                bgcolor=AMBER if is_active else BLUE,
                color=ft.Colors.BLACK if is_active else ft.Colors.WHITE,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=20),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=0),
                ),
                on_click=lambda e, c=cat: filter_by_category(c),
            ))
        cat_chips_row.controls.append(ft.IconButton(
            icon=ft.Icons.ADD_CIRCLE_OUTLINE,
            icon_color=AMBER,
            icon_size=22,
            on_click=lambda e: show_add_category_dialog(),
        ))
        page.update()

    def filter_by_category(cat: str):
        state["selected_category"] = None if cat == "Todos" else cat
        build_category_chips()
        refresh_library()

    def show_add_category_dialog():
        field = ft.TextField(
            hint_text="Nombre de la categoría",
            border=ft.InputBorder.OUTLINE,
            border_width=2,
            border_radius=10,
            focused_border_color=AMBER,
        )
        def save(e):
            name = (field.value or "").strip()
            if name:
                db.add_category(name)
                build_category_chips()
                build_import_chips()
            page.close(dlg)
        dlg = ft.AlertDialog(
            title=ft.Text("Nueva Categoría"),
            content=field,
            actions=[
                ft.TextButton("CANCELAR", on_click=lambda e: page.close(dlg)),
                ft.ElevatedButton(content=ft.Text("CREAR"), on_click=save),
            ],
        )
        page.open(dlg)

    def refresh_library():
        book_list.controls.clear()
        for entry in db.get_all_files(state["selected_category"]):
            book_list.controls.append(build_book_item(entry))
        page.update()

    def build_book_item(entry: dict) -> ft.Control:
        dur = fmt_time(entry["duration"])
        pos = fmt_time(entry["last_position"])
        pct = (entry["last_position"] / entry["duration"] * 100) if entry["duration"] > 0 else 0
        cat = entry.get("category", "")
        sub = f"{cat}  •  {pos} / {dur}  ({pct:.0f}%)" if cat else f"{pos} / {dur}  ({pct:.0f}%)"
        return ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.MUSIC_NOTE, color=ft.Colors.BLUE_400, size=32),
                ft.Column([
                    ft.Text(entry["title"], weight=ft.FontWeight.BOLD,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(sub, size=11, color=ft.Colors.WHITE54),
                ], expand=True, spacing=2, tight=True),
                ft.IconButton(
                    icon=ft.Icons.LABEL_OUTLINE, icon_color=AMBER, icon_size=18,
                    tooltip="Cambiar categoría",
                    on_click=lambda e, en=entry: show_edit_category_dialog(en),
                ),
                ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400, icon_size=18,
                    tooltip="Eliminar",
                    on_click=lambda e, en=entry: confirm_delete(en),
                ),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=CARD,
            border_radius=10,
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            margin=ft.Margin(left=0, right=0, top=2, bottom=2),
            on_click=lambda e, en=entry: open_entry(en),
        )

    def show_edit_category_dialog(entry: dict):
        categories = db.get_categories()
        current_cat = entry.get("category", "Sin categoría")
        sel  = [current_cat]
        btns: list[ft.ElevatedButton] = []

        def select_cat(cat):
            sel[0] = cat
            for b in btns:
                b.bgcolor = AMBER if b.data == cat else BLUE
                b.color   = ft.Colors.BLACK if b.data == cat else ft.Colors.WHITE
            page.update()

        for cat in categories:
            b = ft.ElevatedButton(
                content=ft.Text(cat), data=cat,
                bgcolor=AMBER if cat == current_cat else BLUE,
                color=ft.Colors.BLACK if cat == current_cat else ft.Colors.WHITE,
                on_click=lambda e, c=cat: select_cat(c),
                width=220,
            )
            btns.append(b)

        def save(e):
            db.update_file_category(entry["id"], sel[0])
            page.close(dlg)
            refresh_library()
            snack(f'Categoría cambiada a "{sel[0]}"')

        dlg = ft.AlertDialog(
            title=ft.Text(f'Categoría: {entry["title"][:28]}'),
            content=ft.Column(btns, tight=True, scroll=ft.ScrollMode.AUTO, height=200),
            actions=[
                ft.TextButton("CANCELAR", on_click=lambda e: page.close(dlg)),
                ft.ElevatedButton(content=ft.Text("GUARDAR"), on_click=save),
            ],
        )
        page.open(dlg)

    def confirm_delete(entry: dict):
        def do_delete(e):
            db.delete_file(entry["id"])
            refresh_library()
            page.close(dlg)
        dlg = ft.AlertDialog(
            title=ft.Text("Eliminar"),
            content=ft.Text(f'¿Eliminar "{entry["title"]}" de la biblioteca?'),
            actions=[
                ft.TextButton("CANCELAR", on_click=lambda e: page.close(dlg)),
                ft.ElevatedButton(
                    content=ft.Text("ELIMINAR"),
                    bgcolor=ft.Colors.RED_700,
                    on_click=do_delete,
                ),
            ],
        )
        page.open(dlg)

    library_screen = ft.Column([
        ft.AppBar(
            title=ft.Text("Mi Biblioteca"),
            bgcolor=ft.Colors.BLUE_800,
            actions=[ft.IconButton(
                icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                icon_color=ft.Colors.WHITE,
                on_click=lambda e: go_to_import(),
            )],
        ),
        ft.Container(
            content=cat_chips_row,
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
        ),
        ft.Divider(height=1, color=ft.Colors.WHITE24),
        book_list,
    ], expand=True, spacing=0)

    # ══════════════════════════════════════════════════════════════════════════
    # REPRODUCTOR
    # ══════════════════════════════════════════════════════════════════════════
    lbl_title       = ft.Text("Sin título", size=18, weight=ft.FontWeight.BOLD,
                               text_align=ft.TextAlign.CENTER, max_lines=2)
    lbl_position    = ft.Text("0:00", size=12, color=ft.Colors.WHITE54)
    lbl_duration    = ft.Text("0:00", size=12, color=ft.Colors.WHITE54)
    progress_slider = ft.Slider(min=0, max=1, value=0,
                                active_color=ft.Colors.BLUE_400, thumb_color=AMBER,
                                expand=True)
    btn_play        = ft.IconButton(icon=ft.Icons.PLAY_CIRCLE_OUTLINE,
                                    icon_size=72, icon_color=AMBER)
    lbl_speed       = ft.Text("", size=11, color=AMBER,
                               text_align=ft.TextAlign.CENTER)
    player_title    = ft.Text("Reproduciendo...")
    speed_btns: dict[float, ft.ElevatedButton] = {}

    def make_speed_btn(label: str, rate: float) -> ft.ElevatedButton:
        b = ft.ElevatedButton(
            content=ft.Text(label, size=12),
            bgcolor=AMBER if rate == 1.0 else BLUE,
            color=ft.Colors.BLACK if rate == 1.0 else ft.Colors.WHITE,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=6),
                padding=ft.Padding.symmetric(horizontal=8, vertical=0),
            ),
            on_click=lambda e, r=rate: set_speed(r),
        )
        speed_btns[rate] = b
        return b

    speed_row = ft.Row(
        [make_speed_btn("0.75x", 0.75), make_speed_btn("1x", 1.0),
         make_speed_btn("1.25x", 1.25), make_speed_btn("1.5x", 1.5),
         make_speed_btn("2x", 2.0)],
        scroll=ft.ScrollMode.AUTO,
    )

    def set_speed(rate: float):
        audio.playback_rate = rate
        for r, b in speed_btns.items():
            b.bgcolor = AMBER if r == rate else BLUE
            b.color   = ft.Colors.BLACK if r == rate else ft.Colors.WHITE
        lbl_speed.value = f"Velocidad {rate}x"
        audio.update()
        page.update()

    def toggle_play(e=None):
        if not audio.src:
            return
        if state["is_playing"]:
            audio.pause()
        else:
            audio.resume()

    def skip(seconds: float):
        new_ms = max(0, state["position_ms"] + int(seconds * 1000))
        audio.seek(new_ms)

    def on_seek(e):
        if state["duration_ms"] > 0:
            audio.seek(int(e.control.value * state["duration_ms"]))

    progress_slider.on_change_end = on_seek
    btn_play.on_click = toggle_play

    # ── Eventos de audio ─────────────────────────────────────────────────────
    def on_position_changed(e):
        ms  = int(e.data or 0)
        dur = state["duration_ms"] or 1
        state["position_ms"]    = ms
        lbl_position.value      = fmt_time(ms / 1000)
        progress_slider.value   = ms / dur
        if state["current_file"]:
            db.save_progress(state["current_file"]["id"], ms / 1000)
        page.update()

    def on_duration_changed(e):
        ms = int(e.data or 0)
        if ms > 0:
            state["duration_ms"] = ms
            lbl_duration.value   = fmt_time(ms / 1000)
            if state["current_file"] and state["current_file"]["duration"] == 0:
                db.update_duration(state["current_file"]["id"], ms / 1000)
            page.update()

    def on_state_changed(e):
        s = e.data
        if s == "playing":
            state["is_playing"] = True
            btn_play.icon = ft.Icons.PAUSE_CIRCLE_OUTLINE
        elif s in ("paused", "stopped"):
            state["is_playing"] = False
            btn_play.icon = ft.Icons.PLAY_CIRCLE_OUTLINE
        elif s == "completed":
            state["is_playing"]   = False
            btn_play.icon         = ft.Icons.PLAY_CIRCLE_OUTLINE
            progress_slider.value = 0
            lbl_position.value    = "0:00"
            if state["current_file"]:
                db.save_progress(state["current_file"]["id"], 0)
            refresh_library()
        page.update()

    audio.on_position_changed = on_position_changed
    audio.on_duration_changed = on_duration_changed
    audio.on_state_changed    = on_state_changed

    def open_entry(entry: dict):
        state["current_file"] = entry
        state["position_ms"]  = int(entry["last_position"] * 1000)
        state["duration_ms"]  = int(entry["duration"] * 1000)
        lbl_title.value       = entry["title"]
        lbl_duration.value    = fmt_time(entry["duration"])
        lbl_position.value    = fmt_time(entry["last_position"])
        progress_slider.value = (entry["last_position"] / entry["duration"]) \
                                if entry["duration"] > 0 else 0
        player_title.value = entry["title"]

        audio.src = entry["path"]
        audio.update()
        audio.play()

        if entry["last_position"] > 0.5:
            def _seek_later():
                import time
                time.sleep(1.2)
                audio.seek(int(entry["last_position"] * 1000))
            threading.Thread(target=_seek_later, daemon=True).start()

        go_to_player()

    def show_sleep_timer(e=None):
        def set_timer(minutes):
            if state["sleep_timer"]:
                state["sleep_timer"].cancel()
            def stop():
                if state["is_playing"]:
                    audio.pause()
                page.update()
            t = threading.Timer(minutes * 60, stop)
            t.daemon = True
            t.start()
            state["sleep_timer"] = t
            page.close(dlg)
            snack(f"Sleep timer: {minutes} min")

        def cancel(e=None):
            if state["sleep_timer"]:
                state["sleep_timer"].cancel()
                state["sleep_timer"] = None
            page.close(dlg)
            snack("Sleep timer cancelado")

        dlg = ft.AlertDialog(
            title=ft.Text("Sleep Timer"),
            content=ft.Text("Detener reproducción en:"),
            actions=[
                ft.TextButton("15 min", on_click=lambda e: set_timer(15)),
                ft.TextButton("30 min", on_click=lambda e: set_timer(30)),
                ft.TextButton("60 min", on_click=lambda e: set_timer(60)),
                ft.TextButton("Cancelar", on_click=cancel),
            ],
        )
        page.open(dlg)

    def show_note_dialog(e=None):
        if not state["current_file"]:
            return
        pos_s = state["position_ms"] / 1000
        field = ft.TextField(
            hint_text="Escribe tu nota aquí...",
            multiline=True,
            border=ft.InputBorder.OUTLINE,
            border_width=2,
            border_radius=10,
            focused_border_color=AMBER,
            min_lines=3,
            max_lines=6,
        )
        def save_note(e):
            content = (field.value or "").strip()
            if content:
                db.add_note(file_id=state["current_file"]["id"],
                            position=pos_s, content=content)
                snack("Nota guardada")
            page.close(dlg)
        dlg = ft.AlertDialog(
            title=ft.Text(f"Nota en {fmt_time(pos_s)}"),
            content=field,
            actions=[
                ft.TextButton("CANCELAR", on_click=lambda e: page.close(dlg)),
                ft.ElevatedButton(content=ft.Text("GUARDAR"), on_click=save_note),
            ],
        )
        page.open(dlg)

    player_screen = ft.Column([
        ft.AppBar(
            title=player_title,
            bgcolor=ft.Colors.BLUE_800,
            leading=ft.IconButton(
                icon=ft.Icons.ARROW_BACK,
                icon_color=ft.Colors.WHITE,
                on_click=lambda e: go_to_library(),
            ),
        ),
        ft.Column([
            ft.Container(height=4),
            ft.Icon(ft.Icons.ALBUM, size=80, color=ft.Colors.BLUE_400),
            ft.Container(
                content=lbl_title,
                padding=ft.Padding.symmetric(horizontal=16, vertical=4),
                alignment=ft.alignment.center,
            ),
            ft.Row(
                [lbl_position, ft.Container(expand=True), lbl_duration],
                padding=ft.Padding.symmetric(horizontal=16),
            ),
            ft.Container(
                content=ft.Row([progress_slider]),
                padding=ft.Padding.symmetric(horizontal=8),
            ),
            ft.Row([
                ft.IconButton(icon=ft.Icons.REPLAY_30, icon_size=48,
                              icon_color=ft.Colors.WHITE70,
                              on_click=lambda e: skip(-30)),
                btn_play,
                ft.IconButton(icon=ft.Icons.FORWARD_30, icon_size=48,
                              icon_color=ft.Colors.WHITE70,
                              on_click=lambda e: skip(30)),
            ], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(speed_row, padding=ft.Padding.symmetric(horizontal=8)),
            ft.Container(lbl_speed, alignment=ft.alignment.center),
            ft.Row([
                ft.ElevatedButton(
                    content=ft.Text("Sleep Timer"),
                    bgcolor=BLUE, on_click=show_sleep_timer, expand=True,
                ),
                ft.ElevatedButton(
                    content=ft.Text("Nueva Nota"),
                    bgcolor=BLUE, on_click=show_note_dialog, expand=True,
                ),
            ], padding=ft.Padding.symmetric(horizontal=8)),
        ], scroll=ft.ScrollMode.AUTO, expand=True, spacing=8),
    ], expand=True, spacing=0)

    # ══════════════════════════════════════════════════════════════════════════
    # IMPORTAR
    # ══════════════════════════════════════════════════════════════════════════
    yt_url_field   = ft.TextField(
        hint_text="Pega aquí la URL de YouTube",
        border=ft.InputBorder.OUTLINE,
        border_width=2, border_radius=10,
        focused_border_color=AMBER,
        suffix_icon=ft.Icons.PLAY_CIRCLE_OUTLINE,
    )
    dl_progress    = ft.ProgressBar(value=0, bgcolor=ft.Colors.WHITE12,
                                    color=ft.Colors.BLUE_400)
    dl_status      = ft.Text("", size=12, color=ft.Colors.WHITE54,
                              text_align=ft.TextAlign.CENTER)
    import_cat_row = ft.Row(scroll=ft.ScrollMode.AUTO, spacing=6)
    downloader_ref = [None]

    def build_import_chips():
        import_cat_row.controls.clear()
        for cat in db.get_categories():
            is_active = cat == state["import_category"]
            import_cat_row.controls.append(ft.ElevatedButton(
                content=ft.Text(cat, size=12),
                bgcolor=AMBER if is_active else BLUE,
                color=ft.Colors.BLACK if is_active else ft.Colors.WHITE,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=20),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=0),
                ),
                on_click=lambda e, c=cat: select_import_cat(c),
            ))
        page.update()

    def select_import_cat(cat: str):
        state["import_category"] = cat
        build_import_chips()

    def start_download(mode: str):
        url = (yt_url_field.value or "").strip()
        if not url:
            snack("Ingresa una URL de YouTube.")
            return
        dl_status.value   = "Obteniendo metadatos..."
        dl_progress.value = 0
        page.update()

        def _fetch():
            meta      = fetch_metadata(url)
            title     = meta["title"]     if meta else "Descarga YouTube"
            thumbnail = meta["thumbnail"] if meta else None

            def on_progress(prog):
                dl_progress.value = prog.percent / 100
                dl_status.value = (
                    f"{prog.percent:.0f}% · {prog.speed} · ETA {prog.eta}"
                    if prog.status == "downloading" else "Procesando con FFmpeg..."
                )
                page.update()

            def on_done(filepath):
                dl_progress.value = 1
                dl_status.value   = "¡Descarga completada!"
                db.add_file(title=title, path=filepath, source="youtube",
                            thumbnail=thumbnail, category=state["import_category"])
                refresh_library()
                snack(f'"{title}" añadido a la biblioteca')
                page.update()

            def on_error(msg):
                dl_status.value = f"Error: {msg}"
                page.update()

            downloader_ref[0] = YouTubeDownloader(
                on_progress=on_progress, on_done=on_done, on_error=on_error,
            )
            if mode == "audio":
                downloader_ref[0].download_audio(url)
            else:
                downloader_ref[0].download_video(url)

        threading.Thread(target=_fetch, daemon=True).start()

    import_screen = ft.Column([
        ft.AppBar(
            title=ft.Text("Importar Contenido"),
            bgcolor=ft.Colors.BLUE_800,
            leading=ft.IconButton(
                icon=ft.Icons.ARROW_BACK,
                icon_color=ft.Colors.WHITE,
                on_click=lambda e: go_to_library(),
            ),
        ),
        ft.Column([
            ft.Text("YouTube", size=18, weight=ft.FontWeight.BOLD),
            yt_url_field,
            ft.Row([
                ft.ElevatedButton(
                    content=ft.Text("Solo Audio"), bgcolor=BLUE, expand=True,
                    on_click=lambda e: start_download("audio"),
                ),
                ft.ElevatedButton(
                    content=ft.Text("Con Video"), bgcolor=BLUE, expand=True,
                    on_click=lambda e: start_download("video"),
                ),
            ]),
            dl_progress,
            dl_status,
            ft.Divider(color=ft.Colors.WHITE24),
            ft.Text("Categoría del audio", size=14, weight=ft.FontWeight.BOLD),
            import_cat_row,
            ft.Divider(color=ft.Colors.WHITE24),
            ft.Text("Archivo Local", size=18, weight=ft.FontWeight.BOLD),
            ft.ElevatedButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.FOLDER_OPEN),
                    ft.Text("Abrir selector de archivos"),
                ], tight=True),
                bgcolor=BLUE,
                on_click=lambda e: file_picker.pick_files(
                    allowed_extensions=["mp3", "mp4", "mkv", "m4a", "ogg", "wav"],
                ),
            ),
        ], scroll=ft.ScrollMode.AUTO, expand=True,
           padding=ft.Padding.only(left=16, right=16, top=12, bottom=12),
           spacing=12),
    ], expand=True, spacing=0)

    # ══════════════════════════════════════════════════════════════════════════
    # NAVEGACIÓN
    # ══════════════════════════════════════════════════════════════════════════
    body = ft.Container(content=library_screen, expand=True, bgcolor=BG)

    def go_to_library():
        body.content = library_screen
        page.update()

    def go_to_player():
        body.content = player_screen
        page.update()

    def go_to_import():
        build_import_chips()
        body.content = import_screen
        page.update()

    page.add(body)
    refresh_library()
    build_category_chips()


# ─── Punto de entrada ────────────────────────────────────────────────────────
ft.run(main)
os._exit(0)  # evita ejecutar código legado debajo
def _kivy_placeholder():
    """Solicita permisos peligrosos necesarios en Android 6+."""
    if platform != "android":
        return
    try:
        from android.permissions import (         # type: ignore
            request_permissions, Permission
        )
        request_permissions([
            Permission.READ_EXTERNAL_STORAGE,
            Permission.WRITE_EXTERNAL_STORAGE,
            Permission.INTERNET,
            Permission.WAKE_LOCK,
        ])
    except Exception as exc:
        print(f"[Permisos] {exc}")


# ─── KV Layout ───────────────────────────────────────────────────────────────
KV = """
#:import get_color_from_hex kivy.utils.get_color_from_hex
#:import dp kivy.metrics.dp

<RootManager>:
    LibraryScreen:
        name: "library"
    PlayerScreen:
        name: "player"
    ImportScreen:
        name: "import"

# ═══════════════════════════ BIBLIOTECA ═════════════════════════════════════
<LibraryScreen>:
    name: "library"
    BoxLayout:
        orientation: "vertical"

        MDTopAppBar:
            title: "Mi Biblioteca"
            right_action_items: [["plus-circle-outline", lambda x: app.go_to_import()]]
            md_bg_color: get_color_from_hex("#1565C0")

        # ── Chips de filtro (scroll horizontal) ──
        ScrollView:
            size_hint_y: None
            height: dp(50)
            do_scroll_y: False
            bar_width: 0
            BoxLayout:
                id: cat_chips
                orientation: "horizontal"
                size_hint_x: None
                width: self.minimum_width
                padding: [dp(8), dp(7)]
                spacing: dp(6)

        MDSeparator:

        # ── Lista (scroll vertical automático) ──
        ScrollView:
            MDList:
                id: book_list

        MDFloatingActionButton:
            icon: "refresh"
            md_bg_color: get_color_from_hex("#1565C0")
            pos_hint: {"right": 0.97, "y": 0.02}
            on_release: app.refresh_library()

# ═══════════════════════════ REPRODUCTOR ════════════════════════════════════
<PlayerScreen>:
    name: "player"
    BoxLayout:
        orientation: "vertical"

        MDTopAppBar:
            id: player_toolbar
            title: "Reproduciendo..."
            left_action_items: [["arrow-left", lambda x: app.back_to_library()]]
            md_bg_color: get_color_from_hex("#1565C0")

        # ScrollView para que todo quepa en pantallas pequeñas
        ScrollView:
            do_scroll_x: False
            BoxLayout:
                orientation: "vertical"
                padding: [dp(12), dp(10)]
                spacing: dp(8)
                size_hint_y: None
                height: self.minimum_height

                # ── Portada ──
                MDIcon:
                    id: lbl_cover
                    icon: "book-music-outline"
                    halign: "center"
                    font_size: "64sp"
                    size_hint_y: None
                    height: dp(72)
                    theme_text_color: "Custom"
                    text_color: get_color_from_hex("#1565C0")

                # ── Título ──
                MDLabel:
                    id: lbl_title
                    text: "Sin título"
                    halign: "center"
                    font_style: "H6"
                    size_hint_y: None
                    height: dp(36)

                # ── Posición / Duración ──
                BoxLayout:
                    size_hint_y: None
                    height: dp(22)
                    MDLabel:
                        id: lbl_position
                        text: "0:00"
                        halign: "left"
                        font_style: "Caption"
                    MDLabel:
                        id: lbl_duration
                        text: "0:00"
                        halign: "right"
                        font_style: "Caption"

                # ── Slider ──
                MDSlider:
                    id: progress_slider
                    min: 0
                    max: 1
                    value: 0
                    hint: False
                    size_hint_y: None
                    height: dp(36)
                    on_touch_up: app.on_seek(self, args)

                # ── Controles principales ──
                BoxLayout:
                    size_hint_y: None
                    height: dp(88)
                    spacing: dp(4)
                    padding: [dp(8), 0]
                    MDIconButton:
                        icon: "rewind-30"
                        user_font_size: "48sp"
                        size_hint_x: 0.28
                        on_release: app.skip(-30)
                    MDIconButton:
                        id: btn_play
                        icon: "play-circle-outline"
                        user_font_size: "72sp"
                        size_hint_x: 0.44
                        on_release: app.toggle_play()
                    MDIconButton:
                        icon: "fast-forward-30"
                        user_font_size: "48sp"
                        size_hint_x: 0.28
                        on_release: app.skip(30)

                # ── Velocidad (scroll horizontal si pantalla estrecha) ──
                BoxLayout:
                    orientation: "vertical"
                    size_hint_y: None
                    height: dp(78)
                    spacing: dp(4)

                    ScrollView:
                        size_hint_y: None
                        height: dp(46)
                        do_scroll_y: False
                        bar_width: 0
                        BoxLayout:
                            size_hint_x: None
                            width: self.minimum_width
                            spacing: dp(4)
                            MDRaisedButton:
                                id: btn_speed_075
                                text: "0.75x"
                                size_hint_x: None
                                width: dp(72)
                                on_release: app.set_speed(0.75)
                            MDRaisedButton:
                                id: btn_speed_1
                                text: "1x"
                                size_hint_x: None
                                width: dp(56)
                                md_bg_color: get_color_from_hex("#FFC107")
                                theme_text_color: "Custom"
                                text_color: 0,0,0,1
                                on_release: app.set_speed(1.0)
                            MDRaisedButton:
                                id: btn_speed_125
                                text: "1.25x"
                                size_hint_x: None
                                width: dp(72)
                                on_release: app.set_speed(1.25)
                            MDRaisedButton:
                                id: btn_speed_150
                                text: "1.5x"
                                size_hint_x: None
                                width: dp(64)
                                on_release: app.set_speed(1.5)
                            MDRaisedButton:
                                id: btn_speed_200
                                text: "2x"
                                size_hint_x: None
                                width: dp(56)
                                on_release: app.set_speed(2.0)

                    MDLabel:
                        id: lbl_speed_status
                        text: ""
                        halign: "center"
                        font_style: "Caption"
                        size_hint_y: None
                        height: dp(20)
                        theme_text_color: "Custom"
                        text_color: 1, 0.757, 0.027, 1

                # ── Acciones extra ──
                BoxLayout:
                    size_hint_y: None
                    height: dp(48)
                    spacing: dp(8)
                    MDRaisedButton:
                        text: "Sleep Timer"
                        size_hint_x: 0.5
                        on_release: app.show_sleep_timer()
                    MDRaisedButton:
                        text: "Nueva Nota"
                        size_hint_x: 0.5
                        on_release: app.show_note_dialog()

# ═══════════════════════════ IMPORTAR ═══════════════════════════════════════
<ImportScreen>:
    name: "import"
    BoxLayout:
        orientation: "vertical"

        MDTopAppBar:
            title: "Importar Contenido"
            left_action_items: [["arrow-left", lambda x: app.back_to_library()]]
            md_bg_color: get_color_from_hex("#1565C0")

        # ScrollView para que todo encaje en pantallas pequeñas
        ScrollView:
            do_scroll_x: False
            BoxLayout:
                orientation: "vertical"
                padding: [dp(16), dp(12)]
                spacing: dp(12)
                size_hint_y: None
                height: self.minimum_height

                MDLabel:
                    text: "YouTube"
                    font_style: "H6"
                    size_hint_y: None
                    height: dp(32)

                MDTextField:
                    id: yt_url
                    hint_text: "Pega aquí la URL de YouTube"
                    icon_right: "youtube"
                    mode: "rectangle"
                    size_hint_y: None
                    height: dp(56)

                # Botones de descarga
                BoxLayout:
                    size_hint_y: None
                    height: dp(48)
                    spacing: dp(8)
                    MDRaisedButton:
                        text: "Solo Audio"
                        size_hint_x: 0.5
                        on_release: app.start_download("audio")
                    MDRaisedButton:
                        text: "Con Video"
                        size_hint_x: 0.5
                        on_release: app.start_download("video")

                MDProgressBar:
                    id: dl_progress
                    value: 0
                    size_hint_y: None
                    height: dp(8)

                MDLabel:
                    id: dl_status
                    text: ""
                    halign: "center"
                    font_style: "Caption"
                    size_hint_y: None
                    height: dp(24)

                MDSeparator:
                    size_hint_y: None
                    height: dp(1)

                # ── Categoría ──
                MDLabel:
                    text: "Categoría del audio"
                    font_style: "Subtitle1"
                    size_hint_y: None
                    height: dp(28)

                ScrollView:
                    size_hint_y: None
                    height: dp(48)
                    do_scroll_y: False
                    bar_width: 0
                    BoxLayout:
                        id: import_cat_chips
                        orientation: "horizontal"
                        size_hint_x: None
                        width: self.minimum_width
                        spacing: dp(6)

                MDSeparator:
                    size_hint_y: None
                    height: dp(1)

                # ── Archivo Local ──
                MDLabel:
                    text: "Archivo Local"
                    font_style: "H6"
                    size_hint_y: None
                    height: dp(32)

                MDRaisedButton:
                    text: "Abrir selector de archivos"
                    icon: "folder-open-outline"
                    size_hint_y: None
                    height: dp(48)
                    on_release: app.open_file_chooser()
"""


# ─── Pantallas ────────────────────────────────────────────────────────────────

class RootManager(ScreenManager):
    pass


class LibraryScreen(Screen):
    pass


class PlayerScreen(Screen):
    pass


class ImportScreen(Screen):
    pass


# ─── Aplicación principal ─────────────────────────────────────────────────────

class AudioReaderApp(MDApp):

    PROGRESS_INTERVAL = 1.0   # segundos entre actualizaciones del slider

    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Blue"

        # Servicios
        self.audio = AudioService(autosave_interval=5.0)
        self.audio.on_track_complete = self._on_track_complete

        self._current_file: dict | None = None   # registro activo de DB
        self._sleep_timer: threading.Timer | None = None
        self._downloader: YouTubeDownloader | None = None

        request_android_permissions()
        Builder.load_string(KV)
        return RootManager()

    def on_start(self):
        self._selected_category: str | None = None   # None = "Todos"
        self._import_category: str = "Sin categoría"
        self.refresh_library()
        self._build_category_chips()
        self._build_import_chips()

    def on_stop(self):
        self.audio.stop()

    # ── Navegación ────────────────────────────────────────────────────────────

    def go_to_import(self):
        self._build_import_chips()
        self.root.current = "import"

    def back_to_library(self):
        self.root.current = "library"

    # ── Biblioteca ────────────────────────────────────────────────────────────

    def _build_category_chips(self):
        """Construye los chips de filtro en LibraryScreen."""
        from kivy.metrics import dp
        from kivy.graphics import Color, RoundedRectangle
        chips_box = self.root.get_screen("library").ids.cat_chips
        chips_box.clear_widgets()
        categories = ["Todos"] + db.get_categories()
        for cat in categories:
            btn = MDRaisedButton(
                text=cat,
                size_hint=(None, None),
                height=dp(36),
            )
            active = (cat == "Todos" and self._selected_category is None) or \
                     (cat == self._selected_category)
            btn.md_bg_color = [1, 0.757, 0.027, 1] if active else [0.129, 0.588, 0.953, 1]
            btn.bind(on_release=partial(self._filter_by_category, cat))
            chips_box.add_widget(btn)
        # Botón para agregar nueva categoría
        add_btn = MDIconButton(
            icon="plus-circle-outline",
            size_hint=(None, None),
            size=(dp(36), dp(36)),
        )
        add_btn.bind(on_release=lambda x: self._show_add_category_dialog())
        chips_box.add_widget(add_btn)

    def _build_import_chips(self):
        """Construye los chips de selección de categoría en ImportScreen."""
        from kivy.metrics import dp
        chips_box = self.root.get_screen("import").ids.import_cat_chips
        chips_box.clear_widgets()
        chips_box.size_hint_x = None
        chips_box.width = 0
        categories = db.get_categories()
        for cat in categories:
            btn = MDRaisedButton(
                text=cat,
                size_hint=(None, None),
                height=dp(40),
            )
            active = (cat == self._import_category)
            btn.md_bg_color = [1, 0.757, 0.027, 1] if active else [0.129, 0.588, 0.953, 1]
            btn.theme_text_color = "Custom"
            btn.text_color = [0, 0, 0, 1] if active else [1, 1, 1, 1]
            btn.bind(on_release=partial(self._select_import_category, cat))
            chips_box.add_widget(btn)
        chips_box.bind(minimum_width=chips_box.setter("width"))

    def _filter_by_category(self, cat: str, *args):
        self._selected_category = None if cat == "Todos" else cat
        self._build_category_chips()
        self.refresh_library()

    def _select_import_category(self, cat: str, *args):
        self._import_category = cat
        self._build_import_chips()

    def _show_add_category_dialog(self):
        field = MDTextField(hint_text="Nombre de la categoría", mode="rectangle")

        def save(*args):
            name = field.text.strip()
            if name:
                db.add_category(name)
                dialog.dismiss()
                self._build_category_chips()
                self._build_import_chips()
            else:
                dialog.dismiss()

        dialog = MDDialog(
            title="Nueva Categoría",
            type="custom",
            content_cls=field,
            buttons=[
                MDFlatButton(text="CANCELAR", on_release=lambda x: dialog.dismiss()),
                MDRaisedButton(text="CREAR", on_release=save),
            ],
        )
        dialog.open()

    def refresh_library(self):
        book_list = self.root.get_screen("library").ids.book_list
        book_list.clear_widgets()
        for entry in db.get_all_files(self._selected_category):
            self._add_list_item(book_list, entry)

    def _add_list_item(self, book_list, entry: dict):
        from kivy.metrics import dp
        dur = self._fmt_time(entry["duration"])
        pos = self._fmt_time(entry["last_position"])
        pct = (entry["last_position"] / entry["duration"] * 100
               if entry["duration"] > 0 else 0)
        cat = entry.get("category", "")

        secondary = f"{cat}  •  {pos} / {dur}  ({pct:.0f}%)" if cat else f"{pos} / {dur}  ({pct:.0f}%)"

        item = TwoLineAvatarIconListItem(
            text=entry["title"],
            secondary_text=secondary,
            on_release=partial(self._open_entry, entry),
        )

        thumbnail = entry.get("thumbnail")
        if thumbnail and thumbnail.startswith("http"):
            img = AsyncImage(source=thumbnail, size_hint=(None, None),
                             size=(dp(48), dp(48)), allow_stretch=True)
            icon_left = IconLeftWidget(icon="book-music-outline")
            # Reemplazamos el widget interno del IconLeftWidget con la imagen
            icon_left.clear_widgets()
            icon_left.add_widget(img)
        else:
            icon_left = IconLeftWidget(icon="book-music-outline")

        icon_tag = IconRightWidget(
            icon="tag-edit-outline",
            on_release=partial(self._show_edit_category_dialog, entry),
        )
        icon_del = IconRightWidget(
            icon="delete-outline",
            on_release=partial(self._confirm_delete, entry),
        )
        item.add_widget(icon_left)
        item.add_widget(icon_tag)
        item.add_widget(icon_del)
        book_list.add_widget(item)

    def _open_entry(self, entry: dict, *args):
        self._current_file = entry
        screen = self.root.get_screen("player")
        screen.ids.player_toolbar.title = entry["title"]
        screen.ids.lbl_title.text       = entry["title"]
        screen.ids.lbl_duration.text    = self._fmt_time(entry["duration"])
        screen.ids.progress_slider.value = 0

        ok = self.audio.open(
            path=entry["path"],
            file_id=entry["id"],
            resume_position=entry["last_position"],
        )
        if not ok:
            _snack("No se pudo abrir el archivo.")
            return

        # Actualizar duración si era 0
        dur = self.audio.get_duration()
        if entry["duration"] == 0 and dur > 0:
            db.update_duration(entry["id"], dur)
            screen.ids.lbl_duration.text = self._fmt_time(dur)

        screen.ids.btn_play.icon = "pause-circle-outline"
        Clock.schedule_interval(self._update_progress, self.PROGRESS_INTERVAL)
        self.root.current = "player"

    def _show_edit_category_dialog(self, entry: dict, *args):
        """Muestra un diálogo para cambiar la categoría de un audio existente."""
        from kivy.metrics import dp
        from kivy.uix.boxlayout import BoxLayout
        categories = db.get_categories()
        current_cat = entry.get("category", "Sin categoría")

        container = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        container.bind(minimum_height=container.setter("height"))

        selected = [current_cat]
        btns: list[MDRaisedButton] = []

        def _select(cat, *a):
            selected[0] = cat
            for b in btns:
                b.md_bg_color = [1, 0.757, 0.027, 1] if b.text == cat else [0.129, 0.588, 0.953, 1]
                b.theme_text_color = "Custom"
                b.text_color = [0, 0, 0, 1] if b.text == cat else [1, 1, 1, 1]

        for cat in categories:
            btn = MDRaisedButton(
                text=cat,
                size_hint=(1, None),
                height=dp(40),
            )
            btn.md_bg_color = [1, 0.757, 0.027, 1] if cat == current_cat else [0.129, 0.588, 0.953, 1]
            btn.theme_text_color = "Custom"
            btn.text_color = [0, 0, 0, 1] if cat == current_cat else [1, 1, 1, 1]
            btn.bind(on_release=partial(_select, cat))
            btns.append(btn)
            container.add_widget(btn)

        def save(*a):
            db.update_file_category(entry["id"], selected[0])
            dialog.dismiss()
            self.refresh_library()
            _snack(f'Categoría cambiada a "{selected[0]}"')

        dialog = MDDialog(
            title=f'Categoría: {entry["title"][:30]}',
            type="custom",
            content_cls=container,
            buttons=[
                MDFlatButton(text="CANCELAR", on_release=lambda x: dialog.dismiss()),
                MDRaisedButton(text="GUARDAR", on_release=save),
            ],
        )
        dialog.open()

    def _confirm_delete(self, entry: dict, *args):
        def do_delete(*a):
            db.delete_file(entry["id"])
            self.refresh_library()
            dialog.dismiss()

        dialog = MDDialog(
            title="Eliminar",
            text=f'¿Eliminar "{entry["title"]}" de la biblioteca?',
            buttons=[
                MDFlatButton(text="CANCELAR", on_release=lambda x: dialog.dismiss()),
                MDRaisedButton(text="ELIMINAR", on_release=do_delete),
            ],
        )
        dialog.open()

    # ── Reproductor ───────────────────────────────────────────────────────────

    def toggle_play(self):
        playing = self.audio.play_pause()
        btn = self.root.get_screen("player").ids.btn_play
        btn.icon = "pause-circle-outline" if playing else "play-circle-outline"
        if playing:
            Clock.schedule_interval(self._update_progress, self.PROGRESS_INTERVAL)
        else:
            Clock.unschedule(self._update_progress)

    def skip(self, seconds: float):
        new_pos = max(0.0, self.audio.get_position() + seconds)
        self.audio.seek(new_pos)
        self._update_progress()

    # Mapa velocidad -> id del boton
    _SPEED_BTN = {0.75: "btn_speed_075", 1.0: "btn_speed_1",
                  1.25: "btn_speed_125", 1.5: "btn_speed_150",
                  2.0: "btn_speed_200"}
    _COLOR_ACTIVE   = [1, 0.757, 0.027, 1]
    _COLOR_INACTIVE = [0.129, 0.588, 0.953, 1]
    _TEXT_ACTIVE    = [0, 0, 0, 1]
    _TEXT_INACTIVE  = [1, 1, 1, 1]

    def set_speed(self, rate: float):
        screen = self.root.get_screen("player")
        lbl = screen.ids.lbl_speed_status

        # Resaltar botón pulsado inmediatamente
        for spd, btn_id in self._SPEED_BTN.items():
            btn = screen.ids[btn_id]
            active = (spd == rate)
            btn.md_bg_color = self._COLOR_ACTIVE if active else self._COLOR_INACTIVE
            btn.theme_text_color = "Custom"
            btn.text_color = self._TEXT_ACTIVE if active else self._TEXT_INACTIVE

        lbl.text = f"Preparando {rate}x..."

        def _on_ready():
            Clock.schedule_once(lambda dt: setattr(lbl, "text", f"Velocidad {rate}x lista"))

        self.audio.set_speed(rate, on_ready=_on_ready)

    def on_seek(self, slider, *args):
        duration = self.audio.get_duration()
        if duration > 0:
            self.audio.seek(slider.value * duration)

    def _update_progress(self, *args):
        screen = self.root.get_screen("player")
        pos = self.audio.get_position()
        dur = self.audio.get_duration()
        screen.ids.lbl_position.text    = self._fmt_time(pos)
        screen.ids.progress_slider.value = (pos / dur) if dur > 0 else 0

    def _on_track_complete(self):
        Clock.schedule_once(lambda dt: self._handle_complete_ui())

    def _handle_complete_ui(self):
        screen = self.root.get_screen("player")
        screen.ids.btn_play.icon      = "play-circle-outline"
        screen.ids.progress_slider.value = 0
        Clock.unschedule(self._update_progress)
        self.refresh_library()

    # ── Sleep Timer ───────────────────────────────────────────────────────────

    def show_sleep_timer(self):
        options = [
            MDFlatButton(text="15 min", on_release=partial(self._set_timer, 15)),
            MDFlatButton(text="30 min", on_release=partial(self._set_timer, 30)),
            MDFlatButton(text="60 min", on_release=partial(self._set_timer, 60)),
            MDFlatButton(text="Cancelar", on_release=lambda x: self._cancel_timer()),
        ]
        self._timer_dialog = MDDialog(
            title="Sleep Timer",
            text="Detener reproducción en:",
            buttons=options,
        )
        self._timer_dialog.open()

    def _set_timer(self, minutes: int, *args):
        self._cancel_timer()
        self._sleep_timer = threading.Timer(
            minutes * 60, self._timer_stop
        )
        self._sleep_timer.daemon = True
        self._sleep_timer.start()
        self._timer_dialog.dismiss()
        _snack(f"Sleep timer: {minutes} min")

    def _cancel_timer(self, *args):
        if self._sleep_timer:
            self._sleep_timer.cancel()
            self._sleep_timer = None
        if hasattr(self, "_timer_dialog"):
            self._timer_dialog.dismiss()
        _snack("Sleep timer cancelado")

    def _timer_stop(self):
        Clock.schedule_once(lambda dt: self.audio.play_pause()
                            if self.audio.is_playing() else None)

    # ── Notas ─────────────────────────────────────────────────────────────────

    def show_note_dialog(self):
        if not self._current_file:
            return
        note_field = MDTextField(hint_text="Escribe tu nota aquí...", multiline=True)

        def save_note(*args):
            content = note_field.text.strip()
            if content and self._current_file:
                db.add_note(
                    file_id=self._current_file["id"],
                    position=self.audio.get_position(),
                    content=content,
                )
                _snack("Nota guardada")
            note_dialog.dismiss()

        note_dialog = MDDialog(
            title=f"Nota en {self._fmt_time(self.audio.get_position())}",
            type="custom",
            content_cls=note_field,
            buttons=[
                MDFlatButton(text="CANCELAR", on_release=lambda x: note_dialog.dismiss()),
                MDRaisedButton(text="GUARDAR", on_release=save_note),
            ],
        )
        note_dialog.open()

    # ── Importar ──────────────────────────────────────────────────────────────

    def start_download(self, mode: str):
        screen   = self.root.get_screen("import")
        url      = screen.ids.yt_url.text.strip()

        if not url:
            _snack("Ingresa una URL de YouTube.")
            return

        screen.ids.dl_status.text  = "Obteniendo metadatos..."
        screen.ids.dl_progress.value = 0

        def _fetch():
            meta = fetch_metadata(url)
            title     = meta["title"]     if meta else "Descarga YouTube"
            thumbnail = meta["thumbnail"] if meta else None
            Clock.schedule_once(lambda dt: self._run_download(url, mode, title, thumbnail))

        threading.Thread(target=_fetch, daemon=True).start()

    def _run_download(self, url: str, mode: str, title: str, thumbnail: str = None):
        screen = self.root.get_screen("import")
        screen.ids.dl_status.text = f"Descargando: {title}"

        def on_progress(prog):
            Clock.schedule_once(lambda dt: self._update_dl_ui(prog))

        def on_done(filepath):
            Clock.schedule_once(lambda dt: self._dl_complete(filepath, title, thumbnail))

        def on_error(msg):
            Clock.schedule_once(
                lambda dt, m=msg: _snack(f"Error: {m}")
            )

        self._downloader = YouTubeDownloader(
            on_progress=on_progress,
            on_done=on_done,
            on_error=on_error,
        )
        if mode == "audio":
            self._downloader.download_audio(url)
        else:
            self._downloader.download_video(url)

    def _update_dl_ui(self, prog):
        screen = self.root.get_screen("import")
        screen.ids.dl_progress.value = prog.percent
        screen.ids.dl_status.text = (
            f"{prog.percent:.0f}% · {prog.speed} · ETA {prog.eta}"
            if prog.status == "downloading"
            else "Procesando con FFmpeg..."
        )

    def _dl_complete(self, filepath: str, title: str, thumbnail: str = None):
        screen = self.root.get_screen("import")
        screen.ids.dl_status.text = "¡Descarga completada!"
        screen.ids.dl_progress.value = 100
        db.add_file(title=title, path=filepath, source="youtube",
                    thumbnail=thumbnail, category=self._import_category)
        self.refresh_library()
        _snack(f'"{title}" añadido a la biblioteca')

    def open_file_chooser(self):
        """Abre el selector de archivos nativo del sistema."""
        from kivy.uix.filechooser import FileChooserListView
        from kivymd.uix.dialog import MDDialog

        chooser = FileChooserListView(
            path=self._get_default_path(),
            filters=["*.mp3", "*.mp4", "*.mkv", "*.m4a", "*.ogg", "*.wav"],
        )

        def select_file(*args):
            if chooser.selection:
                path = chooser.selection[0]
                name = os.path.splitext(os.path.basename(path))[0]
                db.add_file(title=name, path=path, source="local",
                            category=self._import_category)
                self.refresh_library()
                _snack(f'"{name}" importado.')
            fc_dialog.dismiss()

        fc_dialog = MDDialog(
            title="Seleccionar Archivo",
            type="custom",
            content_cls=chooser,
            buttons=[
                MDFlatButton(text="CANCELAR", on_release=lambda x: fc_dialog.dismiss()),
                MDRaisedButton(text="IMPORTAR", on_release=select_file),
            ],
        )
        fc_dialog.open()

    def _get_default_path(self) -> str:
        if platform == "android":
            try:
                from jnius import autoclass           # type: ignore
                Env = autoclass("android.os.Environment")
                return str(
                    Env.getExternalStorageDirectory().getAbsolutePath()
                )
            except Exception:
                return "/"
        return os.path.expanduser("~")

    # ── Utilidades ────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        seconds = int(seconds)
        h, rem  = divmod(seconds, 3600)
        m, s    = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"


# ─── Punto de entrada ────────────────────────────────────────────────────────

if __name__ == "__main__":
    AudioReaderApp().run()
