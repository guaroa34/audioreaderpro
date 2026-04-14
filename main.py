"""
Módulo C: Interfaz principal — Kivy/KivyMD
Pantallas:
  • LibraryScreen  — lista de audiolibros con barra de progreso
  • PlayerScreen   — reproductor con controles completos
  • ImportScreen   — importar desde YouTube o archivo local
"""
import os
import threading
from functools import partial

from kivy.lang import Builder
from kivy.clock import Clock
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.utils import platform
from kivy.core.window import Window
from kivy.uix.image import AsyncImage
from kivy.uix.boxlayout import BoxLayout as KivyBoxLayout

from kivymd.app import MDApp
from kivymd.uix.list import (
    MDList, TwoLineAvatarIconListItem, IconLeftWidget, IconRightWidget
)
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton, MDRaisedButton, MDIconButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.snackbar import MDSnackbar
from kivymd.uix.label import MDLabel
from kivymd.uix.progressbar import MDProgressBar
from kivymd.uix.selectioncontrol import MDCheckbox
from kivymd.uix.chip import MDChip


def _snack(text: str) -> None:
    """Muestra un snackbar con mensaje (API KivyMD 1.2.0)."""
    MDSnackbar(MDLabel(text=text)).open()

import database as db
from audio_service import AudioService
from downloader import YouTubeDownloader, fetch_metadata

# ─── Permisos de Android en tiempo de ejecución ──────────────────────────────
def request_android_permissions():
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
