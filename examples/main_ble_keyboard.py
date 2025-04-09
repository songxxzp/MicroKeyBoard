import struct
import time
import bluetooth
import json
import os
import binascii

from typing import Dict, List
from micropython import const
from usb.device.keyboard import KeyCode


_KEYBOARD_REPORT_DESC = (
    b'\x05\x01'     # Usage Page (Generic Desktop),
        b'\x09\x06'     # Usage (Keyboard),
    b'\xA1\x01'     # Collection (Application),
        b'\x05\x07'         # Usage Page (Key Codes);
            b'\x19\xE0'         # Usage Minimum (224),
            b'\x29\xE7'         # Usage Maximum (231),
            b'\x15\x00'         # Logical Minimum (0),
            b'\x25\x01'         # Logical Maximum (1),
            b'\x75\x01'         # Report Size (1),
            b'\x95\x08'         # Report Count (8),
            b'\x81\x02'         # Input (Data, Variable, Absolute), ;Modifier byte
            b'\x95\x01'         # Report Count (1),
            b'\x75\x08'         # Report Size (8),
            b'\x81\x01'         # Input (Constant), ;Reserved byte
            b'\x95\x05'         # Report Count (5),
            b'\x75\x01'         # Report Size (1),
        b'\x05\x08'         # Usage Page (Page# for LEDs),
            b'\x19\x01'         # Usage Minimum (1),
            b'\x29\x05'         # Usage Maximum (5),
            b'\x91\x02'         # Output (Data, Variable, Absolute), ;LED report
            b'\x95\x01'         # Report Count (1),
            b'\x75\x03'         # Report Size (3),
            b'\x91\x01'         # Output (Constant), ;LED report padding
            b'\x95\x06'         # Report Count (6),
            b'\x75\x08'         # Report Size (8),
            b'\x15\x00'         # Logical Minimum (0),
            b'\x25\x65'         # Logical Maximum(101),
        b'\x05\x07'         # Usage Page (Key Codes),
            b'\x19\x00'         # Usage Minimum (0),
            b'\x29\x65'         # Usage Maximum (101),
            b'\x81\x00'         # Input (Data, Array), ;Key arrays (6 bytes)
    b'\xC0'     # End Collection
)


class BluetoothKeyboard(object):
    """A Bluetooth HID keyboard implementation."""
    def __init__(
            self,
            device_name: str = "MicroKeyBoard",
            paired_deivces_path: str = "paired_devices.json",
        ):
        self.device_name = device_name
        self.paired_deivces_path = paired_deivces_path

        self.paired_device_keys = self._load_paired_device()
        self.ble = bluetooth.BLE()

        self.conn_handle = None
        self.report_handle = None
        self.cccd_handle = None
        self.notifications_enabled = False

        # Bluetooth event constants
        self._IRQ_CENTRAL_CONNECT = const(1)
        self._IRQ_CENTRAL_DISCONNECT = const(2)
        self._IRQ_GATTS_WRITE = const(3)
        self._IRQ_GATTS_READ_REQUEST = const(4)
        self._IRQ_MTU_EXCHANGED = const(21)
        self._IRQ_CONNECTION_UPDATE = const(27)
        self._IRQ_ENCRYPTION_UPDATE = const(28)
        self._IRQ_GET_SECRET = const(29)
        self._IRQ_SET_SECRET = const(30)

        self._FLAG_READ = const(0x0002)
        self._FLAG_WRITE_NO_RESPONSE = const(0x0004)
        self._FLAG_WRITE = const(0x0008)
        self._FLAG_NOTIFY = const(0x0010)
        self._FLAG_READ_WRITE = self._FLAG_READ | self._FLAG_WRITE

        # IO capability configuration for security mode
        self._IO_CAPABILITY_DISPLAY_ONLY = const(0)
        # self._IO_CAPABILITY_DISPLAY_YESNO = const(1)
        # self._IO_CAPABILITY_KEYBOARD_ONLY = const(2)
        # self._IO_CAPABILITY_NO_INPUT_OUTPUT = const(3)
        # self._IO_CAPABILITY_KEYBOARD_DISPLAY = const(4)

        self._HID_SERVICE_UUID = bluetooth.UUID(0x1812)
        self._HID_REPORT_MAP_UUID = bluetooth.UUID(0x2A4B)
        self._HID_INFORMATION_UUID = bluetooth.UUID(0x2A4A)
        self._HID_CONTROL_POINT_UUID = bluetooth.UUID(0x2A4C)
        self._HID_INPUT_REPORT_UUID = bluetooth.UUID(0x2A4D)
        self._CCC_DESCRIPTOR_UUID = bluetooth.UUID(0x2902)
        self._REPORT_REF_DESCRIPTOR_UUID = bluetooth.UUID(0x2908)

        self._KEY_ARRAY_LEN = const(6)  # Size of HID key array, must match report descriptor
        self._KEY_REPORT_LEN = const(self._KEY_ARRAY_LEN + 2)  # Modifier Byte + Reserved Byte + Array entries

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
            with open(self.paired_deivces_path, 'w') as f: json.dump(paired_device_data, f)
            os.sync()
            print("Paired devices saved.")
        except Exception as e: print("Failed to save paired devices:", e)

    def _load_paired_device(self) -> Dict:
        if not self.exists(self.paired_deivces_path): return {}
        try:
            keys_dict = {}
            with open(self.paired_deivces_path, 'r') as f: paired_device_data = json.load(f)
            print("Loaded paired devices.")
            for sec_type, key, value in paired_device_data:
                keys_dict[(sec_type, binascii.a2b_base64(key))] = binascii.a2b_base64(value)
            return keys_dict
        except Exception as e: print("Failed to load paired devices:", e); return {}

    def clear_paired_devices(self) -> None:
        try: os.remove(self.paired_deivces_path); print("Cleared all paired device records.")
        except OSError: print("No paired device records to clear.")

    def send_report(self, report: bytes):
        if self.conn_handle is None or self.report_handle is None:
            return False
        try:
            self.ble.gatts_notify(self.conn_handle, self.report_handle, report)
            return True
        except Exception as e:
            print(f"Failed to send HID report: {e}")
            self.conn_handle = None
            return False

    def send_keys(self, down_keys):
        """Sends a HID keyboard report."""
        modifiers, keycodes = 0, []
        for k in down_keys:
            if k < 0:  # Modifier key
                modifiers |= -k
            elif len(keycodes) < self._KEY_ARRAY_LEN:
                keycodes.append(k)
            else:
                modifiers = 0
                keycodes = []
                break
        keycodes = keycodes + [0] * (self._KEY_ARRAY_LEN - len(keycodes))
        report = struct.pack('BB6B', modifiers, 0, *keycodes)
        return self.send_report(report)

    def _ble_irq(self, event: int, data: tuple) -> None:
        """Handles BLE IRQ events."""
        if event == self._IRQ_CENTRAL_CONNECT:
            self.conn_handle, addr_type, addr = data
            self.notifications_enabled = False
            print("[Connect] Connected to:", binascii.hexlify(addr).decode())
        elif event == self._IRQ_CENTRAL_DISCONNECT:
            conn_handle_old, addr_type, addr = data
            print("[Disconnect] Disconnected from:", binascii.hexlify(addr).decode())
            self.conn_handle = None
            self.notifications_enabled = False
            self.ble.gap_advertise(None)
            time.sleep_ms(200)
            self._start_advertising()
        elif event == self._IRQ_GATTS_WRITE:
            conn_handle_write, attr_handle = data
            print(f"_IRQ_GATTS_WRITE: conn={conn_handle_write}, handle={attr_handle}")
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
        elif event == self._IRQ_GATTS_READ_REQUEST:
            conn_handle_read, attr_handle = data
            print(f"_IRQ_GATTS_READ_REQUEST: conn={conn_handle_read}, handle={attr_handle}")
            return None
        elif event == self._IRQ_ENCRYPTION_UPDATE:
            conn_handle_enc, encrypted, authenticated, bonded_status, key_size = data
            print(f"Encryption state: encrypted={encrypted}, authenticated={authenticated}, bonded={bonded_status}")
        elif event == self._IRQ_GET_SECRET:
            sec_type, index, key = data; key = bytes(key) if key is not None else None
            if key is None: return None
            if self.paired_device_keys and (sec_type, key) in self.paired_device_keys:
                return self.paired_device_keys[(sec_type, key)]
            return None
        elif event == self._IRQ_SET_SECRET:
            sec_type, key, value = data
            key = bytes(key) if key is not None else None
            value = bytes(value) if value is not None else None
            if value is None:
                self.paired_device_keys.pop((sec_type, key), None); self._save_paired_device(); return True
            else:
                self.paired_device_keys[(sec_type, key)] = value; self._save_paired_device(); return True
        elif event == self._IRQ_MTU_EXCHANGED:
            conn_handle_mtu, mtu = data
            print(f"_IRQ_MTU_EXCHANGED: new MTU={mtu}")
        else:
            print(f"Unhandled event: {event}")

    def _start_advertising(self) -> None:
        """Starts BLE advertising."""
        adv_data = self._build_adv_data(name=self.device_name, service_uuids=[0x1812])
        try:
            self.ble.gap_advertise(interval_us=100000, adv_data=adv_data, connectable=True, resp_data=None)
            print("Advertising started...")
        except Exception as e:
            print(f"Failed to start advertising: {e}")

    def connected(self):
        return self.conn_handle is not None and self.notifications_enabled

    def run(self):
        """Main execution method."""
        self.ble.active(True)
        print("BLE Radio Active.")
        try:
            self.ble.config(gap_name=self.device_name, mitm=True, bond=True, le_secure=True, io=self._IO_CAPABILITY_DISPLAY_ONLY)
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

            self.ble.gatts_write(h_report_map, _KEYBOARD_REPORT_DESC)
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

        sequence = [KeyCode.M, KeyCode.I, KeyCode.C, KeyCode.R, KeyCode.O]

        while True:
            if self.connected():
                for keycode in sequence:
                    self.send_keys([keycode])
                    time.sleep_ms(100)
                    self.send_keys([])
                    time.sleep_ms(100)
                break
            else:
                time.sleep_ms(200)


if __name__ == "__main__":
    keyboard = BluetoothKeyboard()
    keyboard.run()
