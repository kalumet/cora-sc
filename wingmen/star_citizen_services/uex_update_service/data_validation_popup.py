import copy
import tkinter as tk
from tkinter import ttk
from tkinter.ttk import Style
import json

from threading import Thread
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageColor
from screeninfo import get_monitors

from gui.root import WingmanUI 

from wingmen.star_citizen_services.uex_update_service.commodity_price_validator import CommodityPriceValidator


class OverlayPopup(tk.Toplevel):
    def __init__(self, master, validated_tradeport, operation, all_prices, cropped_screenshot_prices, cropped_screenshot_location_pil):
        super().__init__(master)
        
        self.current_tradeport = validated_tradeport
        self.updated_data = copy.deepcopy(all_prices)
        self.user_updated_data = all_prices

        print(json.dumps(self.updated_data, indent=2))

        self.overrideredirect(True)
        self.attributes('-topmost', True)

        # Erstelle ein temporäres Fenster, um Bildschirmabmessungen zu erhalten
        self.screen_width, self.screen_height = self.get_primary_monitor_resolution()

        # Create the main content frame
        self.content_frame = tk.Frame(self)
        self.content_frame.pack(fill=tk.BOTH, expand=True)

        # Create the screenshot frame
        self.screenshot_frame = tk.Frame(self)
        self.screenshot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
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
        self.data_label = tk.Label(self.content_frame, text=f"Data Validation for {operation}able commodities at '{validated_tradeport['name']}'")
        self.data_label.pack(pady=10)

        self.data_table = ttk.Treeview(self.content_frame, columns=['Commodity Name', 'Code', 'Inventory SCU Quantity', 'Inventory State', 'Price per Unit', 'Multiplier', 'Validation Info'], show='headings')
        for col in self.data_table['columns']:
            self.data_table.heading(col, text=col)
        
        # # Define the styling for validated and rejected data
        # style = Style()
        # style.configure("Rejected.Foreground", foreground="red")
        # style.configure("Validated.Foreground", foreground="green")

        # # Set the styling for validated and rejected data based on the data
        # for row in self.updated_data:
        #     if row in rejected_data:
        #         self.data_table.insert('', tk.END, values=row, tags=('Rejected.Foreground',))
        #     else:
        #         self.data_table.insert('', tk.END, values=row, tags=('Validated.Foreground',))

        # # Define custom styling for the price column to display currency symbols
        # style.configure('Treeview.cell', font=('Arial', 11))
        # style.configure('Treeview.heading', font=('Arial', 12, 'bold'))

        # # Apply custom styling to the price column
        # self.data_table.heading('Price', text='Price', command=lambda: self.data_table.column('Price', width=self.data_table.column('Price').width*2))
        # self.data_table.column('Price', width=100)
        # format_str = '%.2f'
        # self.data_table.tag_configure('currency', foreground='black', font=('Arial', 11, 'bold'))

        for index, item in enumerate(self.updated_data):
            price_with_currency = f"{item['price_per_unit']:.2f}"
            row = (
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

        # Center the popup horizontally
        self.update()  # Update window to get size
        self.geometry(f"+{(self.screen_width - self.winfo_width()) // 2}+0")

        self.setup_treeview_for_editing()

        # Close button
        close_button = tk.Button(self, text="Confirm Changes", command=self.process_data)
        close_button.pack()

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

        # Close the popup when the user presses the button
        close_button = tk.Button(self, text="No changes and continue", command=self.destroy)
        close_button.pack()

    def process_data(self):
        # Logic to collect updated data from the user interface
        self.user_updated_data = self.updated_data
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

    def on_double_click(self, event):
        # Get the item clicked
        item = self.data_table.identify('item', event.x, event.y)
        column = self.data_table.identify_column(event.x)
        self.edit_item(item, column)

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
        entry.bind('<Return>', lambda e: self.save_edit(item, column_index, entry.get()))
        entry.bind('<Escape>', lambda e: entry.destroy())

    def save_edit(self, item, column_index, new_value):
        # Update the item with the new value
        row_index = int(item)  # Convert the row ID back to an integer
        table_values = list(self.data_table.item(item, 'values'))
        table_values[column_index] = new_value
        

        # Map Treeview column names to updated_data keys
        column_mapping = {
            0: "commodity_name",
            1: "code",
            2: "inventory_SCU_quantity",
            3: "inventory_state",
            4: "price_per_unit",
            5: "multiplier",
            6: "validation_result"
        }

        column_key = column_mapping.get(column_index)

        if column_key:
            # Update the corresponding item in updated_data
            self.updated_data[row_index][column_key] = new_value
            self.updated_data[row_index]["validation_result"] = "user updated"
            table_values[6] = "user updated"

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

        self.data_table.item(item, values=table_values)
        self.update()  # Update window to get size  
                