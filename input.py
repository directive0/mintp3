import RPi.GPIO as GPIO
import time
from globals import *

# start the input monitor thread
# a = home, b = previous, c = play, d = next
button_map = {
	"button_a": 12,
	"button_b": 5,
	"button_c": 6,
	"button_d": 13,
}

class ButtonMonitor:
	"""
	Monitors multiple GPIO buttons and returns lists of pressed and held states as booleans.
	"""
	def __init__(self, button_pins, hold_time=.5):
		"""
		Initializes the ButtonMonitor.
		"""
		GPIO.setmode(GPIO.BCM)
		self.button_pins = button_pins
		self.hold_time = hold_time
		self.button_states = {pin: False for pin in self.button_pins.values()}
		self.button_press_times = {}
		
		# Ensure the global structure is nested correctly from the start
		# Index 0: Short Presses [A, B, C, D]
		# Index 1: Long Holds    [A, B, C, D]
		globals.eventlist = [[False, False, False, False], [False, False, False, False]]
		
		for name, pin in self.button_pins.items():
			try:
				GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
				print(f"Successfully initialized {name} on Pin {pin}")
			except Exception as e:
				print(f"CRITICAL ERROR: Failed to initialize {name} on Pin {pin}!")

	def check_buttons(self):
		"""
		Checks the state of the buttons and updates the global event list.
		"""
		# Map pins to indices: A=0, B=1, C=2, D=3
		mapping = {12: 0, 5: 1, 6: 2, 13: 3}

		for pin, was_pressed in self.button_states.items():
			idx = mapping[pin]
			try:
				current_is_pressed = not GPIO.input(pin) 

				if current_is_pressed and not was_pressed:
					# Transition: Not Pressed -> Pressed
					self.button_states[pin] = True
					self.button_press_times[pin] = time.time()
				
				elif not current_is_pressed and was_pressed:
					# Transition: Pressed -> Released (This is where we decide Press vs Hold)
					duration = time.time() - self.button_press_times.get(pin, 0)
					
					if duration >= self.hold_time:
						# It was held long enough to be a Hold
						globals.eventlist[1][idx] = True
					else:
						# It was released quickly, it's a Momentary Press
						globals.eventlist[0][idx] = True
					
					self.button_states[pin] = False
						
			except Exception:
				pass

def button_thread():
	monitor = ButtonMonitor(button_map)
	while True:
		monitor.check_buttons()
		time.sleep(0.01)