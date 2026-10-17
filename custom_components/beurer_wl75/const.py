"""Constants for the Beurer WL75 integration."""

DOMAIN = "beurer_wl75"
MANUFACTURER = "Beurer"
MODEL = "WL75"
LOCAL_NAME = "WL75"

# Disconnect after this many seconds without commands. Frees the proxy slot and
# lets the LightUp app connect (the lamp accepts a single central only).
IDLE_DISCONNECT_SECONDS = 60.0

# Option: poll the state every n minutes, 0 = never. Every poll opens a
# connection; the state is always refreshed after own commands anyway.
CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 0
