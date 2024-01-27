import copy
import tkinter as tk
from tkinter import ttk
from tkinter.ttk import Style
import json

from threading import Thread
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageColor
from screeninfo import get_monitors

from gui.root import WingmanUI 

from wingmen.star_citizen_services.functions.uex_update_services.commodity_price_validator import CommodityPriceValidator
from wingmen.star_citizen_services.location_name_matching import LocationNameMatching



class OverlayPopup(tk.Toplevel):
    def __init__(self, master, validated_tradeport, operation, all_prices, cropped_screenshot_prices, cropped_screenshot_location_pil):
        super().__init__(master)
        
        self.current_tradeport = validated_tradeport
        self.updated_data = copy.deepcopy(all_prices)
        self.user_updated_data = copy.deepcopy(all_prices)
        self.operation = operation

        print(json.dumps(self.updated_data, indent=2))

        # self.overrideredirect(True)
        self.overrideredirect(False)  # Verwenden Sie False, um die Standarddekoration zu aktivieren
        self.attributes('-topmost', True)
        self.resizable(True, True)  # Optional: Erlaubt das Ändern der Fenstergröße

        # Erstelle ein temporäres Fenster, um Bildschirmabmessungen zu erhalten
        self.screen_width, self.screen_height = self.get_primary_monitor_resolution()


        # Create the main content frame
        self.content_frame = tk.Frame(self)
        self.content_frame.pack(fill=tk.BOTH, expand=True)
       
        style = ttk.Style(self)
        style.configure("Treeview", font=('Helvetica', 12))
        style.configure("Treeview.Heading", background="gray", font=('Helvetica', 14, 'bold'))

        # Create the screenshot frame
        self.screenshot_frame = tk.Frame(self)
                
        # Load the location image
        location = ImageTk.PhotoImage(cropped_screenshot_location_pil)

        # Display the screenshot in the screenshot frame
        screenshot_label = tk.Label(self.screenshot_frame, image=location)
        screenshot_label.image = location
        screenshot_label.pack(fill=tk.BOTH, expand=True)
        
        # Convert cv2 image to PIL Image
        prices_screen = Image.fromarray(cropped_screenshot_prices)

        # Load the screenshot image
        prices = ImageTk.PhotoImage(prices_screen)

        # Display the screenshot in the screenshot frame
        screenshot_label = tk.Label(self.screenshot_frame, image=prices)
        screenshot_label.image = prices
        screenshot_label.pack(fill=tk.BOTH, expand=True)

        # Create the data table
        self.data_label = tk.Label(self.content_frame)
        self.data_label.pack(pady=10)

        # Erstellen des Frames für die Textfelder
        textfield_frame = tk.Frame(self.data_label)
        textfield_frame.pack(side=tk.TOP, fill=tk.X)

        # Label "Operation: "
        at_label = tk.Label(textfield_frame, text="Operation: ", font=("Helvetica", 14, "bold"))
        at_label.pack(side=tk.LEFT, padx=5)
        
        # Textfeld für die Operation
        self.operation_entry = tk.Entry(textfield_frame, font=("Helvetica", 14, "bold"), width=10)
        self.operation_entry.insert(0, operation)
        self.adjust_entry_width(self.operation_entry)
        self.operation_entry.configure(state='readonly')
        self.operation_entry.pack(side=tk.LEFT, padx=10, pady=10)

        # Event-Bindings für das Operation-Entry-Widget
        self.operation_entry.bind("<Button-1>", self.toggle_operation)

        # Label "at"
        at_label = tk.Label(textfield_frame, text="at", font=("Helvetica", 14, "bold"))
        at_label.pack(side=tk.LEFT, padx=5)

        # Textfeld für den Handelsportnamen
        self.tradeport_entry = tk.Entry(textfield_frame, font=("Helvetica", 14, "bold"))
        self.tradeport_entry.insert(0, validated_tradeport['name'])
        self.adjust_entry_width(self.tradeport_entry)
        self.tradeport_entry.pack(side=tk.LEFT, padx=10, pady=10)

         # Event-Bindings für das Tradeport-Entry-Widget
        self.tradeport_entry.bind("<Return>", self.tradeport_update)
        self.tradeport_entry.bind("<FocusOut>", self.tradeport_update)
        self.tradeport_entry.bind('<Escape>', self.revert_tradeport)

        self.data_table = ttk.Treeview(self.content_frame, columns=['Transmit', 'Commodity Name', 'Code', 'Inventory SCU', 'Inventory State', 'Price per Unit', 'Multiplier', 'Validation Info'], show='headings')
        
        for col in self.data_table['columns']:
            self.data_table.heading(col, text=col)    

        self.data_table.column("Transmit", width=100)

        self.screenshot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        for index, item in enumerate(self.updated_data):
            # price_with_currency = f"{item['price_per_unit']:.2f}"
            price_with_currency = f"{item['price_per_unit']}" # do not cut off, to be able to see the exact price
            item["transmit"] = True
            checkbox_value = 'Yes'
            row = (
                checkbox_value,
                item['commodity_name'],
                item['code'],
                item['available_SCU_quantity'],
                item['inventory_state'],
                price_with_currency,
                item.get('multiplier', ''),
                item.get('validation_result', '')
            )
            self.data_table.insert('', tk.END, values=row, iid=str(index))  # Assign ID here

        self.data_table.pack(fill=tk.BOTH, expand=True)

        # Titel für das Fenster setzen, um Drag-and-Drop zu ermöglichen
        self.title("Data-Runner Validation")

        # Center the popup horizontally
        self.update()  # Update window to get size
        self.geometry(f"+{(self.screen_width - self.winfo_width()) // 2}+0")

        self.setup_treeview_for_editing()

        self.protocol("WM_DELETE_WINDOW", self.abort_process)

        # Create the data table
        self.usage_label = tk.Label(self, text=(
            "Usage:"
        ), font=("Helvetica", 12, "italic bold"), anchor="w", justify="left")
        self.usage_label.pack(pady=10, anchor="w")

        # Create the data table
        self.data_label = tk.Label(self, text=(
            "Click on operation to change.\n"
            "Correct tradeport name and press 'enter', 'esc' to cancel.\n "
            "After edit of any text field, clicking on other field will save changes.\n"
            "\nCommodities:\n"
            "Click on 'Transmit' to toggle transmit to uex of commodity info\n"
            "Double-Click on any other value to update. 'enter' to save or 'esc' to cancel." 
        ), font=("Helvetica", 12, "italic"), anchor="w", justify="left")
        self.data_label.pack(pady=10, anchor="w")

        # Buttons
        button_frame = tk.Frame(self)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, anchor='center')

        # Erstellen des "Confirm"-Buttons mit grünem Hintergrund
        
        confirm_button = tk.Button(button_frame, text="Confirm Changes", bg="green", fg="white", font=("Helvetica", 16, "bold"), width=15, height=2, command=self.process_data)
        confirm_button.pack(side=tk.LEFT, padx=10, pady=10)

        # Erstellen des "Abort"-Buttons mit rotem Hintergrund
        abort_button = tk.Button(button_frame, text="Abort", bg="red", fg="white", font=("Helvetica", 16, "bold"), width=15, height=2, command=self.abort_process)
        abort_button.pack(side=tk.LEFT, padx=10, pady=10)


    @staticmethod
    def show_data_validation_popup(validated_tradeport, operation, all_prices, cropped_screenshot, location_name_screen_crop):
        root = WingmanUI.get_instance()
        popup = OverlayPopup(root, validated_tradeport, operation, all_prices, cropped_screenshot, location_name_screen_crop)
        popup.show_popup()

        # Wait for the popup to close
        popup.wait_window()

        # Retrieve updated data after the popup is closed
        return popup.get_updated_data()
        
    def show_popup(self):
    
        # Open the popup
        self.update()
        self.deiconify()

    def abort_process(self):
        self.user_updated_data = "aborted"
        self.destroy()
    
    def process_data(self):
        self.user_updated_data = [data for data in self.updated_data if data.get('transmit', True)]
        self.destroy()

    # def collect_updated_data(self):
    #     updated_data = []
    #     for item in self.data_table.get_children():
    #         row_data = self.data_table.item(item, 'values')
    #         updated_data.append(row_data)
    #     return updated_data
    
    def get_updated_data(self):
        # Method to retrieve the updated data after the window is closed
        return self.user_updated_data
    
    def get_primary_monitor_resolution(self):
        monitors = get_monitors()
        if monitors:
            primary_monitor = monitors[0]  # Erster Monitor in der Liste
            return primary_monitor.width, primary_monitor.height
        else:
            return None
        
    def setup_treeview_for_editing(self):
        self.data_table.bind('<Double-1>', self.on_double_click)  # Bind double click
        self.data_table.bind('<ButtonRelease-1>', self.on_table_click) # single click

    def on_double_click(self, event):
        # Get the item clicked
        item = self.data_table.identify('item', event.x, event.y)
        column = self.data_table.identify_column(event.x)
        self.edit_item(item, column)

    def on_table_click(self, event):
        region = self.data_table.identify("region", event.x, event.y)
        if region == "cell":
            row_id = self.data_table.identify_row(event.y)
            column = self.data_table.identify_column(event.x)
            if self.data_table.heading(column)["text"] == "Transmit":
                self.toggle_checkbox(row_id)
    
    def tradeport_update(self, event=None):
        updated_tradeport_name = self.tradeport_entry.get()
        
        if len(updated_tradeport_name) == 0:
            # revert
            self.revert_tradeport(event)

        if updated_tradeport_name == self.current_tradeport["name"]:
            return
        
        matched_tradeport, success = LocationNameMatching.validate_tradeport_name(updated_tradeport_name)
        
        if success is False:
            matched_tradeport = {"name": "unknown"}

        self.current_tradeport = matched_tradeport
        # Entfernen des aktuellen Inhalts im Entry-Widget
        self.tradeport_entry.delete(0, tk.END)
        # Einfügen des neuen Textes in das Entry-Widget
        self.tradeport_entry.insert(0, matched_tradeport["name"])

        self.adjust_entry_width(self.tradeport_entry)
        self.tradeport_entry.update()  # Update  

    def revert_tradeport(self, event=None):
        self.tradeport_entry.delete(0, tk.END)
        # Einfügen des neuen Textes in das Entry-Widget
        self.tradeport_entry.insert(0, self.current_tradeport["name"])
        self.adjust_entry_width(self.tradeport_entry)
        self.tradeport_entry.update()  # Update  

    def adjust_entry_width(self, entry):
        text_length = len(entry.get())
        entry.config(width=(text_length + 1) if text_length > 0 else 1)

    def toggle_operation(self, event=None):

        self.operation_entry.configure(state='normal')
        current_operation = self.operation_entry.get()
        if current_operation.lower() == "buy":
            self.operation_entry.delete(0, tk.END)
            self.operation_entry.insert(0, "Sell")
        else:
            self.operation_entry.delete(0, tk.END)
            self.operation_entry.insert(0, "Buy")

        self.operation_entry.configure(state='readonly')

        # Aktualisieren der Operation-Variable
        self.operation = self.operation_entry.get()

    def toggle_checkbox(self, row_id):
        item = self.data_table.item(row_id)
        checkbox_value = item['values'][0]
        new_value = 'No' if checkbox_value == 'Yes' else 'Yes'
        item['values'][0] = new_value
        self.data_table.item(row_id, values=item['values'])

        # Aktualisieren des 'transmit'-Werts in self.updated_data
        index = int(row_id)
        self.updated_data[index]['transmit'] = (new_value == 'Yes')

    def edit_item(self, item, column):
        # Get the bounds and value of the cell to edit
        x, y, width, height = self.data_table.bbox(item, column)
        
        # column gibt '#n' zurück, wobei 'n' die Spaltennummer ist (beginnend mit 1)
        # Entferne das '#' und subtrahiere 1, um den korrekten Index zu erhalten
        column_index = int(column.strip('#')) - 1
        value = self.data_table.item(item, 'values')[column_index]

        # Create an entry widget for editing
        entry = tk.Entry(self.data_table)
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, value)
        entry.focus()
        entry.bind('<Return>', lambda e: self.save_edit(item, column_index, entry))
        entry.bind('<Escape>', lambda e: entry.destroy())
        entry.bind('<FocusOut>', lambda e: self.save_edit(item, column_index, entry))
    
    def save_edit(self, item, column_index, entry_widget):
        new_value = entry_widget.get()
        
        # Update the item with the new value
        row_index = int(item)  # Convert the row ID back to an integer
        table_values = list(self.data_table.item(item, 'values'))
        table_values[column_index] = new_value
        
        # Map Treeview column names to updated_data keys
        column_mapping = {
            1: "commodity_name",
            2: "code",
            3: "inventory_SCU_quantity",
            4: "inventory_state",
            5: "price_per_unit",
            6: "multiplier",
            7: "validation_result"
        }

        column_key = column_mapping.get(column_index)

        if column_key:
            # Update the corresponding item in updated_data
            self.updated_data[row_index][column_key] = new_value
            self.updated_data[row_index]["validation_result"] = "user updated"
            table_values[7] = "user updated" # index of the validation result collumn...

            if column_key == "price_per_unit":
                unit_price = new_value
                multiplier = self.updated_data[row_index]["multiplier"]
                if multiplier and multiplier.lower()[0] == "m":
                    unit_price = unit_price * 1000000
                
                if multiplier and multiplier.lower()[0] == "k":
                    unit_price = unit_price * 1000

                self.updated_data[row_index]['uex_price'] = unit_price

            if column_key == "multiplier":
                multiplier = new_value
                unit_price = self.updated_data[row_index]["price_per_unit"]
                if multiplier and multiplier.lower()[0] == "m":
                    unit_price = unit_price * 1000000
                
                if multiplier and multiplier.lower()[0] == "k":
                    unit_price = unit_price * 1000

                self.updated_data[row_index]['uex_price'] = unit_price

            if column_key == "commodity_name":
                commodity_name = new_value
                validated_commodity_key, validated_commodity, success = CommodityPriceValidator.validate_commodity_name(commodity_name, self.current_tradeport)
                if not success:
                    self.updated_data[row_index]["validation_result"] = "commodity not found"
                    table_values[6] = "commodity not found"
                    return
                
                self.updated_data[row_index]['commodity_name'] = validated_commodity["name"]
                table_values[0] = validated_commodity["name"]
                self.updated_data[row_index]['code'] = validated_commodity_key
                table_values[1] = validated_commodity_key
                unit_price = self.updated_data[row_index]["price_per_unit"]
                multiplier = self.updated_data[row_index]["multiplier"]
                if multiplier and multiplier.lower()[0] == "m":
                    unit_price = unit_price * 1000000
                
                if multiplier and multiplier.lower()[0] == "k":
                    unit_price = unit_price * 1000

                self.updated_data[row_index]['uex_price'] = unit_price

        #self.data_table.item(item, )
        self.data_table.item(item, values=table_values)
        self.update()  # Update window to get size  

        entry_widget.destroy()
                