class DeliveryMissionAction:
    """
    Bidirectional ordered linked hash map entry representing a delivery mission action.
    """

    def __init__(self, location_ref=None, package_id=None, mission_ref=None, 
                 action=None, buy=False, sell=False, commodity_code=None, 
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
        self.location_ref = location_ref  ## we need the ref, because derelict outposts cannot be found in the uex_api
        self.mission_ref = mission_ref
        self.package_id = package_id
        self.action = action  # pickup | dropoff
        self.buy = buy
        self.sell = sell
        self.commodity_code = commodity_code  # commodity information for this action
        self.partner_action = partner_action  # direct reference to this package partner action (dropoff or pickup action)
        self.state = state  # state of this action: TODO | DONE
        self.action_priority = action_priority
        self.danger = False  # if outlaw and or armistice 

        from wingmen.star_citizen_services.model.mission_package import MissionPackage
        self.mission_package: MissionPackage

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
    
    def __iter__(self):
        return DeliveryMissionIterator(self)

    def reverse_iter(self):
        return DeliveryMissionIterator(self, reverse=True)
    
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
    
class DeliveryMissionIterator:
    def __init__(self, start_action, reverse=False):
        """
        Initialize the iterator.
        
        :param start_action: The starting action for the iteration.
        :param reverse: Flag to indicate reverse iteration.

        HowTo:
            # Assuming head_action is the first action in your linked list
            head_action = DeliveryMissionAction(...)  # Initialize with appropriate parameters

            # Forward iteration
            for action in head_action:
                print(action.action, action.location_id)

            # Reverse iteration
            for action in head_action.reverse_iter():
                print(action.action, action.location_id)
        """
        self.current_action = start_action
        self.reverse = reverse

    def __iter__(self):
        return self

    def __next__(self):
        if self.current_action is None:
            raise StopIteration
        current = self.current_action
        self.current_action = self.current_action.previous_action if self.reverse else self.current_action.next_action
        return current