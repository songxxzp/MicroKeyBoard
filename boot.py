# This is script that run when device boot up or wake from sleep.
# import time

# print("Debug count down:")
# count_down_seconds = 3
# for i in range(count_down_seconds):
#     print(f"Start in {count_down_seconds - i} seconds.")

import json
from machine import Pin

print("Suppressing noise on start.")
sd_pin: int = 45
p0 = Pin(0, Pin.OUT, value=0)
