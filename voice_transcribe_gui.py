#!/usr/bin/python3 -X utf8
"""
Minimalistic GUI for voice transcription using Whisper API.
Always-on-top window with record button and auto-clipboard copy.
"""
import sys
import os
import threading
import tempfile
import tkinter as tk
from tkinter import messagebox
import queue

# Import core functions from voice_transcribe module
from voice_transcribe import (
    ensure_utf8_mode,
    get_api_key,
    transcribe_audio,
    convert_to_mp3
)

try:
    import pyaudio
except ImportError:
    print("Error: pyaudio is required for recording.", file=sys.stderr)
    print("Install it with: pip install pyaudio", file=sys.stderr)
    sys.exit(1)


class VoiceTranscribeGUI:
    """Minimalistic always-on-top GUI for voice transcription."""
    
    def __init__(self, root):
        self.root = root
        self.window = root  # Use root directly instead of Toplevel
        
        self.window.title("Voice Transcribe")
        self.window.geometry("200x90")
        self.window.resizable(False, False)
        
        # Remove OS titlebar
        self.window.overrideredirect(True)
        
        # Always on top state
        self.always_on_top = tk.BooleanVar(value=True)
        self.window.attributes('-topmost', True)
        
        # Force taskbar icon on Windows using ctypes
        self.fix_taskbar_icon()
        
        # Recording state
        self.is_recording = False
        self.stop_event = None
        self.recording_thread = None
        self.recorded_file = None
        self.frames = []
        self.audio_stream = None
        self.pa = None
        
        # Queue for thread-safe UI updates
        self.message_queue = queue.Queue()
        
        # Drag window variables
        self._drag_start_x = 0
        self._drag_start_y = 0
        
        # Build UI
        self.build_ui()
        
        # Process message queue
        self.process_queue()
        
        # Verify API key on startup
        try:
            get_api_key()
        except Exception as e:
            messagebox.showerror("API Key Error", str(e))
            self.window.destroy()
    
    def fix_taskbar_icon(self):
        """Force taskbar icon to appear on Windows even with overrideredirect."""
        try:
            import ctypes
            # Wait for window to be created
            self.window.update_idletasks()
            
            # Get window handle
            hwnd = ctypes.windll.user32.GetParent(self.window.winfo_id())
            
            # Windows styles
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            
            # Get current style
            style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            # Add APPWINDOW (shows in taskbar) and remove TOOLWINDOW (hides from taskbar)
            style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
            # Set new style
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
            
            # Force window to redraw
            self.window.withdraw()
            self.window.deiconify()
        except Exception as e:
            # Non-Windows platform or ctypes issue - just continue
            print(f"Could not set taskbar icon: {e}", file=sys.stderr)
    
    def build_ui(self):
        """Build the minimal UI components."""
        # Main frame with padding
        frame = tk.Frame(self.window, padx=5, pady=5)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Title bar for dragging (minimal)
        title_frame = tk.Frame(frame, bg="#2c3e50", height=18)
        title_frame.pack(fill=tk.X, pady=(0, 3))
        title_label = tk.Label(
            title_frame,
            text="Voice Transcribe",
            bg="#2c3e50",
            fg="white",
            font=("Arial", 8)
        )
        title_label.pack(side=tk.LEFT, padx=5)
        
        # Close button
        close_button = tk.Button(
            title_frame,
            text="×",
            bg="#2c3e50",
            fg="white",
            font=("Arial", 12, "bold"),
            activebackground="#c0392b",
            activeforeground="white",
            command=self.on_close,
            relief=tk.FLAT,
            bd=0,
            width=2,
            cursor="hand2"
        )
        close_button.pack(side=tk.RIGHT, padx=2)
        
        # Pin button (always on top toggle)
        self.pin_button = tk.Button(
            title_frame,
            text="📌",
            bg="#2c3e50",
            fg="#f39c12",  # Orange when pinned
            font=("Arial", 10),
            activebackground="#34495e",
            command=self.toggle_topmost,
            relief=tk.FLAT,
            bd=0,
            width=2,
            cursor="hand2"
        )
        self.pin_button.pack(side=tk.RIGHT, padx=2)
        
        # Bind dragging to title frame
        title_frame.bind("<Button-1>", self.start_drag)
        title_frame.bind("<B1-Motion>", self.do_drag)
        title_label.bind("<Button-1>", self.start_drag)
        title_label.bind("<B1-Motion>", self.do_drag)
        
        # Horizontal frame for button and status
        controls_frame = tk.Frame(frame)
        controls_frame.pack(fill=tk.X, pady=(0, 0))
        
        # Record button
        self.record_button = tk.Button(
            controls_frame,
            text="🎤",
            font=("Arial", 16),
            bg="#4CAF50",
            fg="white",
            activebackground="#45a049",
            command=self.toggle_recording,
            width=3,
            height=1,
            relief=tk.RAISED,
            cursor="hand2"
        )
        self.record_button.pack(side=tk.LEFT, padx=(0, 5))
        
        # Status label
        self.status_label = tk.Label(
            controls_frame,
            text="Ready",
            font=("Arial", 9),
            fg="gray",
            anchor="w"
        )
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
    
    def set_status(self, text, color="gray"):
        """Update status label (thread-safe via queue)."""
        self.message_queue.put(("status", text, color))
    
    def process_queue(self):
        """Process messages from worker threads."""
        try:
            while True:
                msg_type, *args = self.message_queue.get_nowait()
                
                if msg_type == "status":
                    text, color = args
                    self.status_label.config(text=text, fg=color)
                elif msg_type == "recording_stopped":
                    self.on_recording_complete()
                elif msg_type == "transcription_done":
                    transcript = args[0]
                    self.on_transcription_complete(transcript)
                elif msg_type == "error":
                    error_msg = args[0]
                    self.on_error(error_msg)
        except queue.Empty:
            pass
        
        # Schedule next check
        self.window.after(100, self.process_queue)
    
    def toggle_topmost(self):
        """Toggle always-on-top behavior."""
        # Toggle the state
        self.always_on_top.set(not self.always_on_top.get())
        self.window.attributes('-topmost', self.always_on_top.get())
        
        # Update pin button appearance
        if self.always_on_top.get():
            self.pin_button.config(fg="#f39c12")  # Orange when pinned
        else:
            self.pin_button.config(fg="#7f8c8d")  # Gray when unpinned
    
    def toggle_recording(self):
        """Toggle between start and stop recording."""
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()
    
    def start_recording(self):
        """Start audio recording in background thread."""
        self.is_recording = True
        self.stop_event = threading.Event()
        self.frames = []
        
        # Update UI
        self.record_button.config(
            text="⏹️",
            bg="#f44336",
            activebackground="#da190b"
        )
        self.set_status("Recording...", "red")
        
        # Start recording thread
        self.recording_thread = threading.Thread(
            target=self.record_audio,
            daemon=True
        )
        self.recording_thread.start()
    
    def stop_recording(self):
        """Signal recording thread to stop."""
        if self.stop_event:
            self.stop_event.set()
        
        # Disable button during processing
        self.record_button.config(state=tk.DISABLED)
        self.set_status("Stopping...", "orange")
    
    def record_audio(self):
        """Record audio in background thread (adapted from voice_transcribe.py)."""
        RATE = 16000
        CHANNELS = 1
        CHUNK = 1024
        FORMAT = pyaudio.paInt16
        
        try:
            self.pa = pyaudio.PyAudio()
            
            # Open stream
            self.audio_stream = self.pa.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK
            )
            
            # Record until stop event is set
            while not self.stop_event.is_set():
                data = self.audio_stream.read(CHUNK, exception_on_overflow=False)
                self.frames.append(data)
            
            # Save to temporary WAV file
            if self.frames:
                import wave
                tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp_wav.close()
                
                with wave.open(tmp_wav.name, "wb") as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(2)  # paInt16 = 2 bytes
                    wf.setframerate(RATE)
                    wf.writeframes(b"".join(self.frames))
                
                # Convert to mp3
                try:
                    mp3_path = convert_to_mp3(tmp_wav.name)
                    self.recorded_file = mp3_path
                    
                    # Clean up wav file
                    if os.path.exists(tmp_wav.name):
                        os.unlink(tmp_wav.name)
                    
                    duration = len(self.frames) * CHUNK / RATE
                    self.message_queue.put(("recording_stopped", duration))
                except Exception as e:
                    self.message_queue.put(("error", f"Conversion failed: {e}"))
            else:
                self.message_queue.put(("error", "No audio recorded"))
        
        except Exception as e:
            self.message_queue.put(("error", f"Recording failed: {e}"))
        
        finally:
            # Clean up audio resources
            if self.audio_stream:
                self.audio_stream.stop_stream()
                self.audio_stream.close()
                self.audio_stream = None
            if self.pa:
                self.pa.terminate()
                self.pa = None
    
    def on_recording_complete(self):
        """Called when recording finishes successfully."""
        self.is_recording = False
        
        # Start transcription in background
        self.set_status("Transcribing...", "blue")
        
        transcription_thread = threading.Thread(
            target=self.transcribe_audio_bg,
            daemon=True
        )
        transcription_thread.start()
    
    def transcribe_audio_bg(self):
        """Transcribe audio in background thread."""
        try:
            transcript = transcribe_audio(
                self.recorded_file,
                language=None,  # Auto-detect
                response_format="text"
            )
            
            # Ensure we only have plain text (strip any JSON formatting if present)
            text = transcript.strip()
            
            # If somehow JSON was returned, extract the text field
            if text.startswith('{') and text.endswith('}'):
                try:
                    import json
                    data = json.loads(text)
                    text = data.get('text', text)
                except:
                    pass  # Not JSON, use as-is
            
            self.message_queue.put(("transcription_done", text))
        
        except Exception as e:
            self.message_queue.put(("error", f"Transcription failed: {e}"))
        
        finally:
            # Clean up recorded file
            if self.recorded_file and os.path.exists(self.recorded_file):
                try:
                    os.unlink(self.recorded_file)
                except:
                    pass
                self.recorded_file = None
    
    def on_transcription_complete(self, transcript):
        """Called when transcription finishes successfully."""
        # Copy to clipboard
        try:
            self.window.clipboard_clear()
            self.window.clipboard_append(transcript)
            self.window.update()
            
            # Show success status
            self.set_status("✓ Copied to clipboard!", "green")
            
            # Reset button
            self.record_button.config(
                text="🎤",
                bg="#4CAF50",
                activebackground="#45a049",
                state=tk.NORMAL
            )
            
            # Auto-clear status after 3 seconds
            self.window.after(3000, lambda: self.set_status("Ready", "gray"))
        
        except Exception as e:
            self.on_error(f"Clipboard error: {e}")
    
    def on_error(self, error_msg):
        """Handle errors."""
        self.is_recording = False
        
        # Reset UI
        self.record_button.config(
            text="🎤",
            bg="#4CAF50",
            activebackground="#45a049",
            state=tk.NORMAL
        )
        self.set_status("Error!", "red")
        
        # Show error dialog
        messagebox.showerror("Error", error_msg)
        
        # Clean up
        if self.recorded_file and os.path.exists(self.recorded_file):
            try:
                os.unlink(self.recorded_file)
            except:
                pass
            self.recorded_file = None
        
        # Reset status after dialog closed
        self.set_status("Ready", "gray")
    
    def start_drag(self, event):
        """Start dragging the window."""
        self._drag_start_x = event.x
        self._drag_start_y = event.y
    
    def do_drag(self, event):
        """Handle window dragging."""
        x = self.window.winfo_x() + event.x - self._drag_start_x
        y = self.window.winfo_y() + event.y - self._drag_start_y
        self.window.geometry(f"+{x}+{y}")
    
    def on_close(self):
        """Handle window close event."""
        # Stop recording if active
        if self.is_recording and self.stop_event:
            self.stop_event.set()
        
        # Clean up resources
        if self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
        if self.pa:
            self.pa.terminate()
        if self.recorded_file and os.path.exists(self.recorded_file):
            try:
                os.unlink(self.recorded_file)
            except:
                pass
        
        self.window.destroy()


def main():
    """Entry point for GUI application."""
   #ensure_utf8_mode()
    
    root = tk.Tk()
    app = VoiceTranscribeGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
