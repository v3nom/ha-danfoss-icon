"""Constants for the Danfoss Icon integration."""

from typing import Final

DOMAIN: Final = "danfoss_icon"

CONF_PRIVATE_KEY: Final = "private_key"
CONF_PEER_ID: Final = "peer_id"
CONF_HOUSE_NAME: Final = "house_name"
CONF_OTP: Final = "otp"
CONF_USER_NAME: Final = "user_name"

DEFAULT_USER_NAME: Final = "Home Assistant"

MIN_TEMP: Final = 5.0
MAX_TEMP: Final = 35.0
TEMP_STEP: Final = 0.5
