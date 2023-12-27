class DeliveryMissionAction:

    def __init__(self, index=None, location_ref=None, package_id=None, mission_ref=None, 
                 action=None, buy=False, sell=False, buy_commodity_code=None, sell_commodity_code=None, 
                 partner_action=None, state="TODO", action_priority=0):
        """
        Initialize a new DeliveryMissionAction object.

        :param positionIndex: The current position of this action in our ordered map.
        :param location_ref: Reference to the location.
        :param package_id: Identifier for the package.
        :param mission_ref: Reference to the mission.
        :param action: The type of action (pickup | dropoff).
        :param buy: Flag indicating if this action involves buying.
        :param sell: Flag indicating if this action involves selling.
        :param commodity_code: Commodity information for this action.
        :param partner_action: Direct reference to this package's partner action (dropoff or pickup action).
        :param state: State of this action (TODO | DONE).
        """
        self.index = None  # will be the index in the list of the delivery route
        self.location_ref = location_ref  ## we need the ref, because derelict outposts cannot be found in the uex_api
        self.mission_ref = mission_ref
        self.package_id = package_id
        self.action = action  # pickup | dropoff
        self.buy = buy
        self.sell = sell
        self.buy_commodity_code = buy_commodity_code  # commodity information for this action
        self.sell_commodity_code = sell_commodity_code  # commodity information for this action
        self.partner_action = partner_action  # direct reference to this package partner action (dropoff or pickup action) 
        self.state = state  # state of this action: TODO | DONE
        self.action_priority = action_priority
        self.danger = False  # if outlaw and or armistice 

        # from wingmen.star_citizen_services.model.mission_package import MissionPackage
        # self.mission_package: MissionPackage

    def reduce_priority_if_required(self, compare_action):  
        """
        Reduziere die Priorität dieser Aktion basierend auf der zuletzt durchgeführten Aktion.
        """
        if self == compare_action:
            return  # we do not change the priority based our self
        if self.location_ref["code"] == compare_action.location_ref["code"]:
            self.action_priority -= 3
        elif (self.location_ref['planet'] == compare_action.location_ref['planet'] or 
                self.location_ref['satellite'] == compare_action.location_ref['satellite']):
            self.action_priority -= 1
    
    def increase_priority_if_required(self, compare_action):  
        """
        Aktualisiere die Priorität dieser Aktion basierend auf der zuletzt durchgeführten Aktion.
        """
        if self == compare_action:
            return  # we do not change the priority based our self
        if self.location_ref["code"] == compare_action.location_ref["code"]:
            self.action_priority += 3
        elif (self.location_ref['planet'] == compare_action.location_ref['planet'] or 
                self.location_ref['satellite'] == compare_action.location_ref['satellite']):
            self.action_priority += 1

    def __repr__(self):
        location_name = self.location_ref['satellite']
        if not location_name:
            location_name = self.location_ref['planet']
        return (f"action({self.package_id}.{self.action}({self.action_priority})) -> {self.location_ref['code']} ({location_name})")

    def __str__(self):
        location_name = self.location_ref['satellite']
        if not location_name:
            location_name = self.location_ref['planet']
        return (f"action({self.package_id}.{self.action}({self.action_priority})) -> {self.location_ref['code']} ({location_name})")
    
    def __lt__(self, other):
        """
        Vergleiche zwei Aktionen basierend auf ihrer Priorität.
        """
        return self.action_priority > other.action_priority
    
    def __eq__(self, other):
        if not isinstance(other, DeliveryMissionAction):
            return False
        
        if self.package_id != other.package_id:
            return False
        
        if self.action != other.action:
            return False
        
        if self.mission_ref.id != other.mission_ref.id:
            return False
        
        return True

    def __hash__(self):
        hash_str = "_".join([str(self.mission_ref.id), str(self.package_id), str(self.action)])
        return hash(hash_str)
    
    def to_GPT_json(self): 
        from wingmen.star_citizen_services.uex_api import UEXApi
        uex_api = UEXApi()

        satellites = uex_api.get_data("satellites")
        planets = uex_api.get_data("planets")
        cities = uex_api.get_data("cities")
        commodities = uex_api.get_data("commodities")
        tradeports = uex_api.get_tradeports()

        tradeport = self.location_ref["code"]
        satellite = self.location_ref["satellite"]
        planet = self.location_ref["planet"]
        city = self.location_ref["city"]
        
        tradeport_json = f'"tradeport": {tradeports.get(tradeport,{}).get("name", tradeport)},'
        
        location_json = ""
        if satellite:
            location_json = f'"satellite": {satellites.get(satellite,{}).get("name", satellite)},'
        elif city:
            location_json = (
                f'"planet": {planets.get(planet, {}).get("name", planet)},\n'
                f'"city": {cities.get(city, {}).get("name", city)},'
            )
        else:
            location_json = f'"planet": {planets.get(planet, {}).get("name", planet)},'
 
        buy_json = ""
        buy_commodity = ""
        if self.buy:
            buy_json = f'"buy": {self.buy},'
            buy_commodity = f'"buy_commodity": {commodities.get(self.buy_commodity_code, {}).get("name", self.buy_commodity_code)},'  # commodity information for this action

        sell_json = ""
        sell_commodity = ""
        if self.sell:
            sell_json = f'"buy": {self.sell},'
            sell_commodity = f'"sell_commodity": {commodities.get(self.sell_commodity_code, {}).get("name", self.sell_commodity_code)},'  # commodity information for this action

        return {
            f'"mission_id" : {self.mission_ref.id}'
            f"{tradeport_json}"  # we need the ref, because derelict outposts cannot be found in the uex_api
            f"{location_json}"
            "package_id": self.package_id,
            "action": self.action,  # pickup | dropoff
            f"{buy_json}"
            f"{sell_json}"
            f"{buy_commodity}"
            f"{sell_commodity}"
            "danger": self.danger,  # if outlaw and or armistice 
        }

    def to_json(self):
        
        return {
            "index": self.index,
            "location_ref": self.location_ref,  # we need the ref, because derelict outposts cannot be found in the uex_api
            "mission_ref": self.mission_ref.id,  # we need only the id to identify the mission
            "package_id": self.package_id,
            "action": self.action,  # pickup | dropoff
            "buy": self.buy,
            "sell": self.sell,
            "buy_commodity_code": self.buy_commodity_code,  # commodity information for this action
            "sell_commodity_code": self.sell_commodity_code,  # commodity information for this action
            "partner_action": self.partner_action.index,  # we cannot save the reference, so we only save the index of the partner within route (list of mission action)
            "state": self.state, # state of this action: TODO | DONE
            "action_priority": self.action_priority,
            "danger": self.danger,  # if outlaw and or armistice 
        }
    
    @staticmethod
    def from_json(missions, delivery_action_json, index):
        action: DeliveryMissionAction = DeliveryMissionAction()
        action.index = index  # will be the index in the list of the delivery route
        action.location_ref = delivery_action_json["location_ref"]  ## we need the ref, because derelict outposts cannot be found in the uex_api
        action.mission_ref = missions[delivery_action_json["mission_ref"]]
        action.package_id = delivery_action_json["package_id"]
        action.action = delivery_action_json["action"]  # pickup | dropoff
        action.buy = delivery_action_json["buy"]
        action.sell = delivery_action_json["sell"]
        action.buy_commodity_code = delivery_action_json["buy_commodity_code"]  # commodity information for this action
        action.sell_commodity_code = delivery_action_json["sell_commodity_code"]  # commodity information for this action
        action.partner_action = delivery_action_json["partner_action"]  # direct reference to this package partner action (dropoff or pickup action)
        action.state = delivery_action_json["state"]  # state of this action: TODO | DONE
        action.action_priority = delivery_action_json["action_priority"]
        action.danger = delivery_action_json["danger"]  # if outlaw and or armistice 

        return action

