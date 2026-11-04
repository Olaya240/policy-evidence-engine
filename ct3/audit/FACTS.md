# Pending facts for the coordinator to store

A subagent in this session had no `local_memory__*` tool bound, so these are
written here rather than claimed as stored. Store them verbatim, or discard after
transferring to the store.

```
s: policy-evidence-engine BoundedTransportProvider._assess_async
p: DUPLICATES_TIMEOUT_CHECK
o: the five-line timeout validation appears twice verbatim immediately before
   _TRANSPORT_SINGLE_FLIGHT.acquire; the second copy is dead
source: project:verification
```

```
s: policy-evidence-engine provider dispatch timeout
p: EXCLUDES_PARSING
o: asyncio.wait_for wraps only the network hop and body read; _parse_response
   runs after it, so parsing is unbounded by the timeout and bounded only by
   MAX_RESPONSE_BYTES
source: project:verification
```

```
s: policy-evidence-engine _TRANSPORT_SINGLE_FLIGHT
p: REJECTS_RATHER_THAN_QUEUES
o: acquired with blocking=False, so a concurrent caller gets concurrent_request
   instead of waiting; admission control, not mutual exclusion
source: project:verification
```
