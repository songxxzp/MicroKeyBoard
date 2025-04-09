import struct
import time
import bluetooth
import json
import os
import binascii
from typing import Dict, List
from micropython import const
from usb.device import keyboard as usb_keyboard
from usb.device import hid as usb_hid

class BluetoothKeyboard:
    """A Bluetooth HID keyboard implementation."""

    # Bluetooth event constants
    IRQ_CENTRAL_CONNECT = const(1)
    IRQ_CENTRAL_DISCONNECT = const(2)
    IRQ_GATTS_WRITE = const(3)
    IRQ_GATTS_READ_REQUEST = const(4)
    IRQ_MTU_EXCHANGED = const(21)
    IRQ_CONNECTION_UPDATE = const(27)
    IRQ_ENCRYPTION_UPDATE = const(28)
    IRQ_GET_SECRET = const(29)
    IRQ_SET_SECRET = const(30)

    # File for storing paired devices
    PAIRED_DEVICES_FILE = "paired_devices.json"

    # IO capability configuration for security mode
    IO_CAPABILITY_DISPLAY_ONLY = const(0)

    def __init__(self):
        self.conn_handle = None
        self.report_handle = None
        self.cccd_handle = None
        self.notifications_enabled = False
        self.paired_device_keys = self._load_paired_device()
        self.ble = bluetooth.BLE()

        self._FLAG_READ = const(0x0002)
        self._FLAG_WRITE_NO_RESPONSE = const(0x0004)
        self._FLAG_WRITE = const(0x0008)
        self._FLAG_NOTIFY = const(0x0010)
        self._FLAG_READ_WRITE = self._FLAG_READ | self._FLAG_WRITE

        self._HID_SERVICE_UUID = bluetooth.UUID(0x1812)
        self._HID_REPORT_MAP_UUID = bluetooth.UUID(0x2A4B)
        self._HID_INFORMATION_UUID = bluetooth.UUID(0x2A4A)
        self._HID_CONTROL_POINT_UUID = bluetooth.UUID(0x2A4C)
        self._HID_INPUT_REPORT_UUID = bluetooth.UUID(0x2A4D)
        self._CCC_DESCRIPTOR_UUID = bluetooth.UUID(0x2902)
        self._REPORT_REF_DESCRIPTOR_UUID = bluetooth.UUID(0x2908)

    def exists(self, path: str) -> bool:
        try: os.stat(path); return True
        except OSError: return False

    def _build_adv_data(self, name: str = None, service_uuids: List[int] = None) -> bytes:
        parts = []
        parts.append(b'\x02\x01\x06')
        if service_uuids:
            for uuid in service_uuids:
                uuid_bytes = struct.pack('<H', uuid)
                svc_part = struct.pack('BB', 1 + len(uuid_bytes), 0x03) + uuid_bytes
                parts.append(svc_part)
                break
        if name:
            encoded_name = name.encode('utf-8')
            name_header = struct.pack('BB', 1 + len(encoded_name), 0x09)
            parts.append(name_header + encoded_name)
        return b''.join(parts)

    def _save_paired_device(self) -> None:
        try:
            paired_device_data = [
                [sec_type, binascii.b2a_base64(key).decode(), binascii.b2a_base64(value).decode()]
                for (sec_type, key), value in self.paired_device_keys.items()
            ]
            with open(self.PAIRED_DEVICES_FILE, 'w') as f: json.dump(paired_device_data, f)
            os.sync()
            print("Paired devices saved.")
        except Exception as e: print("Failed to save paired devices:", e)

    def _load_paired_device(self) -> Dict:
        if not self.exists(self.PAIRED_DEVICES_FILE): return {}
        try:
            keys_dict = {}
            with open(self.PAIRED_DEVICES_FILE, 'r') as f: paired_device_data = json.load(f)
            print("Loaded paired devices.")
            for sec_type, key, value in paired_device_data:
                keys_dict[(sec_type, binascii.a2b_base64(key))] = binascii.a2b_base64(value)
            return keys_dict
        except Exception as e: print("Failed to load paired devices:", e); return {}

    def clear_paired_devices(self) -> None:
        try: os.remove(self.PAIRED_DEVICES_FILE); print("Cleared all paired device records.")
        except OSError: print("No paired device records to clear.")

    def send_hid_report(self, modifier, keycode):
        """Sends a HID keyboard report."""
        if self.conn_handle is None or self.report_handle is None:
            return False
        report = struct.pack('BB6B', modifier, 0, keycode, 0, 0, 0, 0, 0)
        try:
            self.ble.gatts_notify(self.conn_handle, self.report_handle, report)
            return True
        except Exception as e:
            print(f"Failed to send HID report: {e}")
            self.conn_handle = None
            return False

    def send_m_key(self):
        """Sends a press and release sequence for the 'm' key."""
        print("Attempting 'm' key sequence...")
        if self.send_hid_report(0, usb_keyboard.KeyCode.M):
            time.sleep_ms(50)
            if self.send_hid_report(0, 0):
                print("'m' key sequence sent successfully.")
            else:
                print("Failed to send key release.")
        else:
            print("Failed to send key press.")

    def _ble_irq(self, event: int, data: tuple) -> None:
        """Handles BLE IRQ events."""
        if event == self.IRQ_CENTRAL_CONNECT:
            self.conn_handle, addr_type, addr = data
            self.notifications_enabled = False
            print("[Connect] Connected to:", binascii.hexlify(addr).decode())

        elif event == self.IRQ_CENTRAL_DISCONNECT:
            conn_handle_old, addr_type, addr = data
            print("[Disconnect] Disconnected from:", binascii.hexlify(addr).decode())
            self.conn_handle = None
            self.notifications_enabled = False
            self.ble.gap_advertise(None)
            time.sleep_ms(200)
            self._start_advertising()

        elif event == self.IRQ_GATTS_WRITE:
            conn_handle_write, attr_handle = data
            print(f"IRQ_GATTS_WRITE: conn={conn_handle_write}, handle={attr_handle}")
            if attr_handle == self.cccd_handle:
                try:
                    value_written = self.ble.gatts_read(attr_handle)
                    print(f"  Value written to CCCD handle {attr_handle}: {value_written}")
                    if value_written == b'\x01\x00':
                        print("  Notifications ENABLED by host.")
                        self.notifications_enabled = True
                    elif value_written == b'\x00\x00':
                        print("  Notifications DISABLED by host.")
                        self.notifications_enabled = False
                    else:
                        print("  Unknown value written to CCCD.")
                        self.notifications_enabled = False
                except Exception as e:
                    print(f"  Could not read value written to CCCD handle {attr_handle}: {e}")
                    self.notifications_enabled = False
            else:
                print("  Write was to a different handle.")

        elif event == self.IRQ_GATTS_READ_REQUEST:
            conn_handle_read, attr_handle = data
            print(f"IRQ_GATTS_READ_REQUEST: conn={conn_handle_read}, handle={attr_handle}")
            return None

        elif event == self.IRQ_ENCRYPTION_UPDATE:
            conn_handle_enc, encrypted, authenticated, bonded_status, key_size = data
            print(f"Encryption state: encrypted={encrypted}, authenticated={authenticated}, bonded={bonded_status}")

        elif event == self.IRQ_GET_SECRET:
            sec_type, index, key = data; key = bytes(key) if key is not None else None
            if key is None: return None
            if self.paired_device_keys and (sec_type, key) in self.paired_device_keys:
                return self.paired_device_keys[(sec_type, key)]
            return None

        elif event == self.IRQ_SET_SECRET:
            sec_type, key, value = data
            key = bytes(key) if key is not None else None
            value = bytes(value) if value is not None else None
            if value is None:
                self.paired_device_keys.pop((sec_type, key), None); self._save_paired_device(); return True
            else:
                self.paired_device_keys[(sec_type, key)] = value; self._save_paired_device(); return True

        elif event == self.IRQ_MTU_EXCHANGED:
            conn_handle_mtu, mtu = data
            print(f"IRQ_MTU_EXCHANGED: new MTU={mtu}")

        else:
            print(f"Unhandled event: {event}")

    def _start_advertising(self) -> None:
        """Starts BLE advertising."""
        adv_data = self._build_adv_data(name="MicroKeyBoard", service_uuids=[0x1812])
        try:
            self.ble.gap_advertise(interval_us=100000, adv_data=adv_data, connectable=True, resp_data=None)
            print("Advertising started...")
        except Exception as e:
            print(f"Failed to start advertising: {e}")

    def run(self):
        """Main execution method."""
        self.ble.active(True)
        print("BLE Radio Active.")

        try:
            self.ble.config(gap_name="MicroKeyBoard", mitm=True, bond=True, le_secure=True, io=self.IO_CAPABILITY_DISPLAY_ONLY)
            print("BLE Configured.")
        except Exception as e: print(f"Error setting BLE config: {e}")

        hid_service_definition = (
            self._HID_SERVICE_UUID, (
                (self._HID_REPORT_MAP_UUID, self._FLAG_READ,),
                (self._HID_INFORMATION_UUID, self._FLAG_READ,),
                (self._HID_CONTROL_POINT_UUID, self._FLAG_WRITE_NO_RESPONSE,),
                (self._HID_INPUT_REPORT_UUID, self._FLAG_READ | self._FLAG_NOTIFY, (
                    (self._CCC_DESCRIPTOR_UUID, self._FLAG_READ_WRITE,),
                    (self._REPORT_REF_DESCRIPTOR_UUID, self._FLAG_READ,),
                )),
            ),
        )

        self.ble.gap_advertise(None); time.sleep_ms(100)
        print("Registering services...")
        try:
            ( (h_report_map, h_hid_info, h_control_point, h_input_report, h_input_cccd, h_input_ref), ) = self.ble.gatts_register_services((hid_service_definition,))
            self.report_handle = h_input_report
            self.cccd_handle = h_input_cccd
            print(f"Services registered. Report Handle: {self.report_handle}, CCCD Handle: {self.cccd_handle}")

            self.ble.gatts_write(h_report_map, usb_keyboard._KEYBOARD_REPORT_DESC)
            hid_info_value = struct.pack("<HBB", 0x0111, 0x00, 0x01)
            self.ble.gatts_write(h_hid_info, hid_info_value)
            input_ref_value = struct.pack("<BB", 1, 1)
            self.ble.gatts_write(h_input_ref, input_ref_value)
            print("Initial characteristic/descriptor values written.")

        except Exception as e: print(f"Error registering services or writing values: {e}")

        self.ble.irq(self._ble_irq)
        print("BLE IRQ Handler Set.")
        self._start_advertising()

        try:
            mac_address = self.ble.config('mac')[1]
            print("Device MAC Address:", ":".join(f"{b:02X}" for b in mac_address))
        except Exception as e: print(f"Could not get MAC address: {e}")

        print("Setup complete. Waiting for connections...")

        while True:
            if self.conn_handle is not None and self.notifications_enabled:
                self.send_m_key()
                time.sleep_ms(2000)
            else:
                time.sleep_ms(200)

if __name__ == "__main__":
    keyboard = BluetoothKeyboard()
    keyboard.run()
