class MissionLocationInformation:
    """
        contains information related to all active delivery missions for a given location:
        
        Args:
            location_code
            pickup_package_numbers = [int]
            dropoff_package_numbers = [int] \n
            sell_at_location = False # filled by CargoRoutePlanner \n
            self.selling_commodity_code = None # filled by CargoRoutePlanner \n
            self.buy_at_location = False # filled by CargoRoutePlanner \n
            self.buying_commodity_code = None # filled by CargoRoutePlanner
    """
    def __init__(self, location=None):
        location_code = None
        if location:
            location_code = location["code"]
        self.location_code = location_code
        self.location = location
        self.pickup_package_numbers = []
        self.dropoff_package_numbers = []
        self.sell_at_location = False
        self.selling_commodity_code = None
        self.buy_at_location = False
        self.buying_commodity_code = None

    def __repr__(self):
        commodities_info = ""
        if self.sell_at_location:
            commodities_info += f" sell {self.selling_commodity_code}"
        if self.buy_at_location:
            commodities_info += f" buy {self.buying_commodity_code}"
        
        return (f"LocationPackageManager [location={self.location_code} ({self.location['satellite']}), "
                f"pickupPackageNumbers={self.pickup_package_numbers}, "
                f"dropoffPackageNumbers={self.dropoff_package_numbers}, "
                f"commodities:{commodities_info}]\n\n")

    def __eq__(self, other):
        if not isinstance(other, MissionLocationInformation):
            return False
        return self.location_code == other.location_code

    def __hash__(self):
        return hash(self.location_code)

    # Add more methods as needed for managing package numbers and commodities
