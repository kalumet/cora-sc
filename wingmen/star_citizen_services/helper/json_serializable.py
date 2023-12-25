import json


class JsonSerializable:
    _json_ignored_attributes = set()

    @classmethod
    def ignore_for_json(cls, attr_name):
        cls._json_ignored_attributes.add(attr_name)

    def to_dict(self):
        """
        Convert the object into a dictionary.
        Ignores attributes listed in _json_ignored_attributes.
        """
        return {k: v for k, v in self.__dict__.items() if k not in self._json_ignored_attributes}
    
    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        filtered_data = {k: v for k, v in data.items() if k not in cls._json_ignored_attributes}
        return cls(**filtered_data)
