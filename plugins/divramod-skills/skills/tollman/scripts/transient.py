"""CI failures that a rerun fixes: the network, a registry, a lost runner, a cancelled job (moved from the farmer's
duties.py by hal2 plan 0360 step 8, D9, D30: a red main and a train's red are the tollman's). triage.py classifies a
train's red run as `runner` by them, mainred.py reruns a transient red main by them."""

import re

TRANSIENT = re.compile(r"ECONNRESET|ETIMEDOUT|EAI_AGAIN|Could not resolve host|TLS handshake timeout|"
                       r"connection (reset|refused|timed out)|50[234] (Bad Gateway|Service Unavailable|Gateway)|"
                       r"rate limit|The runner has received a shutdown signal|lost communication with the server|"
                       r"The operation was canceled|toomanyrequests", re.I)
