import json
import machine

from typing import List, Dict
from microkeyboard.utils import exists
from microkeyboard.pins import IRQPin
from microkeyboard.module import PCA9555, TCA8418


class DeivceManager:
    devices_config: Dict[str, List[Dict]] = {}
    devices: Dict = {}

    def __init__(
        self,
        devices_config_path = "/config/devices.json",
    ):
        if exists(devices_config_path):
            self.devices_config = json.load(open(devices_config_path))
        for device_config in self.devices_config["devices"]:
            if device_config["dtype"] == "I2C":  # TODO: priority
                i2c_id, freq = device_config.get("id", 0), device_config.get("freq", 400000)  # TODO: Auto I2C ID
                scl_pin, sda_pin = device_config["scl"], device_config["sda"]
                device = machine.I2C(i2c_id, scl=machine.Pin(scl_pin), sda=machine.Pin(sda_pin), freq=freq)
            elif device_config["dtype"] == "int":
                int_pin = device_config["pin"]
                device = IRQPin(int_pin, machine.Pin.IN, machine.Pin.PULL_UP)
            elif device_config["dtype"] == "pca9555":
                assert device_config["mode"] == "I2C"
                address, i2c_name, interpret = int(device_config["address"], 16), device_config["i2c"], device_config.get("int", None)
                i2c_device = self.get_device(i2c_name)
                device = PCA9555(i2c_device, address)
            elif device_config["dtype"] == "tca8418":
                assert device_config["mode"] == "I2C"
                address, i2c_name, interpret = int(device_config["address"], 16), device_config["i2c"], device_config.get("int", None)
                i2c_device = self.get_device(i2c_name)
                device = TCA8418(i2c_device, address)
            # TODO: Manage SPI
            else:
                raise NotImplementedError(f'Not implemented dtype: {device_config["dtype"]}')
            self.reg_deivce(device_config["name"], device)

    def reg_deivce(self, device_name: str, device):
        self.devices[device_name] = device

    def get_device(self, device_name: str):
        assert device_name in self.devices, f"{device_name} not in self.devices"
        return self.devices.get(device_name)


GLOBAL_DEIVCE_MANAGER = DeivceManager()
