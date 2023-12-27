import json
import os
import traceback
from tkinter import Tk, Label, Toplevel
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageColor
import pygetwindow as gw

from gui.root import WingmanUI
from wingmen.star_citizen_services.model.delivery_mission import DeliveryMission, MissionPackage
from wingmen.star_citizen_services.screenshot_ocr import TransportMissionAnalyzer
from wingmen.star_citizen_services.delivery_manager import PackageDeliveryPlanner, DeliveryMissionAction


DEBUG = True


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class MissionManager:
    """ maintains a set of all missions and provides functionality to manage this set
    
        missions: dict(mission id, DeliveryMission)
        pickup_locations: dict(location_code, mission id)
        drop_off_locations: dict(location_code, mission id)
    
    """
    def __init__(self, config=None):
        self.missions: dict(int, DeliveryMission) = {}
        self.delivery_actions: list(DeliveryMissionAction) = []

        self.config = config
        self.mission_data_path = f'{self.config["data-root-directory"]}{self.config["box-mission-configs"]["mission-data-dir"]}'
        self.missions_file_path = f'{self.mission_data_path}/active-missions.json'
        self.delivery_route_file_path = f'{self.mission_data_path}/active-delivery-route.json'
        self.mission_screen_upper_left_template = f'{self.mission_data_path}/{self.config["box-mission-configs"]["upper-left-region-template"]}'
        self.mission_screen_lower_right_template = f'{self.mission_data_path}/{self.config["box-mission-configs"]["lower-right-region-template"]}'

        self.delivery_manager = PackageDeliveryPlanner()
        self.mission_recognition_service = TransportMissionAnalyzer(
            upper_left_template=self.mission_screen_upper_left_template, 
            lower_right_template=self.mission_screen_lower_right_template, 
            data_dir_path=self.mission_data_path
            )
        
        # we always load from file, as we might restart wingmen.ai indipendently from star citizen
        # TODO need to check on start, if we want to discard this mission
        self.load_missions()
        self.load_delivery_route()

        index = 0
        for index, action in enumerate(self.delivery_actions):
            action: DeliveryMissionAction
            if action.state == "DONE":
                continue
            if action.state == "TODO":
                break
        self.current_delivery_action_index = index
           
    def manage_missions(self, type="new", mission_id=None):
        if type == "new":
            return self.get_new_mission()
        if type == "delete_all":
            return self.discard_all_missions()
        if type == "delete_mission_id":
            return self.discard_mission(mission_id)
        if type == "next_location":
            return self.get_next_location()
    
    def get_next_location(self):
        
        if len(self.delivery_actions) == 0:
            return {"success": "False", 
                "instructions": "There are no delivery missions active"}
            
        if self.current_delivery_action_index < len(self.delivery_actions):
            self.delivery_actions[self.current_delivery_action_index].state = "DONE"
            
            self.current_delivery_action_index += 1
            if self.current_delivery_action_index == len(self.delivery_actions):
                self.discard_all_missions()
                return {"success": "False", 
                "instructions": "The player has completed all delivery missions. No active missions available."}
            
            self.save_delivery_route()

            next_action: DeliveryMissionAction = self.delivery_actions[self.current_delivery_action_index]
            return {"success": "True", 
                "instructions": "Indicate the mission ID that is related to the next action. Whenever you provide a specific package ID, detail its ID by separating each digit with a space. Inform about the pickup location and the corresponding satellite. Conclude with a cautionary note about potential dangers at the location, such as piracy or other risks, if any. Be creativ how to provide these informations, but make short answers. Most important is the Location Name and the package id.",
                "next_location": json.dumps(next_action.to_GPT_json())}
        else:
            self.discard_all_missions()
            return {"success": "False", 
                "instructions": "The player has completed all delivery missions. No active missions available."}
            
    def get_mission_ids(self):
        return [mission for mission in self.missions.keys()]
    
    def get_new_mission(self):
        delivery_mission: DeliveryMission = self.mission_recognition_service.identify_mission()
        self.missions[delivery_mission.id] = delivery_mission
        print_debug(delivery_mission.to_json())
        
        self.calculate_missions()

        self.display_overlay_text(
            f"New Mission #{delivery_mission.id}:   "
            f"{delivery_mission.revenue} αUEC   "
            f"packages: {len(delivery_mission.packages)}"
        )

        # 3 return new mission and active missions + instructions for ai
        return {"success": "True", 
                "instructions": "Announce the addition of a new mission by stating its ID. Specify the expected revenue in alpha UEC by writing out the number. Indicate, that you have calculated the best delivery route. Whenever you provide a specific package ID, detail its ID by separating each digit with a space. Inform about the pickup location and the corresponding satellite. Conclude with a cautionary note about potential dangers at the location, such as piracy or other risks, if any. Be creativ how to provide these informations, but make short answers. Most important is the Location Name and the package id.",
                "missions_count": len(self.missions),
                "new_mission": json.dumps(delivery_mission.to_json()),
                "first_location": json.dumps(self.delivery_actions[0].to_GPT_json())}

    def calculate_missions(self):
        self.delivery_actions = self.delivery_manager.calculate_delivery_route(self.missions)
         
        # CargoRoutePlanner.finde_routes_for_delivery_missions(ordered_delivery_locations, tradeports_data)
			
        # Save the missions to a JSON file
        self.save_missions()
        self.save_delivery_route()
        self.current_delivery_action_index = 0
       
    def discard_mission(self, mission_id):
        """Discard a specific mission by its ID."""
        self.missions.pop(mission_id, None)
        
        self.calculate_missions()

        self.display_overlay_text(
            f"Discarded Mission #{mission_id}"
        )
        
        return {"success": "True", 
                "instructions": "Announce the removal of the given mission. Indicate, that you have recalculated the best delivery route. Whenever you provide a specific package ID, detail its ID by separating each digit with a space. Inform about the pickup location and the corresponding satellite. Conclude with a cautionary note about potential dangers at the location, such as piracy or other risks, if any. Be creativ how to provide these informations, but make short answers. Most important is the Location Name and the package id.",
                "missions_count": len(self.missions),
                "deleted_mission_id": mission_id,
                "first_location": json.dumps(self.delivery_actions[0].to_GPT_json())}

    def discard_all_missions(self):
        """Discard all missions."""
        number = len(self.missions)
        self.missions.clear()
        self.delivery_actions.clear()

        self.save_missions()
        self.save_delivery_route()
        self.current_delivery_action_index = 0

        return {"success": "True", 
                "instructions": "Provide only the following information: Acknowledge the deletion of the number of missions. Any numbers in your response must be written out. Do not provide any further information.",
                "delete_missions_count": number }

    def save_missions(self):
        """Save mission data to a file."""
        filename = self.missions_file_path
        with open(filename, 'w') as file:
            missions_data = {}
            for mission_id, mission in self.missions.items():
                mission_dict = mission.to_dict()
                
                # mission_dict = mission.__dict__.copy()
                mission_dict['packages'] = list(mission_dict['packages'])  # Convert set to list

                # Convert pickup and drop-off locations to a serializable format if needed
                # Depending on how they are stored, you might need similar conversion
                
                missions_data[mission_id] = mission_dict
            json.dump(missions_data, file, indent=3)

    def load_missions(self):
        """Load mission data from a file."""
        filename = self.missions_file_path
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as file:
                    data = json.load(file)
                    for mid, mission_data in data.items():
                        mission = DeliveryMission()

                        # Grundlegende Attribute aktualisieren
                        mission.id = mission_data['id']
                        mission.revenue = mission_data['revenue']

                        # Sets und Listen rekonstruieren
                        mission.packages = set(mission_data['packages'])
                        
                        # Dictionaries für pickup und drop-off locations rekonstruieren
                        mission.pickup_locations = {int(k): v for k, v in mission_data['pickup_locations'].items()}
                        mission.drop_off_locations = {int(k): v for k, v in mission_data['drop_off_locations'].items()}

                        # MissionPackages für jede package_id erstellen
                        for package_id in mission.packages:
                            mission_package = MissionPackage()
                            mission_package.mission_id = mission.id
                            mission_package.package_id = package_id
                            mission_package.pickup_location_ref = mission.pickup_locations.get(package_id)
                            mission_package.drop_off_location_ref = mission.drop_off_locations.get(package_id)
                            mission.mission_packages.append(mission_package)

                        self.missions[mission.id] = mission  
        except Exception as e:
            print(f"Error loading missions: {e}")
            traceback.print_exc()

    def save_delivery_route(self):
        """Save mission data to a file."""
        filename = self.delivery_route_file_path
        with open(filename, 'w') as file:
            delivery_route_data = []
            for delivery_action in self.delivery_actions:
                delivery_action: DeliveryMissionAction
                deliver_json = delivery_action.to_json()
                delivery_route_data.append(deliver_json)
                
            json.dump(delivery_route_data, file, indent=3)

    def load_delivery_route(self):
        """Load delivery route data from a file."""
        filename = self.delivery_route_file_path
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as file:
                    data = json.load(file)
                    for index, action_json in enumerate(data):
                        action = DeliveryMissionAction.from_json(self.missions, action_json, index)                   
                        
                        if isinstance(action.mission_ref, int):
                            action.mission_ref = self.missions[action.mission_ref] # we stored only the id of the mission, so now we recover the reference                    
                        self.delivery_actions.append(action)
                    
                    # we need to reiterate to build the partner-relation
                    for action in self.delivery_actions:
                        me: DeliveryMissionAction = action
                        if isinstance(me.partner_action, int):  # we only need to set, if we haven't already replaced the index by the reference
                            partner: DeliveryMissionAction = self.delivery_actions[me.partner_action]  # we have the index currently saved, so we can access the partner directly

                            me.partner_action = partner
                            partner.partner_action = me

        except Exception:
            traceback.print_exc()

    # def create_text_image(self, text, font_path='arial.ttf', font_size=20, text_color='white', glow_color='grey'):
    #     """Erstellt ein Bild mit Text und Glow-Effekt."""
    #     font = ImageFont.truetype(font_path, font_size)

    #     # Dummy-Image für Textgröße
    #     dummy_image = Image.new('RGB', (1, 1))
    #     draw_dummy = ImageDraw.Draw(dummy_image)
    #     text_width, text_height = int(draw_dummy.textlength(text, font=font)), font_size

    #     # Erstelle ein neues Image mit transparentem Hintergrund
    #     text_image = Image.new('RGBA', (text_width + 20, text_height + 20), (255, 255, 255, 0))
    #     draw = ImageDraw.Draw(text_image)

    #     # Glow-Effekt
    #     x, y = 10, 10
    #     for i in range(1, 5):  # Glow-Intensität
    #         draw.text((x - i, y), text, font=font, fill=(0, 0, 0, 60))  # Links oben
    #         draw.text((x + i, y), text, font=font, fill=(0, 0, 0, 60))  # Rechts oben
    #         draw.text((x, y - i), text, font=font, fill=(0, 0, 0, 60))  # Links unten
    #         draw.text((x, y + i), text, font=font, fill=(0, 0, 0, 60))  # Rechts unten

    #     # Text zeichnen
    #     draw.text((x, y), text, font=font, fill=text_color)

    #     return text_image
    
    def create_glow_text_image(self, text, font_path='arial.ttf', font_size=20, transparent_color="gray", text_color='white', glow_color="black"):
        """Erstellt ein Bild mit Text und Glow-Effekt."""
        # Erstelle ein Font-Objekt
        font = ImageFont.truetype(font_path, font_size)
        
        # Convert color string to RGB values
        glow_color_rgb = ImageColor.getrgb(glow_color)
        glow_color_rgba = (glow_color_rgb[0], glow_color_rgb[1], glow_color_rgb[2], 0)

        # Convert color string to RGB values
        transparent_color_rgb = ImageColor.getrgb(transparent_color)
        transparent_color_rgba = (transparent_color_rgb[0], transparent_color_rgb[1], transparent_color_rgb[2], 0)

        # Convert color string to RGB values
        text_color_rgb = ImageColor.getrgb(text_color)
        text_color_rgba = (text_color_rgb[0], text_color_rgb[1], text_color_rgb[2], 0)


        # Erstelle ein Dummy-Image, um die Textgröße zu bekommen
        dummy_image = Image.new('RGB', (1, 1))
        draw_dummy = ImageDraw.Draw(dummy_image)
        text_width, text_height = int(draw_dummy.textlength(text, font=font)), font_size

        # Erstelle ein neues Image mit transparentem Hintergrund (weiß wird transparent)
        # colored_bg = Image.new('RGBA', (text_width + 2, text_height + 2), transparent_color_rgba)
        text_image = Image.new('RGBA', (text_width + 2, text_height + 2), text_color_rgba)
        
        # find starting coordinates of the text position
        text_x = (text_image.width - text_width) / 2
        text_y = (text_image.height - text_height) / 2
        
        draw = ImageDraw.Draw(text_image)
        
        
        # transparency values of text frames
        transparency_values = [255, 230, 200]

        for i, value in enumerate(transparency_values):
            glow_color_rgba = (glow_color_rgb[0], glow_color_rgb[1], glow_color_rgb[2], value)
            draw.text((text_x, text_y), text, glow_color_rgba, font=font, stroke_width=i, spacing=5)
 
        draw.text((text_x, text_y), text, text_color_rgb, font=font, stroke_width=0, spacing=5)
        return text_image
    
    def close_window(self, root):
        """Schließt das Tkinter-Fenster."""
        root.destroy()

    def display_overlay_text(self, text):
        active_window = gw.getActiveWindow()
        if active_window and 'Wingman AI' in active_window.title:

            def create_overlay():
                transparent_color = "gray"
                overlay_root = Toplevel(WingmanUI.get_instance())
                overlay_root.overrideredirect(True)
                overlay_root.attributes('-topmost', True)
                overlay_root.attributes("-transparentcolor", transparent_color)

                text_image = self.create_glow_text_image(text=text, transparent_color=transparent_color)
                photo = ImageTk.PhotoImage(text_image)

                overlay_root.image = photo

                label = Label(overlay_root, image=photo, bg=transparent_color)
                label.pack()

                overlay_root.geometry("+750+600")

                overlay_root.after(5000, lambda: overlay_root.destroy())

            WingmanUI.enqueue_tkinter_command(create_overlay)

    def __str__(self):
        """Return a string representation of all missions."""
        return "\n".join(str(mission) for mission in self.missions.values())
