import time
from machine import Pin

def main():
    CE_PIN = 13  # Clock Enable pin
    PL_PIN = 12  # Parallel Load pin
    SPI_CLOCK = 11  # SPI Clock pin
    SPI_MISO = 14  # SPI Master In Slave Out pin
    key_pl = Pin(PL_PIN, Pin.OUT, value=1)
    key_ce = Pin(CE_PIN, Pin.OUT, value=1)
    key_clk = Pin(SPI_CLOCK, Pin.OUT, value=0)
    key_in = Pin(SPI_MISO, Pin.IN)
    
    time.sleep_ms(500)
    while True:
        key_pl.value(0)
        time.sleep_us(1)
        key_pl.value(1)
        time.sleep_us(1)
        key_ce.value(0)
        time.sleep_us(1)
        for i in range(72):
            if not key_in.value():
                print(i)
            key_clk.value(1)
            time.sleep_us(1)
            key_clk.value(0)
            time.sleep_us(1)
        key_ce.value(1)
    
    pass

if __name__ == "__main__":
    main()


