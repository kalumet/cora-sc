import time
import json
import webbrowser
import traceback
from collections import defaultdict

from datetime import datetime
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport

from wingmen.star_citizen_services.helper import time_string_converter


DEBUG = True
TEST = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class RegolithAPI:

    def __init__(self, config, x_api_key):
        # Initialize your instance here, if not already initialized
        if not hasattr(self, "is_initialized"):
            self.root_data_path = "star_citizen_data/regolith"

            self.base_api_url = (
                "https://api.regolith.rocks/staging/"
                if TEST
                else "https://api.regolith.rocks"
            )
            self.url = (
                "https://staging.regolith.rocks" if TEST else "https://regolith.rocks"
            )

            print_debug("Initializing RegolithAPI instance")
            self.is_initialized = True
        else:
            print_debug("RegolithAPI instance already initialized")

        self.transport = RequestsHTTPTransport(
            url=self.base_api_url,
            use_json=True,
            headers={
                "Content-Type": "application/json",
                "x-api-key": x_api_key,
            },
            retries=3,
            retry_backoff_factor=2,
            timeout=300,
        )

        self.client = Client(
            transport=self.transport, fetch_schema_from_transport=False
        )
        self.active_session_id = None
        self.refineries = None
        self.refinery_methods = None
        self.gravity_wells = None
        self.locations = None
        self.ship_ores = None
        self.activities = None
        self.lookups = None

    def open_session_in_browser(self, session_id=None):
        if not session_id:
            session_id = self.get_last_active_session()
        return webbrowser.open(f"{self.url}/session/{session_id}/dash")

    def delete_mining_session(self, session_id):
        mutation = gql(
            """
            mutation DeleteSession($sessionId: ID!) {
            deleteSession(sessionId: $sessionId)
            }
        """
        )

        variables = {"sessionId": session_id}

        try:
            response = self.client.execute(mutation, variable_values=variables)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])

                return False
            else:
                print_debug("Mining Session deleted")
                self.active_session_id = None
                return True
        except Exception as e:
            print(
                f"Error trying to delete mining session: {str(e)}:\n{traceback.print_stack()}"
            )
            return False

    def get_graphql_for_names(self, object_name):
        return (
            f'{object_name}: __type(name: "{object_name}") {{'
            " name"
            " enumValues {"
            "  name"
            "  description"
            " }"
            "}"
        )

    def initialize_all_names(self):
        # Erstelle die Queries für RefineryEnum und RefineryMethodEnum
        list_of_name_fields = []
        list_of_name_fields.append(self.get_graphql_for_names("RefineryEnum"))
        list_of_name_fields.append(self.get_graphql_for_names("RefineryMethodEnum"))
        list_of_name_fields.append(self.get_graphql_for_names("ActivityEnum"))
        list_of_name_fields.append(self.get_graphql_for_names("LocationEnum"))
        list_of_name_fields.append(self.get_graphql_for_names("ShipOreEnum"))

        # Kombiniere die beiden Queries zu einer einzigen Query
        combined_query = "{" + " ".join(list_of_name_fields) + "}"

        # Führe die Mutation aus
        try:
            response = self.client.execute(gql(combined_query))

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return
            else:
                print_debug("retrieved all entity names from regolith")
                self.refineries = [
                    value["name"] for value in response["RefineryEnum"]["enumValues"]
                ]
                self.refinery_methods = [
                    value["name"]
                    for value in response["RefineryMethodEnum"]["enumValues"]
                ]
                self.activities = [
                    value["name"] for value in response["ActivityEnum"]["enumValues"]
                ]
                self.locations = [
                    value["name"] for value in response["LocationEnum"]["enumValues"]
                ]
                self.ship_ores = [
                    value["name"] for value in response["ShipOreEnum"]["enumValues"]
                ]
                return
        except Exception as e:
            print(
                f"Error during entity name retrieval from regolith: {str(e)}:\n{traceback.print_stack()}"
            )
            return

    def get_refinery_names(self):
        if self.refineries is not None:
            return self.refineries

        enum_type = gql("{" + self.get_graphql_for_names("RefineryEnum") + "}")

        try:
            response = self.client.execute(enum_type)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug(f"Refineries retrieved")
                self.refineries = [
                    value["name"] for value in response["RefineryEnum"]["enumValues"]
                ]
                return self.refineries
        except Exception as e:
            print(
                f"Error during refinery name retrieval: {str(e)}:\n{traceback.print_stack()}"
            )
            return []

    def get_refinery_method_names(self):
        if self.refinery_methods is not None:
            return self.refinery_methods
        enum_type = gql("{" + self.get_graphql_for_names("RefineryMethodEnum") + "}")

        try:
            response = self.client.execute(enum_type)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug("Refinery methods retrieved")
                self.refinery_methods = [
                    value["name"]
                    for value in response["RefineryMethodEnum"]["enumValues"]
                ]
                return self.refinery_methods
        except Exception as e:
            print(
                f"Error during retrieval refinery methods: {str(e)}:\n{traceback.print_stack()}"
            )
            return []

    def get_gravity_wells(self):
        if self.gravity_wells is not None:
            return self.gravity_wells

        enum_type = gql("{" + self.get_graphql_for_names("PlanetEnum") + "}")

        try:
            response = self.client.execute(enum_type)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug("Gravity wells name retrieved")
                self.gravity_wells = [
                    value["name"] for value in response["PlanetEnum"]["enumValues"]
                ]
                return self.gravity_wells
        except Exception as e:
            print(
                f"Error during gravity wells retrieval: {str(e)}:\n{traceback.print_stack()}"
            )
            return []

    def get_activity_names(self):
        if self.activities is not None:
            return self.activities

        enum_type = gql("{" + self.get_graphql_for_names("ActivityEnum") + "}")

        try:
            response = self.client.execute(enum_type)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug("Activity name retrieved")
                self.activities = [
                    value["name"] for value in response["ActivityEnum"]["enumValues"]
                ]
                return self.activities
        except Exception as e:
            print(
                f"Error during activity name retrieval: {str(e)}:\n{traceback.print_stack()}"
            )
            return []

    def get_location_names(self):
        if self.locations is not None:
            return self.locations
        enum_type = gql("{" + self.get_graphql_for_names("LocationEnum") + "}")

        try:
            response = self.client.execute(enum_type)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug("locations name retrieved")
                self.locations = [
                    value["name"] for value in response["LocationEnum"]["enumValues"]
                ]
                return self.locations
        except Exception as e:
            print(
                f"Error during locations name retrieval: {str(e)}:\n{traceback.print_stack()}"
            )
            return []

    def get_ship_ore_names(self):
        if self.ship_ores is not None:
            return self.ship_ores
        enum_type = gql("{" + self.get_graphql_for_names("LocationEnum") + "}")

        try:
            response = self.client.execute(enum_type)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug("ship_ores name retrieved")
                self.ship_ores = [
                    value["name"] for value in response["ShipOreEnum"]["enumValues"]
                ]
                return self.ship_ores
        except Exception as e:
            print(
                f"Error during ship_ores name retrieval: {str(e)}:\n{traceback.print_stack()}"
            )
            return []

    def get_last_active_session(self):
        if self.active_session_id is not None:
            return self.active_session_id
        enum_type = gql(
            """
            query getMyUserSessions($nextToken: String, ) {
                profile {
                    mySessions(nextToken: $nextToken) {
                    items {
                        ...SessionListFragment
                        ...SessionSummaryFragment
                    }
                    nextToken
                    }
                }
                }

                fragment SessionListFragment on Session {
                sessionId
                name
                createdAt
                finishedAt
                state
                }

                fragment SessionSummaryFragment on Session {
                summary {
                    aUEC
                    oreSCU
                    allPaid
                    refineries
                }
                }

        """
        )

        try:
            response = self.client.execute(enum_type)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])
                return []
            else:
                print_debug("active_sessions retrieved")
                active_sessions = [
                    session
                    for session in response["profile"]["mySessions"]["items"]
                    if session["state"] == "ACTIVE"
                ]

                if active_sessions:
                    newest_active_session = max(
                        active_sessions, key=lambda x: x["createdAt"]
                    )
                    print_debug(
                        f'newest session: {newest_active_session["name"]} with id: {newest_active_session["sessionId"]}'
                    )
                else:
                    print_debug("No active sessions found.")
                    self.active_session_id = None
                    return None

                self.active_session_id = newest_active_session["sessionId"]
                return self.active_session_id

        except Exception as e:
            print(
                f"Error trying to retrieve an active session: {str(e)}:\n{traceback.print_stack()}"
            )
            self.active_session_id = None
            return None

    def get_or_create_mining_session(self, name, activity, refinery):
        session_id = self.get_last_active_session()
        if session_id is None:
            session_id = self.create_mining_session(name, activity, refinery)
        return session_id

    def create_mining_session(self, name, activity, refinery):
        now = datetime.now()
        # Zuerst das Datum mit führenden Nullen formatieren
        formatted_date_with_zero = now.strftime("%A, %b %d, %I %p")

        # Führende Null von der Stunde entfernen, falls vorhanden
        formatted_date = formatted_date_with_zero.replace(" 0", " ")

        # GraphQL-Mutation als String, minimiert auf erforderliche Felder
        mutation = gql(
            """
        mutation createSession($session: SessionInput!, $sessionSettings: SessionSettingsInput, $workOrderDefaults: WorkOrderDefaultsInput) {
            createSession(
            session: $session
            sessionSettings: $sessionSettings
            workOrderDefaults: $workOrderDefaults
            ) {
                sessionId
                __typename
            }
        }
        """
        )

        variables = {
            "session": {
                "name": f"C-Session: {name if name else ''} {formatted_date}",
                "note": "This session has been created by Cora - your AI Compagnion. ",
            },
            "sessionSettings": {
                "activity": activity if activity else "SHIP_MINING",
                "specifyUsers": True,
                "allowUnverifiedUsers": False,
                "usersCanAddUsers": True,
                "usersCanInviteUsers": True,
            },
        }

        if activity == "SHIP_MINING":
            variables["workOrderDefaults"] = {
                "includeTransferFee": True,
                "method": "DINYX_SOLVENTATION",
                "shareRefinedValue": False,
                "isRefined": True,
            }

        if refinery:
            variables["workOrderDefaults"]["refinery"] = refinery

        try:
            response = self.client.execute(mutation, variable_values=variables)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])

                return None
            else:
                print_debug("Mining Session created")
                self.active_session_id = response.get("createSession", {}).get(
                    "sessionId", None
                )
                return self.active_session_id
        except Exception as e:
            print(
                f"Error trying to create mining session: {str(e)}:\n{traceback.print_stack()}"
            )
            return None

    def create_work_order(self, work_order_details):
        print_debug(
            f"creating work order with: \n{json.dumps(work_order_details, indent=2)}"
        )

        mutation = gql(
            """
            mutation CreateWorkOrder(
                $sessionId: ID!,
                $shipOres: [RefineryRowInput!],
                $workOrder: WorkOrderInput!
                ) {
                createWorkOrder(
                        shares: [],
                        sessionId: $sessionId,
                        shipOres: $shipOres,
                        workOrder: $workOrder
                ) {
                    ... on ShipMiningOrder {
                        orderId
                        __typename
                    }
                }
            }
        """
        )

        try:
            response = self.client.execute(mutation, variable_values=work_order_details)

            if "errors" in response:
                print("Fehler bei der GraphQL-Anfrage:")
                for error in response["errors"]:
                    print(error["message"])
                return {
                    "success": False,
                    "message": "There was an error when I tried to create the session. I'm very sorry. ",
                }
            else:
                print_debug(
                    f'Work order created: {response["createWorkOrder"]["orderId"]}'
                )
                return {
                    "success": True,
                    "message": "Work order created. Do you want to open the session in the browser?",
                    "sessionId": work_order_details["sessionId"],
                }
        except Exception as e:
            print(
                f"Error during work order creation {str(e)}: \n{traceback.print_stack()}"
            )
            return {
                "success": False,
                "message": "Sorry, but regolith seems not to be available currently. ",
            }

    def get_active_work_orders(self):
        print_debug("getting active work orders: ")

        query = self.get_active_work_session_query()

        try:
            response = self.client.execute(query)

            if "errors" in response:
                print("Errors during Graph-QL request:")
                for error in response["errors"]:
                    print(error["message"])
                return {
                    "success": False,
                    "message": "There was an error when I tried to retrieve active work orders. I'm very sorry. ",
                }
            else:
                finished_work_orders = self.process_work_orders(response)
                print_debug(
                    f"Work orders retrieved. {json.dumps(finished_work_orders, indent=2)}"
                )

                if finished_work_orders["total_finished_refinery_orders"] > 0:
                    return {
                        "success": True,
                        "instructions": (
                            "Give a summary to the player in his language of his work orders ready for pickup and still processing orders. "
                            "The first refinery mentioned contains the most processed orders to be picked up. Tell him the refinery and the number of orders ready. "
                            "Further, tell him when the next refinery order is going to be finished. "
                            "Ask the player, if he wants to open this session in the browser. "
                        ),
                        "data": finished_work_orders,
                    }

                return {
                    "success": True,
                    "instructions": (
                        "Respond in the players language. Tell him when the next refinery order is going to be finished, if any. "
                    ),
                    "data": finished_work_orders,
                }
        except Exception as e:
            print(
                f"Error during work order retrieval {str(e)}: \n{traceback.print_stack()}"
            )
            return {
                "success": False,
                "message": "Sorry, but regolith seems not to be available currently. ",
            }

    def get_active_work_session_query(self):
        query = gql(
            """
            query getUserProfil($nextToken: String) {
            profile {
                ...UserProfileFragment
                __typename
            }
            }
            fragment UserProfileFragment on UserProfile {
            workOrders(nextToken: $nextToken) {
                items {
                    ...WorkOrderFragment
                    __typename
                }
                nextToken
            }
            __typename
            }
            fragment WorkOrderFragment on WorkOrderInterface {
                orderId
                sessionId
                state
                isSold
                ... on ShipMiningOrder {
                    isRefined
                    refinery
                    processStartTime
                    processDurationS
                    processEndTime
                    shipOres {
                    ore
                    }
                    __typename
                }
            }
        """
        )

        return query

    def get_or_create_scouting_cluster(self, session_id):
        query = gql(
            """
                    query getSession($sessionId: ID!) {
                        session(sessionId: $sessionId) {
                            ...SessionFragment
                        }
                        }

                        fragment SessionFragment on Session {
                        scouting {
                            items {
                            ...ScoutingFindFragment
                            }
                            nextToken
                        }
                        }

                        fragment ScoutingFindFragment on ScoutingFindInterface {
                        ...ScoutingFindBaseFragment
                        state
                        }

                        fragment ScoutingFindBaseFragment on ScoutingFindInterface {
                        scoutingFindId
                        createdAt
                        clusterType
                        clusterCount
                        note
                        ... on ShipClusterFind {
                            shipRocks {
                            ...ShipRockFragment
                            }
                        }  
                        }

                        fragment ShipRockFragment on ShipRock {
                        mass
                        inst
                        res
                        state
                        ores {
                            ore
                            percent
                        }
                        }
        """
        )

        variables = {"sessionId": session_id}

        try:
            response = self.client.execute(query, variable_values=variables)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])

                return False
            else:
                scouting_items = response["session"]["scouting"]["items"]

                if not scouting_items:
                    # Keine Einträge vorhanden
                    scoutingFindId = self.create_scouting_cluster(session_id)
                    print_debug(f"Created new scouting item: {scoutingFindId}")
                    return scoutingFindId, 0
                else:
                    # Es existiert bereits mindestens ein Eintrag
                    # Sortiere absteigend nach createdAt:
                    cluster = sorted(
                        scouting_items, key=lambda i: i["createdAt"], reverse=True
                    )[0]
                    return cluster
        except Exception as e:
            print(
                f"Error trying to delete mining session: {str(e)}:\n{traceback.print_stack()}"
            )
            return False

    def create_scouting_cluster(self, session_id, cluster_count=0, cluster_type=None):
        mutation = gql(
            """mutation addScoutingFind($sessionId: ID!, $scoutingFind: ScoutingFindInput!, $shipRocks: [ShipRockInput!]) {
                addScoutingFind(
                    sessionId: $sessionId
                    scoutingFind: $scoutingFind
                    shipRocks: $shipRocks
                ) {
                    ...ScoutingFindFragment
                }
                }

                fragment ScoutingFindFragment on ScoutingFindInterface {
                ...ScoutingFindBaseFragment
                state
                }

                fragment ScoutingFindBaseFragment on ScoutingFindInterface {
                scoutingFindId
                createdAt
                clusterType
                clusterCount
                note
                ... on ShipClusterFind {
                    shipRocks {
                    ...ShipRockFragment
                    }
                }
                }

                fragment ShipRockFragment on ShipRock {
                mass
                inst
                res
                state
                ores {
                    ore
                    percent
                }
                }  
        """
        )

        variables = {
            "sessionId": session_id,
            "scoutingFind": {
                "state": "DISCOVERED",
                "clusterCount": cluster_count,
                "note": "{'info': 'This cluster has been discovered by Cora - your AI Compagnion.'"
                + (f", 'cluster_type': '{cluster_type}'" if cluster_type else "")
                + "}",
            },
            "shipRocks": [],
        }

        try:
            response = self.client.execute(mutation, variable_values=variables)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])

                return None
            else:
                return response["addScoutingFind"]
        except Exception as e:
            print(
                f"Error trying creating cluster: {str(e)}:\n{traceback.print_stack()}"
            )
            return None

    def add_ship_cluster_scan_results(
        self, session_id, cluster, ship_rock_scan_result
    ):
        mutation = gql(
            """mutation updateScoutingFind($sessionId: ID!, $scoutingFindId: ID!, $scoutingFind: ScoutingFindInput!, $shipRocks: [ShipRockInput!]) {
                updateScoutingFind(
                    sessionId: $sessionId
                    scoutingFindId: $scoutingFindId
                    scoutingFind: $scoutingFind
                    shipRocks: $shipRocks
                ) {
                    ...ScoutingFindFragment
                }
            }

            fragment ScoutingFindFragment on ScoutingFindInterface {
                ...ScoutingFindBaseFragment
                state
            }

            fragment ScoutingFindBaseFragment on ScoutingFindInterface {
                sessionId
                scoutingFindId
                clusterCount
                note
                ... on ShipClusterFind {
                    shipRocks {
                        ...ShipRockFragment
                    }
                }
            }

            fragment ShipRockFragment on ShipRock {
                mass
                inst
                res
                state
                ores {
                    ore
                    percent
                }
            }
            """
        )

        ores = ship_rock_scan_result["ores"]
        cleaned_ores = [
            {key: value for key, value in ore.items() if key != "__typename"}
            for ore in ores
        ]

        ship_rocks = cluster.get("shipRocks", [])
        ship_rocks.append({
                    "mass": ship_rock_scan_result["mass"],
                    "state": "READY",
                    "inst": ship_rock_scan_result["inst"],
                    "res": ship_rock_scan_result["res"],
                    "ores": cleaned_ores,
                })

        variables = {
            "sessionId": session_id,
            "scoutingFindId": cluster["scoutingFindId"],
            "scoutingFind": {"state": "DISCOVERED"},
            "shipRocks": ship_rocks,
        }

        try:
            response = self.client.execute(mutation, variable_values=variables)

            if "errors" in response:
                print("Error during GraphQL-Request:")
                for error in response["errors"]:
                    print(error["message"])

                return {
                    "success": False,
                    "message": response["errors"],
                }
            else:
                return {
                    "success": True,
                    "message": "scan results saved",
                }
        except Exception as e:
            print(f"Error during save scan: {str(e)}:\n{traceback.print_stack()}")
            return {
                "success": False,
                "message": f"Unable to save scan. Check the logs because of {str(e)}. ",
            }

    def process_work_orders(self, data):
        current_time_ms = int(datetime.now().timestamp() * 1000)

        # Zuerst Duplikate entfernen (hier anhand orderId).
        # Wenn du orderId + sessionId für die Eindeutigkeit brauchst,
        # kannst du stattdessen (order['orderId'], order['sessionId']) als Schlüssel benutzen.
        unique_orders_map = {}
        for o in data["profile"]["workOrders"]["items"]:
            if o["orderId"] not in unique_orders_map:
                unique_orders_map[o["orderId"]] = o

        # In eine Liste umwandeln
        unique_orders = list(unique_orders_map.values())

        # Jetzt die eigentliche Logik
        refinery_groups = defaultdict(
            lambda: {
                "order_count": 0,
                "ores": set(),
                "sessions": defaultdict(lambda: {"session_id": None, "orders": []}),
            }
        )

        total_orders_in_processing = 0
        next_order_finish_duration = float(
            "inf"
        )  # Initialize to the largest possible number

        for order in unique_orders:
            # Prüfen, ob der Auftrag noch läuft
            if order["processEndTime"] > current_time_ms:
                total_orders_in_processing += 1
                if order["processEndTime"] < next_order_finish_duration:
                    next_order_finish_duration = order["processEndTime"]

            # Wenn Auftrag fertig (d. h. Endzeit < jetzt) und noch nicht verkauft
            if not order["isSold"] and order["processEndTime"] < current_time_ms:
                refinery = order["refinery"]
                session_id = order["sessionId"]

                # Update Zählungen und Daten sammeln
                refinery_groups[refinery]["order_count"] += 1
                refinery_groups[refinery]["ores"].update(
                    [ore["ore"] for ore in order["shipOres"]]
                )
                refinery_groups[refinery]["sessions"][session_id][
                    "session_id"
                ] = session_id
                refinery_groups[refinery]["sessions"][session_id]["orders"].append(
                    {"orderId": order["orderId"]}
                )

        total_refined_orders = sum(
            info["order_count"] for info in refinery_groups.values()
        )

        if total_orders_in_processing == 0:
            next_order_finish_str = "No active orders"
        else:
            secs_remaining = (next_order_finish_duration - current_time_ms) / 1000
            next_order_finish_str = time_string_converter.convert_seconds_to_str(
                int(secs_remaining)
            )

        refinery_orders = []
        # Sortiere nach der höchsten 'order_count'
        for refinery, info in sorted(
            refinery_groups.items(), key=lambda x: -x[1]["order_count"]
        ):
            sessions_sorted = sorted(
                info["sessions"].values(), key=lambda x: -len(x["orders"])
            )
            refinery_entry = {
                "refinery": refinery,
                "order_count": info["order_count"],
                "ores": list(info["ores"]),
                "sessions": [
                    {"sessionId": session["session_id"], "orders": session["orders"]}
                    for session in sessions_sorted
                ],
            }
            refinery_orders.append(refinery_entry)

        # Rückgabe
        if total_refined_orders == 0:
            return {
                "total_finished_refinery_orders": total_refined_orders,
                "total_refinery_orders_in_processing": total_orders_in_processing,
                "next_refinery_job_finished_in": next_order_finish_str,
            }

        return {
            "total_finished_refinery_orders": total_refined_orders,
            "total_refinery_orders_in_processing": total_orders_in_processing,
            "next_refinery_order_finished_in": next_order_finish_str,
            "finished_refinery_orders": refinery_orders,
        }

        # {
        #     "total_finished_refinery_orders": 3,
        #     "total_refinery_orders_in_processing": 0,
        #     "next_refinery_job_finished_in": "No active orders", # or 21h 33m
        #     "finished_refinery_orders": [
        #         {
        #             "refinery": "MIC-L2",
        #             "order_count": 3,
        #             "ores": [
        #                 "GOLD", "TARANITE"
        #             ],
        #             "sessions": [
        #             {
        #                 "sessionId": "dasdf",
        #                 "orders": [
        #                     {
        #                         "orderId": "hasldfasd",
        #                     }
        #                 ]
        #             }
        #         }

        #     ]
        # }

    def delete_processed_sessions(self):
        print_debug("deleting processed sessions. ")
        query = self.get_active_work_session_query()

        try:
            response = self.client.execute(query)

            if "errors" in response:
                print("Errors during Graph-QL request:")
                for error in response["errors"]:
                    print(error["message"])
                return {
                    "success": False,
                    "message": "There was an error when I tried to retrieve active work orders. I'm very sorry. ",
                }
            else:
                return self.delete_sessions(response)
        except Exception as e:
            print(
                f"Error during work order retrieval {str(e)}: \n{traceback.print_stack()}"
            )
            return {
                "success": False,
                "message": "Sorry, but regolith seems not to be available currently. ",
            }

    def delete_sessions(self, work_order_sessions):
        current_time_ms = int(datetime.now().timestamp() * 1000)

        valid_sessions = {}
        for order in work_order_sessions["profile"]["workOrders"]["items"]:
            session_id = order["sessionId"]
            if order["isSold"] and order["processEndTime"] < current_time_ms:
                if session_id not in valid_sessions:
                    valid_sessions[session_id] = True
            else:
                # Sobald eine Order die Kriterien nicht erfüllt, wird die Session als ungültig markiert
                valid_sessions[session_id] = False

        if len(valid_sessions) == 0:
            return {"success": True, "message": "You don't have any active sessions. "}

        count_deleted = 0
        count_not_deleted = 0
        count_errors = 0
        total_sessions = 0
        for session_id, is_valid in valid_sessions.items():
            total_sessions += 1
            if is_valid:
                success = self.delete_session(session_id)
                if success:
                    count_deleted += 1
                else:
                    count_errors += 1
            else:
                count_not_deleted += 1

        if count_errors == 0 and count_deleted > 0:
            return {
                "success": True,
                "message": "All processed sessions have been deleted. Give a summary. ",
                "data": {
                    "total_sessions_evaluated": total_sessions,
                    "deleted_finished_sessions": count_deleted,
                    "sessions_with_active_jobs": count_not_deleted,
                },
            }
        elif count_errors > 0 and count_deleted > 0:
            return {
                "success": False,
                "message": "Not all processed sessions could be deleted. Give a summary. ",
                "data": {
                    "total_sessions_evaluated": total_sessions,
                    "deleted_finished_sessions": count_deleted,
                    "sessions_with_active_jobs": count_not_deleted,
                    "finished_sessions_that_could_not_be_deleted": count_errors,
                },
            }
        elif count_errors > 0 and count_deleted == 0:
            return {
                "success": False,
                "message": "None of the processed sessions could be deleted. Give a summary. ",
                "data": {
                    "total_sessions_evaluated": total_sessions,
                    "deleted_finished_sessions": count_deleted,
                    "sessions_with_active_jobs": count_not_deleted,
                    "finished_sessions_that_could_not_be_deleted": count_errors,
                },
            }

        return {
            "success": False,
            "message": "You don't have any processed sessions that could be deleted, but you have active sessions. ",
            "data": {
                "total_sessions_evaluated": total_sessions,
                "deleted_finished_sessions": count_deleted,
                "sessions_with_active_jobs": count_not_deleted,
                "finished_sessions_that_could_not_be_deleted": count_errors,
            },
        }

    def delete_session(self, session_id):
        print_debug(f"Deleting session {session_id}")
        mutation = gql(
            """
                mutation DeleteSession($sessionId: ID!) {
            deleteSession(sessionId: $sessionId)
        }
        """
        )

        variables = {"sessionId": session_id}

        try:
            response = self.client.execute(mutation, variable_values=variables)

            if "errors" in response:
                print("Fehler bei der GraphQL-Anfrage:")
                for error in response["errors"]:
                    print(error["message"])
                return False

            print_debug(f'Session deleted: {response["deleteSession"]}')
            return True
        except Exception as e:
            print(
                f"Error during session deletion {str(e)}: \n{traceback.print_stack()}"
            )
            return False

    def get_work_order_image_infos(self, base64_jpg_url_string):
        """
        Expects a "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQ" String
        """
        print_debug(f"retrieving work order information")

        # GraphQL-Mutation als String, minimiert auf erforderliche Felder
        query = gql(
            """
            query captureRefineryOrder($imgUrl: String!) {
                captureRefineryOrder(imgUrl: $imgUrl) {
                    expenses {
                    amount
                    name
                    }
                    processDurationS
                    refinery
                    method
                    shipOres {
                    amt
                    ore
                    yield
                    }
                }
            }
        """
        )
        return self._get_image_infos(query, base64_jpg_url_string)

    def get_rock_scan_image_infos(self, base64_jpg_url_string):
        query = gql(
            """
                query captureShipRockScan($imgUrl: String!) {
                    captureShipRockScan(imgUrl: $imgUrl) {
                        mass
                        inst
                        res
                        ores {
                        ore
                        percent
                        __typename
                        }
                        __typename
                    }
                }
            """
        )
        return self._get_image_infos(query, base64_jpg_url_string)

    def _get_image_infos(self, query_str, base64_jpg_url_string):
        variables = {"imgUrl": base64_jpg_url_string}

        try:
            response = self.client.execute(query_str, variable_values=variables)

            if "errors" in response:
                print("Fehler bei der GraphQL-Anfrage:")
                for error in response["errors"]:
                    print(error["message"])
                return {
                    "success": False,
                    "message": "There was an error when I tried to retrieve image information. I'm very sorry. ",
                }
            else:
                print_debug(
                    f"retrieved image information: {json.dumps(response, indent=2)}"
                )
                return response
        except Exception as e:
            print(
                f"Error during work order creation {str(e)}: \n{traceback.print_stack()}"
            )
            return {
                "success": False,
                "message": "Sorry, but regolith seems not to be available currently. ",
            }

    def fetch_lookups(self):
        """
        Fetches lookup data from the GraphQL API.
        """
        query = gql(
            """
            query GetLookups {
                lookups {
                    CIG {
                    oreProcessingLookup
                    refineryBonusLookup
                    methodsBonusLookup
                    }
                }
            }
            """
        )

        try:
            response = self.client.execute(query)

            if "errors" in response:
                print("Fehler bei der GraphQL-Anfrage:")
                for error in response["errors"]:
                    print(error["message"])
                return None
            else:
                return response["lookups"]["CIG"]
        except Exception as e:
            print(
                f"Error during work order creation {str(e)}: \n{traceback.print_stack()}"
            )
            return None

    def ore_amt_calc(self, ore_yield, ore, refinery, method):
        """
        Calculates the final ore amount after applying processing, refinery, and method bonuses.

        Args:
            ore_yield (float): Initial ore yield.
            ore (str): Type of ore.
            refinery (str): Name of the refinery.
            method (str): Refining method used.
            api_url (str): GraphQL API URL to fetch lookup data.

        Returns:
            int: Final ore amount rounded to the nearest integer.
        """
        # Fetch lookup data
        if self.lookups is None:
            self.lookups = self.fetch_lookups()
        ore_processing_lookup = self.lookups["oreProcessingLookup"]
        refinery_bonus_lookup = self.lookups["refineryBonusLookup"]
        methods_bonus_lookup = self.lookups["methodsBonusLookup"]

        # Default bonuses
        processing_bonus = 1
        refinery_bonus = 1
        method_bonus = 1

        # Refinery bonus lookup
        if refinery not in refinery_bonus_lookup:
            print(f"Refinery {refinery} not found.")
        elif ore not in refinery_bonus_lookup[refinery]:
            print(f"Ore {ore} not found in refinery {refinery}.")
        else:
            refinery_bonus = refinery_bonus_lookup[refinery][ore][0]

        # Method bonus lookup
        if method not in methods_bonus_lookup:
            print(f"Method {method} not found.")
        else:
            method_bonus = methods_bonus_lookup[method][0]

        # Ore processing bonus lookup
        if ore not in ore_processing_lookup:
            print(f"Ore {ore} not found in ore processing lookup.")
        else:
            processing_bonus = ore_processing_lookup[ore][0]

        # Final calculation
        final_ore_yield = ore_yield / (processing_bonus * refinery_bonus * method_bonus)
        return round(final_ore_yield)


# Example usage
if __name__ == "__main__":
    regolith = RegolithAPI(None, "i288P0IjLz9HiYTFWV8nd8CMErZjueu2a2GxthVs")
    current_time = int(time.time())

    # regolith.create_mining_session()

    # variables = {
    #     "sessionId": regolith.active_session_id,
    #     "shipOres": [
    #         {
    #             "amt": 100,  # Die Menge des Erzes
    #             "ore": "QUANTANIUM"  # Der Enum-Wert des Erzes
    #         }
    #     ],
    #     "workOrder": {
    #         "expenses": [
    #             {
    #                 "amount": 6841,
    #                 "name": "Refinery Fee"
    #             }
    #         ],
    #         "includeTransferFee": True,
    #         "isRefined": True,
    #         "isSold": False,
    #         "method": "DINYX_SOLVENTATION",  # Angenommen, dies ist ein gültiger Wert im RefineryMethodEnum
    #         "note": "Work order created by Cora - Your Star Citizen ai-compagnion",
    #         "processDurationS": 3600,  # Angenommen, dies ist die Dauer in Sekunden
    #         "processStartTime": current_time,  # Ein Zeitstempel
    #         "refinery": "MICL2",  # Angenommen, dies ist ein gültiger Wert im RefineryEnum
    #     }
    #     # Fülle die anderen Listenparameter entsprechend
    # }

    # regolith.create_work_order(regolith.active_session_id, None)
    # regolith.delete_mining_session(regolith.activeSessionId)
    # regolith.get_refinery_names()
    # print_debug(f"refineries: {regolith.refineries}")
    # regolith.get_refinery_method_names()
    # print_debug(f"refinery methods: {regolith.refinery_methods}")
    # regolith.get_location_names()
    # print_debug(f"locations: {regolith.locations}")
    # regolith.get_gravity_wells()
    # print_debug(f"gravity wells: {regolith.gravity_wells}")
    # regolith.get_last_active_session()
    # regolith.initialize_all_names()
