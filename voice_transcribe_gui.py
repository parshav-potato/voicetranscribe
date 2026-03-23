#!/usr/bin/python3 -X utf8
"""
Minimalistic GUI for voice transcription using Whisper API.
Always-on-top window with record button and auto-clipboard copy.
"""
import sys
import os
import json
import math
import time
import struct
import threading
import tempfile
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
import queue
import ctypes
import winsound

from voice_transcribe import (
    ensure_utf8_mode,
    get_api_key,
    transcribe_audio,
    convert_to_mp3,
    AUDIO_EXTENSIONS,
)

try:
    import pyaudio
except ImportError:
    print("Error: pyaudio is required. Install with: uv add pyaudio", file=sys.stderr)
    sys.exit(1)

try:
    import pystray
    from PIL import Image
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    import keyboard as kb
    HAS_HOTKEY = True
except ImportError:
    HAS_HOTKEY = False

try:
    import windnd
    HAS_DND = True
except ImportError:
    HAS_DND = False

# Sleek dark color palette
COLORS = {
    "bg": "#1e1e2e",
    "titlebar": "#181825",
    "accent": "#89b4fa",
    "text": "#cdd6f4",
    "text_dim": "#6c7086",
    "green": "#a6e3a1",
    "green_hover": "#b8f0b0",
    "red": "#f38ba8",
    "red_hover": "#f5a0b8",
    "red_dark": "#8b3a4a",
    "orange": "#fab387",
    "blue": "#89b4fa",
    "border": "#313244",
    "surface": "#24243a",
    "close_hover": "#f38ba8",
    "pin_active": "#f9e2af",
    "pin_inactive": "#6c7086",
    "tooltip_bg": "#313244",
    "meter_bg": "#11111b",
    "meter_green": "#a6e3a1",
    "meter_orange": "#fab387",
    "meter_red": "#f38ba8",
    "progress_bg": "#11111b",
    "progress_fg": "#89b4fa",
}

HOTKEY = "ctrl+shift+r"

LANGUAGES = [
    ("Auto-detect", None),
    ("English", "en"),
    ("German", "de"),
    ("French", "fr"),
    ("Spanish", "es"),
    ("Japanese", "ja"),
    ("Chinese", "zh"),
    ("Dutch", "nl"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Russian", "ru"),
    ("Korean", "ko"),
]

MAX_HISTORY = 20
SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".config", "voicetranscribe")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")

IDLE_ALPHA = 0.45
ACTIVE_ALPHA = 1.0
ALPHA_STEP = 0.08


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(data):
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


class Tooltip:
    """Temporary tooltip window near a widget."""

    def __init__(self, parent, text, duration=4000):
        self.parent = parent
        self.tw = tk.Toplevel(parent)
        self.tw.overrideredirect(True)
        self.tw.attributes("-topmost", True)
        self.tw.configure(bg=COLORS["border"])

        frame = tk.Frame(self.tw, bg=COLORS["tooltip_bg"], padx=8, pady=6)
        frame.pack(padx=1, pady=1)

        label = tk.Label(
            frame, text=text,
            bg=COLORS["tooltip_bg"], fg=COLORS["text"],
            font=("Segoe UI", 9), wraplength=300, justify=tk.LEFT,
        )
        label.pack()

        x = parent.winfo_rootx() + 10
        y = parent.winfo_rooty() + parent.winfo_height() + 4
        self.tw.geometry(f"+{x}+{y}")

        self.tw.bind("<Button-1>", lambda e: self.dismiss())
        label.bind("<Button-1>", lambda e: self.dismiss())
        self._after_id = parent.after(duration, self.dismiss)

    def dismiss(self):
        if self.tw:
            self.parent.after_cancel(self._after_id)
            self.tw.destroy()
            self.tw = None


class HistoryDropdown:
    """Dropdown panel showing transcription history."""

    def __init__(self, parent, history, on_select):
        self.parent = parent
        self.tw = tk.Toplevel(parent)
        self.tw.overrideredirect(True)
        self.tw.attributes("-topmost", True)
        self.tw.configure(bg=COLORS["border"])

        container = tk.Frame(self.tw, bg=COLORS["tooltip_bg"], padx=1, pady=1)
        container.pack(padx=1, pady=1)

        if not history:
            lbl = tk.Label(
                container, text="No history yet",
                bg=COLORS["tooltip_bg"], fg=COLORS["text_dim"],
                font=("Segoe UI", 9), padx=10, pady=6,
            )
            lbl.pack()
        else:
            for i, (timestamp, text) in enumerate(reversed(history)):
                preview = text[:60] + ("..." if len(text) > 60 else "")
                time_str = timestamp.strftime("%H:%M")

                entry_frame = tk.Frame(container, bg=COLORS["tooltip_bg"], cursor="hand2")
                entry_frame.pack(fill=tk.X, padx=2, pady=1)

                time_lbl = tk.Label(
                    entry_frame, text=time_str,
                    bg=COLORS["tooltip_bg"], fg=COLORS["text_dim"],
                    font=("Segoe UI", 8), width=5,
                )
                time_lbl.pack(side=tk.LEFT, padx=(4, 2))

                text_lbl = tk.Label(
                    entry_frame, text=preview,
                    bg=COLORS["tooltip_bg"], fg=COLORS["text"],
                    font=("Segoe UI", 9), anchor="w",
                )
                text_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

                full_text = text
                for w in (entry_frame, time_lbl, text_lbl):
                    w.bind("<Enter>", lambda e, f=entry_frame: f.config(bg=COLORS["surface"]) or
                           [c.config(bg=COLORS["surface"]) for c in f.winfo_children()])
                    w.bind("<Leave>", lambda e, f=entry_frame: f.config(bg=COLORS["tooltip_bg"]) or
                           [c.config(bg=COLORS["tooltip_bg"]) for c in f.winfo_children()])
                    w.bind("<Button-1>", lambda e, t=full_text: (on_select(t), self.dismiss()))

        x = parent.winfo_rootx()
        y = parent.winfo_rooty() + parent.winfo_height() + 4
        self.tw.geometry(f"+{x}+{y}")

        self.tw.bind("<Escape>", lambda e: self.dismiss())
        self.tw.focus_set()
        self.tw.bind("<FocusOut>", lambda e: self.parent.after(100, self._check_focus))

    def _check_focus(self):
        if self.tw and self.tw.winfo_exists():
            try:
                focused = self.tw.focus_get()
                if focused is None or not str(focused).startswith(str(self.tw)):
                    self.dismiss()
            except Exception:
                self.dismiss()

    def dismiss(self):
        if self.tw:
            self.tw.destroy()
            self.tw = None


class VoiceTranscribeGUI:
    """Minimalistic always-on-top GUI for voice transcription."""

    def __init__(self, root):
        self.root = root
        self.window = root

        # Load persisted settings
        self._settings = load_settings()

        self.window.title("Voice Transcribe")
        self.window.geometry("260x100")
        self.window.resizable(False, False)
        self.window.configure(bg=COLORS["bg"])

        # Remove OS titlebar
        self.window.overrideredirect(True)

        # Always on top
        self.always_on_top = tk.BooleanVar(value=True)
        self.window.attributes("-topmost", True)

        self.fix_taskbar_icon()

        # Recording state
        self.is_recording = False
        self.is_processing = False
        self.stop_event = None
        self.recording_thread = None
        self.recorded_file = None
        self.frames = []
        self.audio_stream = None
        self.pa = None
        self.record_start_time = None
        self._timer_after_id = None
        self._pulse_after_id = None
        self._pulse_step = 0
        self._tooltip = None
        self._peak_level = 0.0
        self._progress_after_id = None
        self._progress_pos = 0

        # Capture the foreground window before we take focus
        self._previous_hwnd = None

        # Transcription options (restore from settings)
        self._language = self._settings.get("language", None)
        self._language_name = self._settings.get("language_name", "Auto")
        self._translate = self._settings.get("translate", False)
        self._auto_paste = self._settings.get("auto_paste", True)
        self._transparent_idle = self._settings.get("transparent_idle", True)

        # History
        self._history = []
        self._history_dropdown = None

        # Queue for thread-safe UI updates
        self.message_queue = queue.Queue()

        # Drag state
        self._drag_start_x = 0
        self._drag_start_y = 0

        # Transparency state
        self._target_alpha = IDLE_ALPHA if self._transparent_idle else ACTIVE_ALPHA
        self._current_alpha = ACTIVE_ALPHA
        self._fade_after_id = None
        self._mouse_inside = False

        # Tray icon
        self._tray_icon = None

        self.build_ui()
        self.process_queue()
        self._setup_hotkey()
        self._setup_tray()
        self._setup_dnd()
        self._restore_position()

        # Start idle transparency after a brief delay
        if self._transparent_idle:
            self.window.after(2000, self._fade_to_idle)

        # Track mouse enter/leave on the whole window for transparency
        self.window.bind("<Enter>", self._on_mouse_enter)
        self.window.bind("<Leave>", self._on_mouse_leave)

        # Verify API key
        try:
            get_api_key()
        except Exception as e:
            messagebox.showerror("API Key Error", str(e))
            self.quit_app()

    def fix_taskbar_icon(self):
        try:
            self.window.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.window.winfo_id())
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
            self.window.withdraw()
            self.window.deiconify()
        except Exception:
            pass

    # ── Settings Persistence ─────────────────────────────────────────

    def _save_settings(self):
        data = {
            "language": self._language,
            "language_name": self._language_name,
            "translate": self._translate,
            "auto_paste": self._auto_paste,
            "transparent_idle": self._transparent_idle,
            "window_x": self.window.winfo_x(),
            "window_y": self.window.winfo_y(),
        }
        save_settings(data)

    def _restore_position(self):
        x = self._settings.get("window_x")
        y = self._settings.get("window_y")
        if x is not None and y is not None:
            # Validate position is on screen
            screen_w = self.window.winfo_screenwidth()
            screen_h = self.window.winfo_screenheight()
            if -50 < x < screen_w - 50 and -50 < y < screen_h - 50:
                self.window.geometry(f"+{x}+{y}")

    # ── UI Construction ──────────────────────────────────────────────

    def build_ui(self):
        outer = tk.Frame(self.window, bg=COLORS["bg"])
        outer.pack(fill=tk.BOTH, expand=True)

        inner = tk.Frame(outer, bg=COLORS["bg"], highlightbackground=COLORS["border"],
                         highlightthickness=1)
        inner.pack(fill=tk.BOTH, expand=True)

        # Title bar
        title_frame = tk.Frame(inner, bg=COLORS["titlebar"], height=24)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        title_label = tk.Label(
            title_frame, text="Voice Transcribe",
            bg=COLORS["titlebar"], fg=COLORS["text_dim"],
            font=("Segoe UI", 8),
        )
        title_label.pack(side=tk.LEFT, padx=8)

        # Close button
        self.close_btn = self._make_title_button(title_frame, "\u00d7", self.on_close,
                                                  font=("Segoe UI", 12, "bold"),
                                                  hover_bg=COLORS["close_hover"],
                                                  hover_fg="#1e1e2e")
        self.close_btn.pack(side=tk.RIGHT, padx=(0, 2))

        # Pin button
        self.pin_btn = self._make_title_button(title_frame, "\u25cf", self.toggle_topmost,
                                                font=("Segoe UI", 10),
                                                hover_bg=COLORS["surface"])
        self.pin_btn.config(fg=COLORS["pin_active"])
        self.pin_btn.pack(side=tk.RIGHT)

        # History button
        self.history_btn = self._make_title_button(title_frame, "\u2630", self._show_history,
                                                    font=("Segoe UI", 10),
                                                    hover_bg=COLORS["surface"])
        self.history_btn.pack(side=tk.RIGHT)

        # Drag bindings
        for w in (title_frame, title_label):
            w.bind("<Button-1>", self.start_drag)
            w.bind("<B1-Motion>", self.do_drag)

        # Controls area
        controls = tk.Frame(inner, bg=COLORS["bg"], padx=10, pady=6)
        controls.pack(fill=tk.X)

        # Record button
        self.record_button = tk.Button(
            controls, text="\U0001f3a4", font=("Segoe UI", 14),
            bg=COLORS["green"], fg=COLORS["bg"],
            activebackground=COLORS["green_hover"], activeforeground=COLORS["bg"],
            command=self.toggle_recording,
            width=3, relief=tk.FLAT, bd=0, cursor="hand2",
        )
        self.record_button.pack(side=tk.LEFT, padx=(0, 8))
        self._bind_hover(self.record_button, COLORS["green"], COLORS["green_hover"])
        self.record_button.bind("<Button-3>", self._show_options_menu)

        # Status label
        self.status_label = tk.Label(
            controls, text=self._build_status_text("Ready"),
            font=("Segoe UI", 9), fg=COLORS["text_dim"],
            bg=COLORS["bg"], anchor="w",
        )
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Meter / progress bar area
        self._bar_frame = tk.Frame(inner, bg=COLORS["meter_bg"], height=4)
        self._bar_frame.pack(fill=tk.X, padx=8, pady=(0, 6))
        self._bar_frame.pack_propagate(False)

        # Level meter bar (used during recording)
        self._meter_bar = tk.Frame(self._bar_frame, bg=COLORS["meter_green"], height=4, width=0)
        self._meter_bar.place(x=0, y=0, relheight=1.0, width=0)

        # Progress bar (used during transcription)
        self._progress_bar = tk.Frame(self._bar_frame, bg=COLORS["progress_fg"], height=4, width=0)
        self._progress_bar.place(x=0, y=0, relheight=1.0, width=0)

    def _make_title_button(self, parent, text, command, font=None, hover_bg=None, hover_fg=None):
        btn = tk.Button(
            parent, text=text, command=command,
            bg=COLORS["titlebar"], fg=COLORS["text_dim"],
            font=font or ("Segoe UI", 10),
            activebackground=hover_bg or COLORS["surface"],
            activeforeground=hover_fg or COLORS["text"],
            relief=tk.FLAT, bd=0, width=3, cursor="hand2",
        )
        if hover_bg:
            btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg, fg=hover_fg or COLORS["text"]))
            btn.bind("<Leave>", lambda e: btn.config(bg=COLORS["titlebar"], fg=COLORS["text_dim"]))
        return btn

    def _bind_hover(self, widget, normal_bg, hover_bg):
        widget._normal_bg = normal_bg
        widget._hover_bg = hover_bg
        widget.bind("<Enter>", lambda e: widget.config(bg=widget._hover_bg))
        widget.bind("<Leave>", lambda e: widget.config(bg=widget._normal_bg))

    def _build_status_text(self, base):
        parts = [base]
        if HAS_HOTKEY:
            parts.append(f"({HOTKEY})")
        lang_tag = self._get_lang_tag()
        if lang_tag:
            parts.append(lang_tag)
        return "  ".join(parts)

    def _get_lang_tag(self):
        tags = []
        if self._language:
            tags.append(self._language.upper())
        if self._translate:
            tags.append("EN\u2190")
        if tags:
            return "[" + " ".join(tags) + "]"
        return ""

    # ── Transparency ─────────────────────────────────────────────────

    def _on_mouse_enter(self, event):
        self._mouse_inside = True
        if self._transparent_idle:
            self._fade_to(ACTIVE_ALPHA)

    def _on_mouse_leave(self, event):
        self._mouse_inside = False
        if self._transparent_idle and not self.is_recording and not self.is_processing:
            self.window.after(300, self._check_fade_to_idle)

    def _check_fade_to_idle(self):
        if not self._mouse_inside and not self.is_recording and not self.is_processing:
            self._fade_to(IDLE_ALPHA)

    def _fade_to_idle(self):
        if not self._mouse_inside and not self.is_recording and not self.is_processing:
            self._fade_to(IDLE_ALPHA)

    def _fade_to(self, target):
        self._target_alpha = target
        if self._fade_after_id:
            self.window.after_cancel(self._fade_after_id)
        self._do_fade()

    def _do_fade(self):
        if abs(self._current_alpha - self._target_alpha) < ALPHA_STEP:
            self._current_alpha = self._target_alpha
            self.window.attributes("-alpha", self._current_alpha)
            self._fade_after_id = None
            return

        if self._current_alpha < self._target_alpha:
            self._current_alpha = min(self._current_alpha + ALPHA_STEP, self._target_alpha)
        else:
            self._current_alpha = max(self._current_alpha - ALPHA_STEP, self._target_alpha)

        self.window.attributes("-alpha", self._current_alpha)
        self._fade_after_id = self.window.after(30, self._do_fade)

    # ── Audio Level Meter ────────────────────────────────────────────

    def _update_meter(self):
        if not self.is_recording:
            self._meter_bar.place_configure(width=0)
            return

        level = min(self._peak_level, 1.0)
        meter_width = self._bar_frame.winfo_width()
        bar_width = int(level * meter_width)

        if level > 0.85:
            color = COLORS["meter_red"]
        elif level > 0.5:
            color = COLORS["meter_orange"]
        else:
            color = COLORS["meter_green"]

        self._meter_bar.config(bg=color)
        self._meter_bar.place_configure(width=bar_width)

        self.window.after(50, self._update_meter)

    # ── Progress Bar (indeterminate) ─────────────────────────────────

    def _start_progress(self):
        self._progress_pos = 0
        self._meter_bar.place_configure(width=0)

        def animate():
            bar_width = self._bar_frame.winfo_width()
            seg_width = max(40, bar_width // 4)
            x = int((self._progress_pos % (bar_width + seg_width)) - seg_width)
            self._progress_bar.place_configure(x=x, width=seg_width)
            self._progress_pos += 3
            self._progress_after_id = self.window.after(30, animate)

        self._progress_after_id = self.window.after(30, animate)

    def _stop_progress(self):
        if self._progress_after_id:
            self.window.after_cancel(self._progress_after_id)
            self._progress_after_id = None
        self._progress_bar.place_configure(width=0)

    # ── Status & Queue ───────────────────────────────────────────────

    def set_status(self, text, color=None):
        self.message_queue.put(("status", text, color or COLORS["text_dim"]))

    def process_queue(self):
        try:
            while True:
                msg_type, *args = self.message_queue.get_nowait()
                if msg_type == "status":
                    text, color = args
                    self.status_label.config(text=text, fg=color)
                elif msg_type == "recording_stopped":
                    self.on_recording_complete()
                elif msg_type == "transcription_done":
                    self.on_transcription_complete(args[0])
                elif msg_type == "error":
                    self.on_error(args[0])
                elif msg_type == "level":
                    self._peak_level = args[0]
        except queue.Empty:
            pass
        self.window.after(100, self.process_queue)

    # ── Always on Top ────────────────────────────────────────────────

    def toggle_topmost(self):
        self.always_on_top.set(not self.always_on_top.get())
        self.window.attributes("-topmost", self.always_on_top.get())
        self.pin_btn.config(
            fg=COLORS["pin_active"] if self.always_on_top.get() else COLORS["pin_inactive"]
        )

    # ── Options Menu (Right-click) ───────────────────────────────────

    def _show_options_menu(self, event):
        menu = tk.Menu(self.window, tearoff=0,
                       bg=COLORS["tooltip_bg"], fg=COLORS["text"],
                       activebackground=COLORS["accent"], activeforeground=COLORS["bg"],
                       font=("Segoe UI", 9))

        # Language submenu
        lang_menu = tk.Menu(menu, tearoff=0,
                            bg=COLORS["tooltip_bg"], fg=COLORS["text"],
                            activebackground=COLORS["accent"], activeforeground=COLORS["bg"],
                            font=("Segoe UI", 9))
        for name, code in LANGUAGES:
            check = "\u2713 " if self._language == code else "   "
            lang_menu.add_command(
                label=f"{check}{name}",
                command=lambda c=code, n=name: self._set_language(c, n),
            )
        menu.add_cascade(label="Language", menu=lang_menu)

        # Translate toggle
        tr_check = "\u2713 " if self._translate else "   "
        menu.add_command(label=f"{tr_check}Translate to English", command=self._toggle_translate)

        menu.add_separator()

        # Auto-paste toggle
        ap_check = "\u2713 " if self._auto_paste else "   "
        menu.add_command(label=f"{ap_check}Auto-paste", command=self._toggle_auto_paste)

        # Transparency toggle
        tp_check = "\u2713 " if self._transparent_idle else "   "
        menu.add_command(label=f"{tp_check}Transparent when idle", command=self._toggle_transparency)

        menu.tk_popup(event.x_root, event.y_root)

    def _set_language(self, code, name):
        self._language = code
        self._language_name = name
        self._save_settings()
        self.set_status(self._build_status_text("Ready"), COLORS["text_dim"])

    def _toggle_translate(self):
        self._translate = not self._translate
        self._save_settings()
        self.set_status(self._build_status_text("Ready"), COLORS["text_dim"])

    def _toggle_auto_paste(self):
        self._auto_paste = not self._auto_paste
        self._save_settings()

    def _toggle_transparency(self):
        self._transparent_idle = not self._transparent_idle
        self._save_settings()
        if self._transparent_idle:
            self._fade_to_idle()
        else:
            self._fade_to(ACTIVE_ALPHA)

    # ── History ──────────────────────────────────────────────────────

    def _show_history(self):
        if self._history_dropdown:
            self._history_dropdown.dismiss()
            self._history_dropdown = None
            return
        self._history_dropdown = HistoryDropdown(
            self.window, self._history, self._copy_from_history
        )

    def _copy_from_history(self, text):
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.window.update()
        self.set_status("Copied!", COLORS["green"])
        self.window.after(2000, lambda: self.set_status(
            self._build_status_text("Ready"), COLORS["text_dim"]))

    # ── Drag & Drop ──────────────────────────────────────────────────

    def _setup_dnd(self):
        if not HAS_DND:
            return
        try:
            windnd.hook_dropfiles(self.window, func=self._on_files_dropped)
        except Exception:
            pass

    def _on_files_dropped(self, file_list):
        # windnd returns list of bytes paths
        for raw_path in file_list:
            path = raw_path.decode("utf-8") if isinstance(raw_path, bytes) else raw_path
            ext = os.path.splitext(path)[1].lower()
            if ext in AUDIO_EXTENSIONS:
                self._transcribe_file(path)
                return
        self.set_status("Unsupported file type", COLORS["red"])
        self.window.after(2000, lambda: self.set_status(
            self._build_status_text("Ready"), COLORS["text_dim"]))

    def _transcribe_file(self, path):
        if self.is_recording or self.is_processing:
            return
        self.is_processing = True
        self._capture_previous_window()
        self.record_button.config(state=tk.DISABLED)
        self.set_status("Transcribing file...", COLORS["blue"])
        self._start_progress()
        self._fade_to(ACTIVE_ALPHA)

        def do_transcribe():
            try:
                transcript = transcribe_audio(
                    path, language=self._language,
                    response_format="text", translate=self._translate,
                )
                self.message_queue.put(("transcription_done", transcript.strip()))
            except Exception as e:
                self.message_queue.put(("error", f"Transcription failed: {e}"))

        threading.Thread(target=do_transcribe, daemon=True).start()

    # ── Auto-paste ───────────────────────────────────────────────────

    def _capture_previous_window(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            # Don't capture our own window
            our_hwnd = ctypes.windll.user32.GetParent(self.window.winfo_id())
            if hwnd != our_hwnd and hwnd != 0:
                self._previous_hwnd = hwnd
            else:
                self._previous_hwnd = None
        except Exception:
            self._previous_hwnd = None

    def _do_auto_paste(self):
        if not self._auto_paste or not HAS_HOTKEY or not self._previous_hwnd:
            return

        try:
            # Check if the window still exists
            if not ctypes.windll.user32.IsWindow(self._previous_hwnd):
                return

            # Set focus to the previous window
            ctypes.windll.user32.SetForegroundWindow(self._previous_hwnd)

            # Small delay to let focus switch complete
            time.sleep(0.15)

            # Simulate Ctrl+V
            kb.send("ctrl+v")
        except Exception:
            pass
        finally:
            self._previous_hwnd = None

    # ── Recording ────────────────────────────────────────────────────

    def toggle_recording(self):
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        self._capture_previous_window()
        self.is_recording = True
        self.stop_event = threading.Event()
        self.frames = []
        self.record_start_time = time.time()
        self._peak_level = 0.0

        # Go fully opaque while recording
        self._fade_to(ACTIVE_ALPHA)

        self.record_button.config(
            text="\u23f9", bg=COLORS["red"],
            activebackground=COLORS["red_hover"],
        )
        self.record_button._normal_bg = COLORS["red"]
        self.record_button._hover_bg = COLORS["red_hover"]

        self.set_status("Recording... 0:00", COLORS["red"])
        self._start_timer()
        self._start_pulse()
        self._update_meter()

        self.recording_thread = threading.Thread(target=self.record_audio, daemon=True)
        self.recording_thread.start()

    def stop_recording(self):
        if self.stop_event:
            self.stop_event.set()
        self._stop_timer()
        self._stop_pulse()
        self._peak_level = 0.0
        self._meter_bar.place_configure(width=0)
        self.record_button.config(state=tk.DISABLED)
        self.set_status("Processing...", COLORS["orange"])

    def _reset_button(self):
        self.record_button.config(
            text="\U0001f3a4", bg=COLORS["green"],
            activebackground=COLORS["green_hover"],
            state=tk.NORMAL,
        )
        self.record_button._normal_bg = COLORS["green"]
        self.record_button._hover_bg = COLORS["green_hover"]

    # ── Recording Timer ──────────────────────────────────────────────

    def _start_timer(self):
        def tick():
            if self.is_recording and self.record_start_time:
                elapsed = int(time.time() - self.record_start_time)
                mins, secs = divmod(elapsed, 60)
                self.status_label.config(text=f"Recording... {mins}:{secs:02d}")
                self._timer_after_id = self.window.after(1000, tick)
        self._timer_after_id = self.window.after(1000, tick)

    def _stop_timer(self):
        if self._timer_after_id:
            self.window.after_cancel(self._timer_after_id)
            self._timer_after_id = None

    # ── Pulse Animation ──────────────────────────────────────────────

    def _start_pulse(self):
        self._pulse_step = 0

        def pulse():
            if not self.is_recording:
                return
            t = (math.sin(self._pulse_step * 0.1) + 1) / 2
            r = int(0x8b + (0xf3 - 0x8b) * t)
            g = int(0x3a + (0x8b - 0x3a) * t)
            b = int(0x4a + (0xa8 - 0x4a) * t)
            color = f"#{r:02x}{g:02x}{b:02x}"
            self.record_button.config(bg=color)
            self._pulse_step += 1
            self._pulse_after_id = self.window.after(50, pulse)

        self._pulse_after_id = self.window.after(50, pulse)

    def _stop_pulse(self):
        if self._pulse_after_id:
            self.window.after_cancel(self._pulse_after_id)
            self._pulse_after_id = None

    # ── Audio Recording ──────────────────────────────────────────────

    def record_audio(self):
        RATE = 16000
        CHANNELS = 1
        CHUNK = 1024
        FORMAT = pyaudio.paInt16

        try:
            self.pa = pyaudio.PyAudio()
            self.audio_stream = self.pa.open(
                format=FORMAT, channels=CHANNELS, rate=RATE,
                input=True, frames_per_buffer=CHUNK,
            )

            while not self.stop_event.is_set():
                data = self.audio_stream.read(CHUNK, exception_on_overflow=False)
                self.frames.append(data)

                samples = struct.unpack(f"<{CHUNK}h", data)
                peak = max(abs(s) for s in samples) / 32768.0
                self.message_queue.put(("level", peak))

            if self.frames:
                import wave
                tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp_wav.close()
                with wave.open(tmp_wav.name, "wb") as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(2)
                    wf.setframerate(RATE)
                    wf.writeframes(b"".join(self.frames))

                try:
                    mp3_path = convert_to_mp3(tmp_wav.name)
                    self.recorded_file = mp3_path
                    if os.path.exists(tmp_wav.name):
                        os.unlink(tmp_wav.name)
                    self.message_queue.put(("recording_stopped",))
                except Exception as e:
                    self.message_queue.put(("error", f"Conversion failed: {e}"))
            else:
                self.message_queue.put(("error", "No audio recorded"))

        except Exception as e:
            self.message_queue.put(("error", f"Recording failed: {e}"))
        finally:
            if self.audio_stream:
                self.audio_stream.stop_stream()
                self.audio_stream.close()
                self.audio_stream = None
            if self.pa:
                self.pa.terminate()
                self.pa = None

    def on_recording_complete(self):
        self.is_recording = False
        self.is_processing = True
        self.set_status("Transcribing...", COLORS["blue"])
        self._start_progress()
        threading.Thread(target=self.transcribe_audio_bg, daemon=True).start()

    def transcribe_audio_bg(self):
        try:
            transcript = transcribe_audio(
                self.recorded_file,
                language=self._language,
                response_format="text",
                translate=self._translate,
            )
            self.message_queue.put(("transcription_done", transcript.strip()))
        except Exception as e:
            self.message_queue.put(("error", f"Transcription failed: {e}"))
        finally:
            if self.recorded_file and os.path.exists(self.recorded_file):
                try:
                    os.unlink(self.recorded_file)
                except Exception:
                    pass
                self.recorded_file = None

    def on_transcription_complete(self, transcript):
        self.is_processing = False
        self._stop_progress()

        try:
            self.window.clipboard_clear()
            self.window.clipboard_append(transcript)
            self.window.update()

            # Add to history
            self._history.append((datetime.now(), transcript))
            if len(self._history) > MAX_HISTORY:
                self._history.pop(0)

            self._reset_button()
            self.set_status("Copied!", COLORS["green"])

            # Play completion sound
            try:
                winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass

            # Tray notification if minimized
            if self._tray_icon and not self.window.winfo_viewable():
                try:
                    preview = transcript[:80] + ("..." if len(transcript) > 80 else "")
                    self._tray_icon.notify("Transcription complete", preview)
                except Exception:
                    pass

            # Show tooltip
            preview = transcript[:100] + ("..." if len(transcript) > 100 else "")
            if self._tooltip:
                self._tooltip.dismiss()
            self._tooltip = Tooltip(self.window, preview, duration=4000)

            # Auto-paste in background thread (has a small sleep)
            if self._auto_paste and self._previous_hwnd:
                threading.Thread(target=self._do_auto_paste, daemon=True).start()

            # Fade to idle after a delay
            self.window.after(3000, lambda: self.set_status(
                self._build_status_text("Ready"), COLORS["text_dim"]))
            if self._transparent_idle:
                self.window.after(4000, self._check_fade_to_idle)

        except Exception as e:
            self.on_error(f"Clipboard error: {e}")

    def on_error(self, error_msg):
        self.is_recording = False
        self.is_processing = False
        self._stop_timer()
        self._stop_pulse()
        self._stop_progress()
        self._peak_level = 0.0
        self._meter_bar.place_configure(width=0)
        self._reset_button()
        self.set_status("Error", COLORS["red"])
        messagebox.showerror("Error", error_msg)

        if self.recorded_file and os.path.exists(self.recorded_file):
            try:
                os.unlink(self.recorded_file)
            except Exception:
                pass
            self.recorded_file = None
        self.set_status(self._build_status_text("Ready"), COLORS["text_dim"])
        if self._transparent_idle:
            self.window.after(1000, self._check_fade_to_idle)

    # ── Drag ─────────────────────────────────────────────────────────

    def start_drag(self, event):
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def do_drag(self, event):
        x = self.window.winfo_x() + event.x - self._drag_start_x
        y = self.window.winfo_y() + event.y - self._drag_start_y
        self.window.geometry(f"+{x}+{y}")

    # ── Global Hotkey ────────────────────────────────────────────────

    def _setup_hotkey(self):
        if not HAS_HOTKEY:
            return
        try:
            kb.add_hotkey(HOTKEY, self._hotkey_triggered)
        except Exception:
            pass

    def _hotkey_triggered(self):
        self.window.after(0, self._hotkey_action)

    def _hotkey_action(self):
        if not self.window.winfo_viewable():
            self.window.deiconify()
            self.window.attributes("-topmost", self.always_on_top.get())
        self.toggle_recording()

    def _remove_hotkey(self):
        if HAS_HOTKEY:
            try:
                kb.unhook_all_hotkeys()
            except Exception:
                pass

    # ── System Tray ──────────────────────────────────────────────────

    def _setup_tray(self):
        if not HAS_TRAY:
            return

        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "microphone_icon.ico")
        if not os.path.exists(icon_path):
            return

        try:
            image = Image.open(icon_path)
        except Exception:
            return

        menu = pystray.Menu(
            pystray.MenuItem("Show / Hide", self._tray_toggle_window, default=True),
            pystray.MenuItem("Start Recording", self._tray_record),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._tray_quit),
        )

        self._tray_icon = pystray.Icon("voicetranscribe", image, "Voice Transcribe", menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _tray_toggle_window(self, icon=None, item=None):
        self.window.after(0, self._toggle_visibility)

    def _toggle_visibility(self):
        if self.window.winfo_viewable():
            self.window.withdraw()
        else:
            self.window.deiconify()
            self.window.attributes("-topmost", self.always_on_top.get())

    def _tray_record(self, icon=None, item=None):
        self.window.after(0, self._hotkey_action)

    def _tray_quit(self, icon=None, item=None):
        self.window.after(0, self.quit_app)

    # ── Close / Quit ─────────────────────────────────────────────────

    def on_close(self):
        self._save_settings()
        if self._tray_icon:
            self.window.withdraw()
        else:
            self.quit_app()

    def quit_app(self):
        self._save_settings()

        if self.is_recording and self.stop_event:
            self.stop_event.set()
        self._stop_timer()
        self._stop_pulse()
        self._stop_progress()
        self._remove_hotkey()

        if self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
        if self.pa:
            self.pa.terminate()
        if self.recorded_file and os.path.exists(self.recorded_file):
            try:
                os.unlink(self.recorded_file)
            except Exception:
                pass
        if self._tray_icon:
            self._tray_icon.stop()

        self.window.destroy()


def main():
    root = tk.Tk()
    app = VoiceTranscribeGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
