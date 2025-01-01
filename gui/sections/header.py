import customtkinter as ctk
from gui.components.icon_button import IconButton
from services.printr import Printr


printr = Printr()

class Header(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(1, weight=1)

        self.settings_button = IconButton(self,
                                icon="settings",
                                size=32,
                                themed=False,
                                command=lambda: master.show_view("settings"))
        self.settings_button.grid(row=0, column=4, padx=5, pady=5, sticky="e")

