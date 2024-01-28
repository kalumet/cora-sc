# from typing import Dict, List
# import copy
import heapq

from wingmen.star_citizen_services.uex_api import UEXApi
from wingmen.star_citizen_services.model.delivery_mission import DeliveryMission
from wingmen.star_citizen_services.model.mission_action import DeliveryMissionAction
from wingmen.star_citizen_services.model.mission_package import MissionPackage


DEBUG = True


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class PackageDeliveryPlanner:
    
    def __init__(self):

        self.debug = False
        self.mission_actions_list = []
        self.uex_service: UEXApi = UEXApi()

    def calculate_delivery_route(self, missions: [DeliveryMission]) -> [DeliveryMissionAction]:
        """
        Sorts package missions to determine the optimal order of locations for package pickup and dropoff.

        Args:
            delivery_missions (List[DeliveryMission]): List of package missions to sort.

        Returns:
            List[LocationPackageManager]: Ordered list of locations for efficient package management.
        """
       
        # Step 1: build a correct, but inefficient action order
        self.mission_actions_list = self.build_delivery_mission_actions(missions)

        if DEBUG:
            print_debug("===DELIVERY ACTIONS===")
            for mission_action in self.mission_actions_list:
                mission_action: DeliveryMissionAction
                print_debug(
                    f"mission: {mission_action.mission_ref.id}, "
                    f"{mission_action}") 

        # Step 2  
        self.prioritize(self.mission_actions_list)

        if DEBUG:
            print_debug("===PRIORITIES===")
            for mission_action in self.mission_actions_list:
                mission_action: DeliveryMissionAction
                print_debug(
                    f"mission: {mission_action.mission_ref.id}, "
                    f"{mission_action}") 

        # Step 3
        self.mission_actions_list =  self.plan_delivery_route(self.mission_actions_list)

        if DEBUG:
            print_debug("===SORTED===")
            for mission_action in self.mission_actions_list:
                mission_action: DeliveryMissionAction
                print_debug(
                    f"mission: {mission_action.mission_ref.id}, "
                    f"{mission_action}")

        return self.mission_actions_list

    def build_delivery_mission_actions(self, delivery_missions: [DeliveryMission]):
        
        actions_list = []
        previous_action = None
        first = None
        last = None

        for delivery_mission in delivery_missions.values():
            delivery_mission: DeliveryMission

            for mission_package in delivery_mission.mission_packages:
                mission_package: MissionPackage
                
                pickup_action = DeliveryMissionAction()
                if not first:
                    first = pickup_action

                if previous_action:
                    previous_action.next_action = pickup_action
                
                dropoff_action = DeliveryMissionAction()

                pickup_action.location_ref = delivery_mission.pickup_locations[mission_package.package_id]
                pickup_action.package_id = mission_package.package_id
                pickup_action.action = "pickup"
                pickup_action.mission_ref = delivery_mission
                pickup_action.partner_action = dropoff_action
                # pickup_action.mission_package = mission_package

                actions_list.append(pickup_action)
                
                previous_action = dropoff_action

                dropoff_action.location_ref = delivery_mission.drop_off_locations[mission_package.package_id]
                dropoff_action.package_id = mission_package.package_id
                dropoff_action.action = "dropoff"
                dropoff_action.mission_ref = delivery_mission
                dropoff_action.partner_action = pickup_action
                # dropoff_action.mission_package = mission_package
                
                actions_list.append(dropoff_action)

                last = dropoff_action
    
        return actions_list

    def plan_delivery_route(self, actions_list):
        """
        Plane die Lieferroute basierend auf den gegebenen Aktionen.
        """
        heapq.heapify(actions_list)
        route = []
        last_action = None
        picked_up_packages = set()
        postponed_dropoffs = []
        index = 0

        print_debug("\n##### PLANNING ROUTE #####")
        while actions_list:
            current_action = heapq.heappop(actions_list)  # entfernt wird die aktion mit der derzeitig höchsten Priorität, in der ersten iteration eine pickup action
            current_location = current_action.location_ref

            # da wir ein paket abgeholt haben, aktualisieren wir jetzt die Prioritäten, da wir, sofern sinnvoll, Pakete auf dem gleichen Mond bevorzugen
            # allerdings wollen wir riskante Orte dadurch nicht zu stark nach hinten schieben, daher ist dieser faktor immer kleiner als gefährliche aktionen
            self.prioritize_remaining_list(actions_list, current_action, last_action)

            last_action = current_action

            print_debug(f"planning action {current_action}")

            # wir dürfen ein paket erst abliefern, wenn es auch schon aufgehoben wurde, was hier geprüft wird
            # manchmal kann es durch die Priorisierung dazu kommen, dass ein paket abgeliefert werden soll, obwohl es noch nicht
            # aufgehoben wurde
            skip = self.add_pickup_or_postpone_drop_off_check(picked_up_packages, current_action, current_location, actions_list)
            if skip:
                print_debug(f"    postponing: {current_action}")
                postponed_dropoffs.append(current_action)  # dropoff action before corresponding pickup
                continue
            
            location_route = []
            location_route.append(current_action)

            # Zusätzliche Schleife, um alle verfügbaren Pakete am aktuellen Ort zu sammeln
            collect_more = True
            while collect_more:
                collect_more = False
                removed_action = None
                # Erstelle eine Kopie der actions_list für die Iteration
                for i, action in enumerate(list(actions_list)):
                    if action.location_ref["code"] == current_action.location_ref["code"] and action.action == 'pickup':
                        print_debug(f"    pickup {action} as on same location.")
                        picked_up_packages.add(action.package_id)
                        
                        # Entferne das gefundene Element aus dem Heap
                        actions_list.pop(i)

                        location_route.append(action)

                        removed_action = action
                        collect_more = True
                        break  
                    
                # wir müssen die "action_list neu initialisieren, da sie jetzt kürzer ist"
                if removed_action:
                    for action in actions_list:
                        action.reduce_priority_if_required(removed_action)
                    removed_action = None

            drop_more = True
            while drop_more:  # check if we can drop packages here independent of priority
                drop_more = False
                for i, action in enumerate(list(actions_list)):
                    if action.location_ref["code"] == current_action.location_ref["code"] and action.action == 'dropoff':
                        print_debug("    found same location for dropoff.")
                        can_drop = self.check_drop_off_at_location(picked_up_packages, action)
                        
                        if can_drop: # Entferne das gefundene Element aus dem Heap
                            actions_list.pop(i)
                            
                            location_route.insert(0, action)  # wenn wir am gleichen Ort pakete abliefern können, bevorzugen wir das als erste aktion, also setzen wir das am anfang

                            removed_action = action
                            drop_more = True
                            break  # wir müssen die "action_list neu initialisieren, da sie jetzt kürzer ist"
                
                if removed_action:
                    for action in actions_list:
                        action.reduce_priority_if_required(removed_action)
                    removed_action = None
                        
            # jetzt müssen wir die aufgebaute liste des ortes in unsere route einbauen und die indizes entsprechen setzen
            for action in location_route:
                action.index = index
                index += 1
                route.append(action)

            if len(postponed_dropoffs) > 0:  # we processed all lists, but we postponed dropoff-actions ...
                retry_delivery = set()
                for action in postponed_dropoffs:
                    # check if a package has been picked up already. if yes, this package can be retried for delivery
                    package_can_be_dropped = self.can_postponed_package_be_retried(picked_up_packages, action, current_location, actions_list)
                    if package_can_be_dropped:
                        retry_delivery.add(action)

                # we remove all retry actions from the postponed actions
                postponed_dropoffs = [action for action in postponed_dropoffs if action not in retry_delivery]

                # we add the retry elements to our action_list
                actions_list.extend(retry_delivery)

                # we have to check if the priorities for all remaining actions need to be increased
                # for every retry element we added to the list
                for action in actions_list:
                    for retry_action in retry_delivery:
                        action.increase_priority_if_required(retry_action)

            #  aktualisiere die priorisierung unseres heaps für die nächste iteration
            heapq.heapify(actions_list)

        return route

    def can_postponed_package_be_retried(self, pickups, action: DeliveryMissionAction, current_location, actions_list):
        # we want to see, if the current-package can be retried now.
        # we decide this depending on 
        # if the current location corresponds to the postponed package -> drop it if already picked up
        # if this postponed package is not on the same location, check if other packages at the same location wait for action
        # in this case, we want to postpone further
        if action.location_ref.get("code") == current_location.get("code"):
            return True

        # are there other actions with the same location in our list? -> no retry yet
        for tmp_action in actions_list:
            tmp_action: DeliveryMissionAction
            if tmp_action.location_ref.get("code") == action.location_ref.get("code"):
                # we found another package to be dropped / picked up at the same location, so we don't wont to retry yet
                print_debug(f'not retrying postponed package yet {action}')
                return False
            
        # ok, no other same location found so we requeue this dropped package, if it is already picked up:
        if action.package_id in pickups:
            print_debug(f'drop off now possible: retry {action}')
            return True
        
        print_debug(f'still waiting for pickup: {action}')
        return False

    def check_drop_off_at_location(self, pickups, action):
        action: DeliveryMissionAction

        if action.action == "dropoff":            
            if action.package_id in pickups:
                pickups.remove(action.package_id)
                print_debug(f"    dropped {action}")
                return True

            print_debug(f"    no drop of {action} because not picked up yet")
            return False

    def add_pickup_or_postpone_drop_off_check(self, pickups, action, current_location, actions_list) -> bool:
        """ returns true > postpone action
                if dropoff, but not yet picked up
                if dropoff possible, but a later visit is possible
            return false > execute action
                if pickup location
                if dropoff possible and no other action on same location
        """
        action: DeliveryMissionAction
        pickups: set

        if action.action == "dropoff":            
            if action.package_id in pickups:
                # package could be dropped, but we check first, if other actions on the same location are still on the itinerary
                for tmp_action in actions_list:
                    tmp_action: DeliveryMissionAction

                    if tmp_action.location_ref.get("code") == current_location.get("code"):
                        # we found an action, so we postpone this dropoff for later
                        print_debug(f'   postponing {action} as later visit possible')
                        return True

                pickups.remove(action.package_id)
                print_debug(f"    dropped {action}")
                return False

            print_debug(f"    no drop of {action} because not picked up yet")
            return True
                
        print_debug(f"    picked up {action}")
        pickups.add(action.package_id)
        return False
    
    def prioritize(self, mission_actions_list):
        
        print_debug("calculating Priorities")
        tradeports = self.uex_service.get_tradeports()

        count_location_code = {}  # location_code: count
        count_satellite_planet = {} # sat / planet code: count
        location_has_only_pickup_set = {} # location_code: bool
        
        # build up the priorities
        for mission_action in mission_actions_list:
            mission_action: DeliveryMissionAction
            location_code = mission_action.location_ref["code"]
            count = count_location_code.get(location_code, 0) + 10 # same location higher prio than same sat / planet
            count_location_code[location_code] = count

            is_pickup = True if mission_action.action == "pickup" else False
            only_pickup_at_location = location_has_only_pickup_set.get(location_code, True) 

            location_has_only_pickup_set[location_code] = is_pickup and only_pickup_at_location

            satellite_planet = "_".join(
                [mission_action.location_ref["planet"], 
                 mission_action.location_ref["satellite"]])
            
            count = count_satellite_planet.get(satellite_planet, 0) + 5
            count_satellite_planet[satellite_planet] = count

        # now set the priority of each action
        for mission_action in mission_actions_list:
            print(f'-- for {mission_action}')
            mission_action: DeliveryMissionAction
            prio = 0
            prio = 1 if mission_action.action == "pickup" else 0 # the pickup location for this package needs to be visited before the drop-off location
            print(f'   start with {prio} for action type {mission_action.action}')
            
            location_code = mission_action.location_ref["code"]
            location_count = count_location_code.get(location_code, 0)
            print(f'   + {location_count} for number of packages on same location')

            only_pickup_prio = 20 * location_count if location_has_only_pickup_set.get(location_code) is True else 0
            print(f'   + {only_pickup_prio} for only pickups at location')

            satellite_planet = "_".join(
                [mission_action.location_ref["planet"], 
                 mission_action.location_ref["satellite"]])
            same_sapl_count = count_satellite_planet.get(satellite_planet, 0)
            print(f'   + {same_sapl_count} for packages on the same moon or planet')

            prio += only_pickup_prio + location_count + same_sapl_count
            
            location = tradeports.get(location_code, None)
            # outlaw locations should be visited as early as possible to reduce
            # risk of late mission failure (if destroyed)
            # (when we don't find the location it is a derelict outpost not specified, 
            # therefore we assume it is a dangerous place)
            dangerous = False
            if not location or location["outlaw"] == "1":
                dangerous = True
                prio += 50  
                print('   + 50 as outlaw location')

            # same logic, if there is no armistice at this location, potentially more dangerous as other locations
            if not location or location["armistice"] == "0":
                dangerous = True
                prio += 75
                print(f'   + 75 as location without armistice')

            if dangerous:
                # our location is dangerous. If we are dropoff action, we want to pickup our package as early as possible:
                if mission_action.action == "dropoff":
                    mission_action.partner_action.action_priority += prio
                    print_debug(f"overwrite partner {mission_action.partner_action}")
                mission_action.danger = True
            else:  
                # if our partner is a dropoff action and dangerous, our priority must be higher
                if mission_action.partner_action.danger and mission_action.partner_action.action == "dropoff":
                    prio += mission_action.partner_action.action_priority + 1
                    print_debug(f"using partner priority {mission_action.partner_action} ")
                
            mission_action.action_priority = prio

    def prioritize_remaining_list(self, actions_list, current_action, last_action):
        """
            here we focus on the current location that we are currently
            to reprioritize the list
            Intetion: if we changed the planet / satellite, we want to see, if we can
            make the most actions here before leaving the satellite again
        """
        if not current_action or not last_action:
            return
        
        current_location_sapl = "_".join(
                [current_action.location_ref["planet"], 
                 current_action.location_ref["satellite"]])
        
        last_action_sapl = "_".join(
                [last_action.location_ref["planet"], 
                 last_action.location_ref["satellite"]])
        
        if current_location_sapl == last_action_sapl:
            return  # we keep the original priority
        
        print_debug("switched planet / moon: repriorisation of remaing packages")
        tradeports = self.uex_service.get_tradeports()

        count_location_code = {}  # location_code: count
        count_satellite_planet = {} # sat / planet code: count
        location_has_only_pickup_set = {} # location_code: bool
        
        # build up the priorities
        for mission_action in actions_list:
            mission_action: DeliveryMissionAction

            location_code = mission_action.location_ref["code"]
            count = count_location_code.get(location_code, 0) + 2 # same location higher prio than same sat / planet
            count_location_code[location_code] = count

            is_pickup = True if mission_action.action == "pickup" else False
            only_pickup_at_location = location_has_only_pickup_set.get(location_code, True) 

            location_has_only_pickup_set[location_code] = is_pickup and only_pickup_at_location

            satellite_planet = "_".join(
                [mission_action.location_ref["planet"], 
                 mission_action.location_ref["satellite"]])
            
            count = count_satellite_planet.get(satellite_planet, 0) + 1
            count_satellite_planet[satellite_planet] = count

        # now set the priority of each action
        for mission_action in actions_list:
            mission_action: DeliveryMissionAction
            print(f'-- for {mission_action}')
            prio = 0
            prio = 1 if mission_action.action == "pickup" else 0 # the pickup location for this package needs to be visited before the drop-off location
            print(f'   start with {prio} for action type {mission_action.action}')

            location_code = mission_action.location_ref["code"]
            location_count = count_location_code.get(location_code, 0)
            print(f'   + {location_count} for number of packages on same location')

            only_pickup_prio = 20 * location_count if location_has_only_pickup_set.get(location_code) is True else 0
            print(f'   + {only_pickup_prio} because this location has only pickups')

            satellite_planet = "_".join(
                [mission_action.location_ref["planet"], 
                 mission_action.location_ref["satellite"]])
            same_sapl_count = count_satellite_planet.get(satellite_planet, 0)
            print(f'   + {same_sapl_count} for packages on the same moon or planet')

            prio += location_count + same_sapl_count

            if satellite_planet == current_location_sapl:
                prio += 30  # increase the priority of locations on the same planet / satellite
                print('   + 30 as this location is on same planet or satellite we are currently')

            location = tradeports.get(location_code, None)
            # outlaw locations should be visited as early as possible to reduce
            # risk of late mission failure (if destroyed)
            # (when we don't find the location it is a derelict outpost not specified, 
            # therefore we assume it is a dangerous place)
            dangerous = False
            if not location or location["outlaw"] == "1":
                dangerous = True
                prio += 50
                print('   + 50 as outlaw location')  

            # same logic, if there is no armistice at this location, potentially more dangerous as other locations
            if not location or location["armistice"] == "0":
                dangerous = True
                prio += 75
                print('   + 70 as location without armistice')

            if dangerous:
                # our location is dangerous. If we are dropoff action, we want to pickup our package as early as possible:
                if mission_action.action == "dropoff":
                    mission_action.partner_action.action_priority += prio
                    print_debug(f"overwrite partner {mission_action.partner_action}")
                mission_action.danger = True
            else:  
                # if our partner is a dropoff action and dangerous, our priority must be higher
                if mission_action.partner_action.danger and mission_action.partner_action.action == "dropoff":
                    prio += mission_action.partner_action.action_priority
                    print_debug(f"including partner priority {mission_action.partner_action} ")
                
            print_debug(f"action: {mission_action} -> new prio = {prio}")
            mission_action.action_priority = prio
        heapq.heapify(actions_list)
