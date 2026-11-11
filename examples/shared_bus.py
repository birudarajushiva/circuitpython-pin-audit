"""Several device drivers can use a single bus without reallocating its pins."""
import board
import busio

i2c = busio.I2C(board.SCL, board.SDA)
# Driver modules are illustrative and aren't imported or executed by the audit.
sensor = TemperatureSensor(i2c, address=0x40)
display = OledDisplay(i2c, address=0x3C)
