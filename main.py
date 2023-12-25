from os import path
import subprocess
import sys
import asyncio
import threading
from pynput import keyboard
from pynput import mouse
from services.audio_recorder import AudioRecorder
from services.secret_keeper import SecretKeeper
from services.tower import Tower
from services.printr import Printr
from services.config_manager import ConfigManager
from gui.root import WingmanUI
from wingmen.wingman import Wingman

# ─────────────────────────────────── ↓ MONKEY PATCHING ↓ ─────────────────────────────────────────
# Patch all subprocess calls to hide the console window on Windows
# Otherwise the console window will pop up every time a subprocess is called, like when playing audio
# which leads to loosing focus on the game you are playing
original_call = subprocess.call
original_popen_init = subprocess.Popen.__init__

# Monkey patch call
def monkey_patched_call(*args, **kwargs):
    if 'creationflags' not in kwargs and sys.platform.startswith('win'):
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    return original_call(*args, **kwargs)

# Monkey patch Popen.__init__
def popen_init(self, *args, **kwargs):
    if 'creationflags' not in kwargs and sys.platform.startswith('win'):
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    original_popen_init(self, *args, **kwargs)

# Monkey patch Popen and call
subprocess.Popen.__init__ = popen_init
subprocess.call = monkey_patched_call
# ─────────────────────────────────── MONKEY PATCHING ─────────────────────────────────────────

printr = Printr()


class WingmanAI:
    def __init__(self):
        self.active = False
        self.active_recording = {"key": "", "wingman": None}
        self.tower = None
        self.audio_recorder = AudioRecorder()
        self.app_is_bundled = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
        self.app_root_dir = path.abspath(path.dirname(__file__))
        self.config_manager = ConfigManager(self.app_root_dir, self.app_is_bundled)
        self.secret_keeper = SecretKeeper(self.app_root_dir)

    def load_context(self, context=""):
        self.active = False
        try:
            if self.config_manager:
                config = self.config_manager.get_context_config(context)
                self.tower = Tower(config, self.secret_keeper)

        except FileNotFoundError:
            printr.print_err(f"Could not find context.{context}.yaml", True)
        except Exception as e:
            # Everything else...
            printr.print_err(str(e), True)

    def activate(self):
        if self.tower:
            self.active = True

    def deactivate(self):
        self.active = False

    def on_press(self, key):
        if self.active and self.tower and self.active_recording["key"] == "":
            wingman = self.tower.get_wingman_from_key(key)
            if wingman:
                self.active_recording = dict(key=key, wingman=wingman)
                self.audio_recorder.start_recording()

    def on_release(self, key):
        if self.active and self.active_recording["key"] == key:
            wingman = self.active_recording["wingman"]
            recorded_audio_wav = self.audio_recorder.stop_recording()
            self.active_recording = dict(key="", wingman=None)

            def run_async_process():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    if isinstance(wingman, Wingman):
                        loop.run_until_complete(
                            wingman.process(str(recorded_audio_wav))
                        )
                finally:
                    loop.close()

            if recorded_audio_wav:
                play_thread = threading.Thread(target=run_async_process)
                play_thread.start()

    def on_press_mouse(self, x, y, button, pressed):
        # print(f"Button: {button.name}, Pressed: {pressed}")
        if button.name == "x1":
            if pressed and self.active and self.tower and self.active_recording["key"] == "":
                wingman = self.tower.get_wingman_from_key(button)
                if wingman:
                    self.active_recording = dict(key=button, wingman=wingman)
                    self.audio_recorder.start_recording()

            if not pressed and self.active and self.active_recording["key"] == button:
                wingman = self.active_recording["wingman"]
                recorded_audio_wav = self.audio_recorder.stop_recording()
                self.active_recording = dict(key="", wingman=None)

                def run_async_process():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        if isinstance(wingman, Wingman):
                            loop.run_until_complete(
                                wingman.process(str(recorded_audio_wav))
                            )
                    finally:
                        loop.close()

                if recorded_audio_wav:
                    play_thread = threading.Thread(target=run_async_process)
                    play_thread.start()


# ─────────────────────────────────── ↓ START ↓ ─────────────────────────────────────────
if __name__ == "__main__":
    core = WingmanAI()

    # NOTE this is the only possibility to use `pynput` and `tkinter` in parallel
    listener = keyboard.Listener(on_press=core.on_press, on_release=core.on_release)
    listener.start()
    listener.wait()

    # Maus-Listener starten
    mouseListener = mouse.Listener(on_click=core.on_press_mouse)
    mouseListener.start()
    mouseListener.wait()

    ui = WingmanUI(core)
    ui.mainloop()

    listener.stop()
    mouseListener.stop()

