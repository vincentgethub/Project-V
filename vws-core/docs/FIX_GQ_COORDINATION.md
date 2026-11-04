# Paper broker coordination

`vws start` refuses while a stuck-intent dry run holds `runtime.lock`, including
its 60-second evidence wait. The dry run also holds all eight broker-actor slots
and checks the invocation epoch after its final evidence snapshot. A changed or
incomplete inventory, occupied slot, abandoned mutex or adapter error refuses
with `FIX_G_QUIESCENCE_UNVERIFIED`.

Panic never acquires `runtime.lock`. It uses a free nonblocking actor slot if
available and proceeds when all slots are occupied. Each later physical worker
probes again if its invocation has no slot. Separate invocations have separate
leases and durable BEGIN/END records. A physical worker outliving its caller
keeps its invocation incomplete until actual physical exit; coroutine completion
alone cannot certify quiescence. An incomplete invocation is explained by doctor;
there is no automatic expiry, marker removal, or new reset mechanism.

This is the owner-approved paper residual-risk contract, not an unconditional
proof: simultaneous observation/publication failure can hide panic, and durable
filesystem operations have no demonstrated latency bound. Coordination cannot
be a reason to skip an emergency broker operation. No live unlock is granted.
