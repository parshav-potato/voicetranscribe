#!/usr/bin/python3 -X utf8
"""
Minimalistic GUI for voice transcription using Whisper API.
Always-on-top window with record button and auto-clipboard copy.
"""
import sys
import os
import math
import time
import threading
import tempfile
import tkinter as tk
from tkinter import messagebox
import queue

from voice_transcribe import (
    ensure_utf8_mode,
    get_api_key,
    transcribe_audio,
    convert_to_mp3
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
}

HOTKEY = "ctrl+shift+r"


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
            frame,
            text=text,
            bg=COLORS["tooltip_bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 9),
            wraplength=300,
            justify=tk.LEFT,
        )
        label.pack()

        # Position near parent window
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


class VoiceTranscribeGUI:
    """Minimalistic always-on-top GUI for voice transcription."""

    def __init__(self, root):
        self.root = root
        self.window = root

        self.window.title("Voice Transcribe")
        self.window.geometry("240x90")
        self.window.minsize(200, 90)
        self.window.resizable(True, False)
        self.window.configure(bg=COLORS["bg"])

        # Remove OS titlebar
        self.window.overrideredirect(True)

        # Always on top
        self.always_on_top = tk.BooleanVar(value=True)
        self.window.attributes("-topmost", True)

        self.fix_taskbar_icon()

        # Recording state
        self.is_recording = False
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

        # Queue for thread-safe UI updates
        self.message_queue = queue.Queue()

        # Drag state
        self._drag_start_x = 0
        self._drag_start_y = 0

        # Tray icon
        self._tray_icon = None

        self.build_ui()
        self.process_queue()
        self._setup_hotkey()
        self._setup_tray()

        # Verify API key
        try:
            get_api_key()
        except Exception as e:
            messagebox.showerror("API Key Error", str(e))
            self.quit_app()

    def fix_taskbar_icon(self):
        """Force taskbar icon on Windows even with overrideredirect."""
        try:
            import ctypes
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

    # ── UI Construction ──────────────────────────────────────────────

    def build_ui(self):
        outer = tk.Frame(self.window, bg=COLORS["bg"])
        outer.pack(fill=tk.BOTH, expand=True)

        # Border effect
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
        self.pin_btn.pack(side=tk.RIGHT, padx=(0, 0))

        # Drag bindings
        for w in (title_frame, title_label):
            w.bind("<Button-1>", self.start_drag)
            w.bind("<B1-Motion>", self.do_drag)

        # Controls area
        controls = tk.Frame(inner, bg=COLORS["bg"], padx=10, pady=8)
        controls.pack(fill=tk.BOTH, expand=True)

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

        # Status label
        hotkey_hint = f"  ({HOTKEY.replace('+', '+')})" if HAS_HOTKEY else ""
        self.status_label = tk.Label(
            controls, text=f"Ready{hotkey_hint}",
            font=("Segoe UI", 9), fg=COLORS["text_dim"],
            bg=COLORS["bg"], anchor="w",
        )
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Resize grip
        grip = tk.Frame(inner, bg=COLORS["border"], width=12, height=12, cursor="size_nw_se")
        grip.place(relx=1.0, rely=1.0, anchor="se")
        grip.bind("<Button-1>", self._start_resize)
        grip.bind("<B1-Motion>", self._do_resize)

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

    # ── Resize ───────────────────────────────────────────────────────

    def _start_resize(self, event):
        self._resize_start_x = event.x_root
        self._resize_start_w = self.window.winfo_width()

    def _do_resize(self, event):
        dx = event.x_root - self._resize_start_x
        new_w = max(200, self._resize_start_w + dx)
        self.window.geometry(f"{new_w}x{self.window.winfo_height()}")

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
        except queue.Empty:
            pass
        self.window.after(100, self.process_queue)

    # ── Always on Top ────────────────────────────────────────────────

    def toggle_topmost(self):
        self.always_on_top.set(not self.always_on_top.get())
        self.window.attributes("-topmost", self.always_on_top.get())
        if self.always_on_top.get():
            self.pin_btn.config(fg=COLORS["pin_active"])
        else:
            self.pin_btn.config(fg=COLORS["pin_inactive"])

    # ── Recording ────────────────────────────────────────────────────

    def toggle_recording(self):
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        self.is_recording = True
        self.stop_event = threading.Event()
        self.frames = []
        self.record_start_time = time.time()

        # Update button to stop state
        self.record_button.config(
            text="\u23f9", bg=COLORS["red"],
            activebackground=COLORS["red_hover"],
        )
        self.record_button._normal_bg = COLORS["red"]
        self.record_button._hover_bg = COLORS["red_hover"]

        self.set_status("Recording... 0:00", COLORS["red"])
        self._start_timer()
        self._start_pulse()

        self.recording_thread = threading.Thread(target=self.record_audio, daemon=True)
        self.recording_thread.start()

    def stop_recording(self):
        if self.stop_event:
            self.stop_event.set()
        self._stop_timer()
        self._stop_pulse()
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
            # Sinusoidal interpolation between red and red_dark
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
        self.set_status("Transcribing...", COLORS["blue"])
        threading.Thread(target=self.transcribe_audio_bg, daemon=True).start()

    def transcribe_audio_bg(self):
        try:
            transcript = transcribe_audio(
                self.recorded_file, language=None, response_format="text"
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
        try:
            self.window.clipboard_clear()
            self.window.clipboard_append(transcript)
            self.window.update()

            self._reset_button()
            self.set_status("Copied!", COLORS["green"])

            # Show tooltip with transcript preview
            preview = transcript[:100] + ("..." if len(transcript) > 100 else "")
            if self._tooltip:
                self._tooltip.dismiss()
            self._tooltip = Tooltip(self.window, preview, duration=4000)

            self.window.after(3000, lambda: self.set_status(
                f"Ready  ({HOTKEY})" if HAS_HOTKEY else "Ready", COLORS["text_dim"]))
        except Exception as e:
            self.on_error(f"Clipboard error: {e}")

    def on_error(self, error_msg):
        self.is_recording = False
        self._stop_timer()
        self._stop_pulse()
        self._reset_button()
        self.set_status("Error", COLORS["red"])
        messagebox.showerror("Error", error_msg)

        if self.recorded_file and os.path.exists(self.recorded_file):
            try:
                os.unlink(self.recorded_file)
            except Exception:
                pass
            self.recorded_file = None
        self.set_status(f"Ready  ({HOTKEY})" if HAS_HOTKEY else "Ready", COLORS["text_dim"])

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
        # Schedule on tkinter main thread
        self.window.after(0, self._hotkey_action)

    def _hotkey_action(self):
        # Restore window if hidden
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
        tray_thread = threading.Thread(target=self._tray_icon.run, daemon=True)
        tray_thread.start()

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
        """Close button minimizes to tray if available, otherwise quits."""
        if self._tray_icon:
            self.window.withdraw()
        else:
            self.quit_app()

    def quit_app(self):
        """Full shutdown."""
        if self.is_recording and self.stop_event:
            self.stop_event.set()
        self._stop_timer()
        self._stop_pulse()
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
