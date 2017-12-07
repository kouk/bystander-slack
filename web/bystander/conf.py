INCOMING_TOKEN = "XXXXXXX"
OUTGOING_TOKEN = "XXXXXXX"
EXPIRE_SECONDS = 60 * 60
TIMEOUT_SECONDS = 2 * 60
REDIS_HOST = 'redis'

try:
    from .conf_private import *  # noqa
except ImportError:
    pass
