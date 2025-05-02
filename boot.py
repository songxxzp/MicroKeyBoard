# This is script that run when device boot up or wake from sleep.
from machine import Pin

en_pin: int = 38
sd_pin: int = 45

en = Pin(en_pin, Pin.OUT, value=0)
p0 = Pin(sd_pin, Pin.OUT, value=0)

print("Suppressing noise on start.")
