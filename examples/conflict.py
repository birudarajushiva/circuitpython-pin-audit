"""A reduced reproduction of the pin allocation conflict found in HackPad.

This is intentionally broken and is parsed only. Do not upload it to a board.
"""
import board
import busio
import keypad

oled_bus = busio.I2C(board.D5, board.D4)
keys = keypad.KeyMatrix(
    row_pins=(board.D0, board.D1),
    column_pins=(board.D2, board.D3, board.D4, board.D5),
)
