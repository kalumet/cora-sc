class MissionPackage:
    """
    contains all necessary information about a given package of a mission
    """
    mission_id: int
    package_id: int
    pickup_location_ref: dict
    """the code of a tradeport as of uex api tradeports"""
    drop_off_location_ref: dict
    """the code of a tradeport as of uex api tradeports"""