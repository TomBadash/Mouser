# Windows remote desktop sessions

By default, Mouser pauses all input handling when its own Windows session is
connected through RDP. The connecting computer handles mouse mappings; the
remote copy does not reverse scrolling, consume mouse buttons, execute volume
actions, or inject shortcuts. Windows still receives input the client forwards.

The **Point & Scroll → Remote Desktop → Automatically pause Mouser in remote
desktop sessions** switch is enabled by default. When checked, it applies the
pause behavior described above. When unchecked, Mouser keeps the previous remote
behavior, including device discovery and input processing under the existing
device and manual-enable conditions. It does not selectively filter RDP input
or distinguish it from physically connected mouse input.

Changing the switch takes effect immediately, including inside an existing RDP
session, and the choice is saved across restarts. Mappings, scroll preferences,
and the manual remapping toggle are preserved. The main window and settings
remain available while paused. Edited settings take effect on the next resume,
whether by unchecking the switch or returning to the local console.

| Scenario | Expected behavior with auto-pause enabled |
| --- | --- |
| Start on the local console | Run with saved mappings and scroll direction |
| Start inside RDP | Do not start input hooks, HID interception, or foreground-app detection |
| Local session transfers to RDP | Stop input processing and HID polling; release simulated held mouse buttons and discard pending actions |
| Disconnect and reconnect RDP | Stay paused; do not repeat the warning |
| Return to the local console | Restore saved behavior automatically |
| Change mappings or scroll direction while remote | Save preferences without activating input processing |
| Disable auto-pause while remote | Resume the old behavior; preserve the manual enable/disable choice |
| Multiple users/sessions | Inspect the current process's session only |
| Local Windows instance connects to another PC | The local instance remains active; the RDP-hosted instance pauses |
| Nested RDP | Each RDP-hosted instance pauses |
| Session detection is temporarily unavailable | Pause until a console session can be confirmed; retry automatically |
| macOS/Linux or non-RDP console sharing tools | Keep existing behavior |

The UI shows a persistent paused banner and tray tooltip, plus one non-blocking
warning per remote period. The warning latch resets only after a confirmed local
session. The process stays alive so it can resume without restarting the app.

Detection uses `WTSQuerySessionInformationW(WTSClientProtocolType)` for the current
session (console `0`, RDP `2`). A positive `SM_REMOTESESSION` is a fallback; a
negative metric alone is insufficient to identify a local RemoteFX session.
WTS session notifications trigger immediate checks, with a one-second timer as
a fallback. No per-mouse hook callback makes blocking WTS calls.

Automated coverage includes both axes' four inversion combinations, remote
startup, local/remote transitions, opt-out, unknown session detection, stale
callbacks, held-button cleanup, and queued scroll cleanup. Manual verification
should connect/disconnect RDP and return to console using the same running app,
checking that only the client maps input and the warning does not repeat.

## Extension boundary

Connection detection stays separate from pause policy and runtime start/stop:
`core/remote_session.py` reports the current state, `core/engine.py` applies the
saved auto-pause choice, and `ui/windows_session_monitor.py` requests refreshes.
The engine does not query WTS directly or inspect remote-control processes.

Future integrations should fit behind the detection interface and supply their
own change notifications. Provider-specific status, affected desktop/session,
and pause reasons can be added through a richer detection result with a
compatibility wrapper; callers should not need to know each provider's API.
An unsupported optional provider must not be treated as the existing unknown
RDP state or pause the runtime merely because its server process is present.

Console-sharing tools may share the local desktop rather than create an RDP
session, so their connection status and input provenance are separate concerns.
Do not assume that discovering a physical mouse identifies the source of every
input event. The auto-pause choice remains independent of such future detection.

Threading follows the shared state, not the number of remote sessions. The
lifecycle lock serializes start, stop, and policy refresh. The mouse-button lock
protects injected presses, safety timers, and pause cleanup. Their acquisition
order is lifecycle then mouse-button, never the reverse; input/timer workers
must not acquire the lifecycle lock, because shutdown waits for those workers.

WTS notifications, polling, and settings changes currently run on the Qt thread.
Future background detectors should queue a refresh onto that same owner thread,
not start/stop the runtime or mutate its state directly. The engine then reads
the current detection snapshot under the lifecycle lock. If detection later
becomes asynchronous, stale results must be rejected before policy is applied;
a mutex alone does not make an old observation current. UI callbacks must remain
non-blocking and queued, as the current backend's session notification is.

This is an interface boundary only. No additional providers, detection heuristics,
configuration options, or per-event filtering are implemented in this change.
