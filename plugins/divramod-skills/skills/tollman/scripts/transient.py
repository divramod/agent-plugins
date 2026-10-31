"""CI failures that a rerun fixes: the network, a registry, a lost runner, a cancelled job (moved from the farmer's
duties.py by hal2 plan 0360 step 8, D9, D30: a red main and a train's red are the tollman's). triage.py classifies a
train's red run as `runner` by them, mainred.py reruns a transient red main by them, train_red.py retries a red
landing without a run (a carrier push the network cut, L51) by them.

Plan 0490 step 9 added: a connection git's ssh lost (L51), Apple's codesign timestamp service (L59), a cloud
provider without capacity (L68: Hetzner's `resource_unavailable`, `placed no cx33 in ...`).

MAC is this Mac's own fault, not a car's and not a runner's: a Homebrew tool whose library an upgrade replaced (dyld
`Library not loaded`, L101). The pretest (pretest_jobs.py) never calls such a red a car's; it stays out of TRANSIENT,
as a CI runner's image is no Homebrew of this Mac and a car can break a link there."""

import re

TRANSIENT = re.compile(r"ECONNRESET|ETIMEDOUT|EAI_AGAIN|Could not resolve host|TLS handshake timeout|"
                       r"connection (reset|refused|timed out)|50[234] (Bad Gateway|Service Unavailable|Gateway)|"
                       r"rate limit|The runner has received a shutdown signal|lost communication with the server|"
                       r"The operation was canceled|toomanyrequests|"
                       r"closed by remote host|early EOF|unexpected disconnect|"
                       r"The timestamp service is not available|A timestamp was expected but was not found|"
                       r"resource_unavailable|placed no [\w.-]+", re.IGNORECASE)
MAC = re.compile(r"dyld(\[\d+\])?: Library not loaded: \S+|Library not loaded: (/opt/homebrew|/usr/local)/\S+")
