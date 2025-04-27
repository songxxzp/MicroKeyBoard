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
en_pin: int = 38

p0 = Pin(sd_pin, Pin.OUT, value=0)
en = Pin(en_pin, Pin.OUT, value=0)
