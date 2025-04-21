import time
from machine import Pin

def main():
    CE_PIN = 13  # Clock Enable pin
    PL_PIN = 11  # Parallel Load pin
    SPI_CLOCK = 14  # SPI Clock pin
    SPI_MISO = 12  # SPI Master In Slave Out pin
    SR_POWER_CONTROLL = 21 # shift register power
    WAKE_UP = 7

    key_pl = Pin(PL_PIN, Pin.OUT, value=1)
    key_ce = Pin(CE_PIN, Pin.OUT, value=1)
    key_clk = Pin(SPI_CLOCK, Pin.OUT, value=0)
    key_in = Pin(SPI_MISO, Pin.IN)
    
    if SR_POWER_CONTROLL is not None:
        power_controll = Pin(SR_POWER_CONTROLL, Pin.OUT, value=1)
        wakeup = Pin(WAKE_UP, Pin.OUT, value=0)

    time.sleep_ms(500)
    while True:
        key_pl.value(0)
        time.sleep_ms(1)
        key_pl.value(1)
        time.sleep_ms(1)
        key_ce.value(0)
        time.sleep_ms(1)
        for i in range(72):
            if not key_in.value():
                print(i)
            key_clk.value(1)
            time.sleep_ms(1)
            key_clk.value(0)
            time.sleep_ms(1)
        key_ce.value(1)
    
    pass

if __name__ == "__main__":
    main()


