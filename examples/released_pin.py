"""Explicit release allows the same symbolic pin to be allocated again."""
import board
import digitalio
import pwmio

with digitalio.DigitalInOut(board.D0) as probe:
    probe.switch_to_input()

output = pwmio.PWMOut(board.D0)
