# Normalized actuator requests, not SI velocity or steering angle.
# throttle: [-1, 1], positive = forward, negative = reverse.
# steering: [-1, 1], positive = left, negative = right.
# Zero throttle requests ESC neutral; it does not guarantee active braking.
# Calibrate hardware direction and neutral before driving.
float32 throttle
float32 steering
