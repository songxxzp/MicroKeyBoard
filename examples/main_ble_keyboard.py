import struct
import time
import bluetooth
import json
import os
import binascii
# from machine import Timer # Not needed
from typing import Dict, List
from micropython import const

# Bluetooth event constants
IRQ_CENTRAL_CONNECT = const(1)
IRQ_CENTRAL_DISCONNECT = const(2)
IRQ_GATTS_WRITE = const(3)
IRQ_GATTS_READ_REQUEST = const(4)
IRQ_MTU_EXCHANGED = const(21)
IRQ_CONNECTION_UPDATE = const(27) # Not explicitly handled, but defined
IRQ_ENCRYPTION_UPDATE = const(28)
IRQ_GET_SECRET = const(29)
IRQ_SET_SECRET = const(30)

# File for storing paired devices
PAIRED_DEVICES_FILE = "paired_devices.json"

# IO capability configuration for security mode
IO_CAPABILITY_DISPLAY_ONLY = const(0)

# HID Report Descriptor for Keyboard (Standard)
HID_REPORT_DESCRIPTOR = bytes([
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x85, 0x01, 0x05, 0x07,
    0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01,
    0x95, 0x08, 0x81, 0x02, 0x95, 0x01, 0x75, 0x08, 0x81, 0x01,
    0x05, 0x08, 0x19, 0x01, 0x29, 0x05, 0x95, 0x05, 0x75, 0x01,
    0x91, 0x02, 0x95, 0x01, 0x75, 0x03, 0x91, 0x03, 0x05, 0x07,
    0x19, 0x00, 0x29, 0xFF, 0x15, 0x00, 0x25, 0xFF, 0x75, 0x08,
    0x95, 0x06, 0x81, 0x00, 0xC0
])

# Keycode for 'm'
KEYCODE_M = const(0x10)

# Global variables
conn_handle = None
report_handle = None
cccd_handle = None # <<< NEW: Store CCCD handle
notifications_enabled = False # <<< NEW: Flag for notification state
paired_device_keys = {}

# === Helper Functions (Unchanged) ===
def exists(path: str) -> bool:
    try: os.stat(path); return True
    except OSError: return False

def build_adv_data(name: str = None, service_uuids: List[int] = None) -> bytes:
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

def save_paired_device(paired_device_keys_dict: Dict) -> None:
    try:
        paired_device_data = [
            [sec_type, binascii.b2a_base64(key).decode(), binascii.b2a_base64(value).decode()]
            for (sec_type, key), value in paired_device_keys_dict.items()
        ]
        with open(PAIRED_DEVICES_FILE, 'w') as f: json.dump(paired_device_data, f)
        os.sync()
        print("Paired devices saved.")
    except Exception as e: print("Failed to save paired devices:", e)

def load_paired_device() -> Dict:
    if not exists(PAIRED_DEVICES_FILE): return {}
    try:
        keys_dict = {}
        with open(PAIRED_DEVICES_FILE, 'r') as f: paired_device_data = json.load(f)
        print("Loaded paired devices.")
        for sec_type, key, value in paired_device_data:
            keys_dict[(sec_type, binascii.a2b_base64(key))] = binascii.a2b_base64(value)
        return keys_dict
    except Exception as e: print("Failed to load paired devices:", e); return {}

def clear_paired_devices() -> None:
    try: os.remove(PAIRED_DEVICES_FILE); print("Cleared all paired device records.")
    except OSError: print("No paired device records to clear.")

# === HID Specific Function (Unchanged) ===
def send_hid_report(modifier, keycode):
    """Sends a HID keyboard report."""
    global conn_handle, report_handle
    if conn_handle is None or report_handle is None:
        # Don't print error here, expected when disconnected or not ready
        # print("Not connected or report handle not set, cannot send report.")
        return False # Indicate failure
    report = struct.pack('BB6B', modifier, 0, keycode, 0, 0, 0, 0, 0)
    try:
        ble.gatts_notify(conn_handle, report_handle, report)
        return True # Indicate success
    except Exception as e:
        print(f"Failed to send HID report: {e}")
        conn_handle = None # Assume connection lost on error
        return False # Indicate failure

def send_m_key():
    """Sends a press and release sequence for the 'm' key."""
    print("Attempting 'm' key sequence...")
    if send_hid_report(0, KEYCODE_M): # Press 'm'
        time.sleep_ms(50) # Delay only if press succeeded
        if send_hid_report(0, 0): # Release keys
            print("'m' key sequence sent successfully.")
        else:
            print("Failed to send key release.")
    else:
        print("Failed to send key press.")


# === BLE Interrupt Handler (Modified) ===
def ble_irq(event: int, data: tuple) -> None:
    """Handles BLE IRQ events."""
    global conn_handle, paired_device_keys, notifications_enabled, cccd_handle

    if event == IRQ_CENTRAL_CONNECT:
        conn_handle, addr_type, addr = data
        notifications_enabled = False # Reset flag on new connection
        print("[Connect] Connected to:", binascii.hexlify(addr).decode())
        # --- DO NOT SEND KEY HERE ---

    elif event == IRQ_CENTRAL_DISCONNECT:
        conn_handle_old, addr_type, addr = data
        print("[Disconnect] Disconnected from:", binascii.hexlify(addr).decode())
        conn_handle = None
        notifications_enabled = False # Reset flag
        ble.gap_advertise(None)
        # Consider a slightly shorter delay or manage advertising state better
        time.sleep_ms(200) # Shorter delay before restarting advertising
        start_advertising()
        # print("Advertising restarted.") # Moved to start_advertising

    elif event == IRQ_GATTS_WRITE:
        conn_handle_write, attr_handle = data
        print(f"IRQ_GATTS_WRITE: conn={conn_handle_write}, handle={attr_handle}")
        # Check if the write is to *our* CCCD handle
        if attr_handle == cccd_handle:
            try:
                value_written = ble.gatts_read(attr_handle)
                print(f"  Value written to CCCD handle {attr_handle}: {value_written}")
                if value_written == b'\x01\x00':
                    print("  Notifications ENABLED by host.")
                    notifications_enabled = True
                elif value_written == b'\x00\x00':
                    print("  Notifications DISABLED by host.")
                    notifications_enabled = False
                else:
                    print("  Unknown value written to CCCD.")
                    notifications_enabled = False
            except Exception as e:
                print(f"  Could not read value written to CCCD handle {attr_handle}: {e}")
                notifications_enabled = False
        else:
             print("  Write was to a different handle.")


    elif event == IRQ_GATTS_READ_REQUEST:
        conn_handle_read, attr_handle = data
        print(f"IRQ_GATTS_READ_REQUEST: conn={conn_handle_read}, handle={attr_handle}")
        return None # Allow default handling

    elif event == IRQ_ENCRYPTION_UPDATE:
        conn_handle_enc, encrypted, authenticated, bonded_status, key_size = data
        print(f"Encryption state: encrypted={encrypted}, authenticated={authenticated}, bonded={bonded_status}")

    elif event == IRQ_GET_SECRET:
        sec_type, index, key = data; key = bytes(key) if key is not None else None
        if key is None: return None
        if paired_device_keys and (sec_type, key) in paired_device_keys:
            return paired_device_keys[(sec_type, key)]
        return None

    elif event == IRQ_SET_SECRET:
        sec_type, key, value = data
        key = bytes(key) if key is not None else None
        value = bytes(value) if value is not None else None
        if value is None:
            paired_device_keys.pop((sec_type, key), None); save_paired_device(paired_device_keys); return True
        else:
            paired_device_keys[(sec_type, key)] = value; save_paired_device(paired_device_keys); return True

    elif event == IRQ_MTU_EXCHANGED:
        conn_handle_mtu, mtu = data
        print(f"IRQ_MTU_EXCHANGED: new MTU={mtu}")

    else:
        print(f"Unhandled event: {event}")


# === Advertising Function (Minor print change) ===
def start_advertising() -> None:
    """Starts BLE advertising."""
    adv_data = build_adv_data(name="MicroKeyBoard", service_uuids=[0x1812])
    try:
        ble.gap_advertise(interval_us=100000, adv_data=adv_data, connectable=True, resp_data=None)
        print("Advertising started...") # Moved print here
    except Exception as e:
        print(f"Failed to start advertising: {e}")


# === Main Execution Block (Modified) ===
if __name__ == "__main__":
    paired_device_keys = load_paired_device()
    ble = bluetooth.BLE()
    ble.active(True)
    print("BLE Radio Active.")

    try:
        ble.config(gap_name="MicroKeyBoard", mitm=True, bond=True, le_secure=True, io=IO_CAPABILITY_DISPLAY_ONLY)
        print("BLE Configured.")
    except Exception as e: print(f"Error setting BLE config: {e}")

    _FLAG_READ = const(0x0002)
    _FLAG_WRITE_NO_RESPONSE = const(0x0004)
    _FLAG_WRITE = const(0x0008)
    _FLAG_NOTIFY = const(0x0010)
    _FLAG_READ_WRITE = _FLAG_READ | _FLAG_WRITE

    _HID_SERVICE_UUID = bluetooth.UUID(0x1812)
    _HID_REPORT_MAP_UUID = bluetooth.UUID(0x2A4B)
    _HID_INFORMATION_UUID = bluetooth.UUID(0x2A4A)
    _HID_CONTROL_POINT_UUID = bluetooth.UUID(0x2A4C)
    _HID_INPUT_REPORT_UUID = bluetooth.UUID(0x2A4D)
    _CCC_DESCRIPTOR_UUID = bluetooth.UUID(0x2902)
    _REPORT_REF_DESCRIPTOR_UUID = bluetooth.UUID(0x2908)

    hid_service_definition = (
        _HID_SERVICE_UUID, (
            (_HID_REPORT_MAP_UUID, _FLAG_READ,),
            (_HID_INFORMATION_UUID, _FLAG_READ,),
            (_HID_CONTROL_POINT_UUID, _FLAG_WRITE_NO_RESPONSE,),
            (_HID_INPUT_REPORT_UUID, _FLAG_READ | _FLAG_NOTIFY, (
                (_CCC_DESCRIPTOR_UUID, _FLAG_READ_WRITE,), # <<< This handle needs to be stored
                (_REPORT_REF_DESCRIPTOR_UUID, _FLAG_READ,),
            )),
        ),
    )

    ble.gap_advertise(None); time.sleep_ms(100)
    print("Registering services...")
    try:
        # <<< Store CCCD Handle >>>
        ( (h_report_map, h_hid_info, h_control_point, h_input_report, h_input_cccd, h_input_ref), ) = ble.gatts_register_services((hid_service_definition,))
        report_handle = h_input_report
        cccd_handle = h_input_cccd # <<< Store the handle globally
        print(f"Services registered. Report Handle: {report_handle}, CCCD Handle: {cccd_handle}")

        ble.gatts_write(h_report_map, HID_REPORT_DESCRIPTOR)
        hid_info_value = struct.pack("<HBB", 0x0111, 0x00, 0x01)
        ble.gatts_write(h_hid_info, hid_info_value)
        input_ref_value = struct.pack("<BB", 1, 1)
        ble.gatts_write(h_input_ref, input_ref_value)
        print("Initial characteristic/descriptor values written.")

    except Exception as e: print(f"Error registering services or writing values: {e}")

    ble.irq(ble_irq)
    print("BLE IRQ Handler Set.")
    start_advertising()

    try:
        mac_address = ble.config('mac')[1]
        print("Device MAC Address:", ":".join(f"{b:02X}" for b in mac_address))
    except Exception as e: print(f"Could not get MAC address: {e}")

    print("Setup complete. Waiting for connections...")

    # === Main Loop for Periodic Keypress ===
    while True:
        # Check if connected AND notifications are enabled by the host
        if conn_handle is not None and notifications_enabled:
            send_m_key()
            # Wait 2 seconds before sending the next keypress
            time.sleep_ms(2000)
        else:
            # Sleep briefly when not active to prevent busy-waiting
            # This allows background BLE tasks to run smoothly
            time.sleep_ms(200) # Check status roughly 5 times/second