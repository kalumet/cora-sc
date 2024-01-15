from os import path
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

printr = Printr()

DEBUG = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


def get_application_root(is_bundled: bool):
    if is_bundled:
        application_path = sys._MEIPASS
    else:
        application_path = path.dirname(path.abspath(__file__))
    return application_path


class WingmanAI:
    def __init__(self):
        # pyinstaller things...
        self.app_is_bundled = getattr(sys, "frozen", False)
        self.app_root_dir = get_application_root(self.app_is_bundled)

        self.active = False
        self.active_recording = {"key": "", "wingman": None}
        self.tower = None
        self.config_manager = ConfigManager(self.app_root_dir, self.app_is_bundled)
        self.secret_keeper = SecretKeeper(self.app_root_dir)
        self.audio_recorder = AudioRecorder(self.app_root_dir)

    def load_context(self, context=""):
        self.active = False
        try:
            if self.config_manager:
                config = self.config_manager.get_context_config(context)
                self.tower = Tower(
                    config=config,
                    secret_keeper=self.secret_keeper,
                    app_root_dir=self.app_root_dir,
                )

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
        print_debug(f"key pressed: {key}")
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
        print_debug(f"Button: {button.name}, Pressed: {pressed}")
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
    # allow access to main ui thread
    core = WingmanAI()

    # NOTE this is the only possibility to use `pynput` and `tkinter` in parallel
    listener = keyboard.Listener(on_press=core.on_press, on_release=core.on_release)
    listener.start()
    listener.wait()

    # Maus-Listener starten
    mouseListener = mouse.Listener(on_click=core.on_press_mouse)
    mouseListener.start()
    mouseListener.wait()

    # create a singelton instance of the ui
    ui = WingmanUI.get_instance(core)
    ui.process_tkinter_queue()
    ui.mainloop()

    listener.stop()
    mouseListener.stop()

