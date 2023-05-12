import os
import json
from faker.providers import BaseProvider

SOURCE_DIR = 'output_address_files'


def delete_address_from_source(address_dict):
    for filename in os.listdir(SOURCE_DIR):
        file_path = os.path.join(SOURCE_DIR, filename)
        with open(file_path, "r") as f:
            data = json.load(f)

        for i, a in enumerate(data):
            if a == address_dict:
                data.pop(i)
                break

        with open(file_path, "w") as f:
            json.dump(data, f)


class AddressProvider(BaseProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.addresses = []
        self.load_addresses()

    def load_addresses(self):
        directory_path = "output_address_files"
        for filename in os.listdir(directory_path):
            with open(os.path.join(directory_path, filename), "r") as f:
                data = json.load(f)
                self.addresses += data

    def address(self, postcode=None):
        if postcode:
            matching_addresses = [a for a in self.addresses if a['postcode'] == postcode]
            if matching_addresses:
                return self.random_element(matching_addresses)
        return self.random_element(self.addresses)
