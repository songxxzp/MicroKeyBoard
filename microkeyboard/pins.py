import time

from machine import Pin

from microkeyboard.module.pca9555 import I2CPin, PassiveI2CPin


class IRQPin(Pin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._handlers = []
        self.trigger = None
        # self.priority = None
        # self.wake = None
        # self.hard = None

    def irq_handler(self, pin: Pin):
        for handler in self._handlers:
            handler(pin)

    def clear_irq(self):
        self._handlers = []

    # TODO: delete specific irq

    def irq(self, handler=None, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING):
        self._handlers.append(handler)
        if self.trigger is None:
            self.trigger = trigger
        else:
            assert self.trigger == trigger
        super().irq(handler=self.irq_handler, trigger=trigger)

