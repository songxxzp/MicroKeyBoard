import struct
import time
import bluetooth
import json
import os
import binascii

from typing import Dict, List
from micropython import const

# Bluetooth event constants
IRQ_CENTRAL_CONNECT = const(1)
IRQ_CENTRAL_DISCONNECT = const(2)
IRQ_MTU_EXCHANGED = const(21)
IRQ_CONNECTION_UPDATE = const(27)
IRQ_ENCRYPTION_UPDATE = const(28)
IRQ_GET_SECRET = const(29)
IRQ_SET_SECRET = const(30)

# File for storing paired devices
PAIRED_DEVICES_FILE = "paired_devices.json"

# IO capability configuration for security mode
IO_CAPABILITY_DISPLAY_ONLY = const(0)


def exists(path: str) -> bool:
    """Check if a file exists."""
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def build_adv_data(name: str = None, service_uuids: List[int] = None) -> bytes:
    """
    Build advertising data for BLE.

    Args:
        name: Device name to include in advertising data.
        service_uuids: List of service UUIDs to include.

    Returns:
        Advertising data as bytes.
    """
    parts = []
    # Flags indicating general discoverability and BLE-only mode
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


def save_paired_device(paired_device_keys: Dict) -> None:
    """
    Save paired device information to a file.

    Args:
        paired_device_keys: Dictionary containing paired device keys.
    """
    try:
        paired_device_data = [
            [sec_type, binascii.b2a_base64(key).decode(), binascii.b2a_base64(value).decode()]
            for (sec_type, key), value in paired_device_keys.items()
        ]
        with open(PAIRED_DEVICES_FILE, 'w') as f:
            json.dump(paired_device_data, f)
        os.sync()
        print("Paired devices saved:", paired_device_data)
    except Exception as e:
        print("Failed to save paired devices:", e)


def load_paired_device() -> Dict:
    """
    Load paired device information from a file.

    Returns:
        Dictionary containing paired device keys.
    """
    if not exists(PAIRED_DEVICES_FILE):
        return {}
    try:
        paired_device_keys = {}
        with open(PAIRED_DEVICES_FILE, 'r') as f:
            paired_device_data = json.load(f)
        print("Loaded paired devices:", paired_device_data)
        for sec_type, key, value in paired_device_data:
            paired_device_keys[(sec_type, binascii.a2b_base64(key))] = binascii.a2b_base64(value)
        return paired_device_keys
    except Exception as e:
        print("Failed to load paired devices:", e)
        return {}


def clear_paired_devices() -> None:
    """Clear all paired device records."""
    try:
        os.remove(PAIRED_DEVICES_FILE)
        print("Cleared all paired device records.")
    except OSError:
        print("No paired device records to clear.")


def ble_irq(event: int, data: tuple) -> None:
    """
    Handle BLE IRQ (interrupt request) events.

    Args:
        event: Event type.
        data: Event-specific data.
    """
    global bonded, paired_device_keys

    if event == IRQ_CENTRAL_CONNECT:
        conn_handle, addr_type, addr = data
        print("[Connect] Connected:", bytes(addr))
        bonded = False  # Reset bonding status

    elif event == IRQ_CENTRAL_DISCONNECT:
        conn_handle, addr_type, addr = data
        print("[Disconnect] Disconnected:", bytes(addr))

        # Stop advertising and restart after a delay
        ble.gap_advertise(None)
        time.sleep_ms(1000)
        start_advertising()

    elif event == IRQ_ENCRYPTION_UPDATE:
        conn_handle, encrypted, authenticated, bonded, key_size = data
        print(f"Encryption state: encrypted={encrypted}, authenticated={authenticated}")

    elif event == IRQ_GET_SECRET:
        sec_type, index, key = data
        key = bytes(key) if key is not None else None
        print(f"IRQ_GET_SECRET: type={sec_type}, index={index}")
        if key is None:
            return None
        if paired_device_keys and (sec_type, key) in paired_device_keys:
            return paired_device_keys[(sec_type, key)]
        return None

    elif event == IRQ_SET_SECRET:
        sec_type, key, value = data
        key = bytes(key) if key is not None else None
        value = bytes(value) if value is not None else None
        print(f"IRQ_SET_SECRET: type={sec_type}, key={key}, value={value}")
        if paired_device_keys is None:
            paired_device_keys = {}
        if value is None:
            paired_device_keys.pop((sec_type, key), None)
            save_paired_device(paired_device_keys)
            return True
        else:
            paired_device_keys[(sec_type, key)] = value
            save_paired_device(paired_device_keys)
        return False

    elif event == IRQ_MTU_EXCHANGED:
        conn_handle, mtu = data
        print(f"IRQ_MTU_EXCHANGED: mtu={mtu}")
        ble.config(mtu=mtu)

    else:
        print(f"Unhandled event: {event}")


def start_advertising() -> None:
    """Start BLE advertising (peripheral mode)."""
    ble.config(
        io=IO_CAPABILITY_DISPLAY_ONLY,  # Set IO capability
        bond=True,  # Enable bonding
        le_secure=True  # Enable LE secure connections
    )

    # Build advertising data with device name and service UUIDs
    adv_data = build_adv_data(
        name="MicroKeyBoard",
        service_uuids=[0x1812]  # HID service UUID
    )
    ble.gap_advertise(
        interval_us=100,
        adv_data=adv_data,
        connectable=True,
        resp_data=None
    )


if __name__ == "__main__":
    # Load paired device keys from file
    paired_device_keys = load_paired_device()

    # Initialize BLE
    ble = bluetooth.BLE()
    ble.active(True)
    ble.config(
        gap_name="MicroKeyBoard",
        mitm=True,  # Require man-in-the-middle protection
        bond=True  # Enable bonding
    )
    ble.irq(ble_irq)

    # Start advertising
    start_advertising()

    # Print the device MAC address
    mac_address = ble.config('mac')[1]
    print("Device MAC Address:", ":".join("{:02X}".format(x) for x in mac_address))

