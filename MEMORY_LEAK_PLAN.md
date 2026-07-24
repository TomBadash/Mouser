# Memory Problem — Consolidated Status & Action Plan

*Last updated: 2026-07-21 (master @ `7bae4d5`, app version 3.7.0).*

This document arranges every issue and PR that refers to the long-running
memory-growth problem, records what each one proved, and lays out the plan for
the remaining work. The problem is macOS-specific in every confirmed report;
the leaked memory is native (Foundation/Quartz/IOKit), not Python objects.

---

## 1. Inventory

### Issues

| Issue | Title | State | Status |
|---|---|---|---|
| [#150](https://github.com/TomBadash/Mouser/issues/150) | High memory usage, 1.29 GB (macOS 26, MX Master 4, BLE) | **Closed** | Fixed by PR #151 (bounded dispatch backlog), merged 2026-05-12. |
| [#233](https://github.com/TomBadash/Mouser/issues/233) | High memory usage, grows over time / with click count (v3.6.0–v3.7.0, MX Master 2S/3S, Bluetooth; 4 reporters) | **Open** | Partially fixed by PR #242 (click path confirmed fixed). **Scroll path still leaks** (~7–8 MB/min while scrolling); one tester still hits 700 MB in ~4.5 h on the PR-242 build. |
| [#238](https://github.com/TomBadash/Mouser/issues/238) | Repeated HID reconnects leak `IOHIDManager` objects + Mach ports → 3.3 GB (macOS 26.4.1, MX Master, BLE) | **Open** | Core leak fixed by PR #240 and **validated on-device** (managers pinned at 2, ports 67,862 → 2,646). A separate `HIDEvent`/`CGEvent`/`GPProcessMonitor` retention path remains (~926 MB after 20 h). |

Near-matches excluded from scope: #134 (Win ARM64 native build — battery/architecture request), PR #180 (DPI persistence), PR #212 (G602 catalog). They matched the keyword search only.

### Pull requests

| PR | Title | State | Addresses | Outcome |
|---|---|---|---|---|
| [#125](https://github.com/TomBadash/Mouser/pull/125) | `@_autoreleased` on CGEventTap callback + `get_foreground_exe` | **Merged** 2026-04-24 | ~1.4 GB / 2-day leak | Fixed event-tap *ingestion* and added a pool to the app poller. `GPProcessMonitor` still accumulates despite the pool (see §2.3). |
| [#151](https://github.com/TomBadash/Mouser/pull/151) | Bound hook dispatch backlogs (512-entry queue, drop-oldest) | **Merged** 2026-05-12 | #150 | Prevents unbounded Python-side event backlog. Cross-platform. |
| [#240](https://github.com/TomBadash/Mouser/pull/240) | Close `IOHIDManager` + exception-safe open/close + reconnect backoff + REPROG_V4 probe cooldown | **Open** | #238 | **Validated** by two testers (maxhis 20 h run, mizi 32 h run). Manager/port explosion resolved. Residual growth is a different signature. |
| [#242](https://github.com/TomBadash/Mouser/pull/242) | Autorelease pools on action-execution threads (`_dispatch_worker`, `key_simulator` injection entry points) | **Open** | #233 | **Validated for clicks** (click-only burst: +4 MB ≈ noise, vs. clear growth on v3.7.0). **Not sufficient**: scroll-only test still leaks +19 MB / 2.5 min. |
| [#243](https://github.com/TomBadash/Mouser/pull/243) | Split macOS daemon from on-demand Qt UI | **Open (draft)** | Baseline footprint (complementary to the leaks) | Resident process drops ~280 MB → ~48 MB by keeping the PySide6 runtime out of the daemon. Substantial architectural change; author requests maintainer feedback on IPC/packaging. |

### How they relate

```
#150 (closed) ── fixed by ── #151 (merged)          Python-side backlog, done
#233 (open)  ─┬─ partially fixed by #242 (open)     click path ✅, scroll path ❌
              └─ remaining: HID read-loop pool      → Phase 1 below
#238 (open)  ─┬─ core leak fixed by #240 (open)     managers/ports ✅, validated
              └─ remaining: HIDEvent/GPProcessMonitor retention → Phases 1–2 below
#125 (merged) ── same residual signature persists on macOS 26.4.1 → Phases 1–2
#243 (draft)  ── independent baseline reduction     → Phase 4 below
```

The residual growth reported on **both** open issues after their respective fix
PRs has the **same heap signature**, so #233 and #238 converge on the same
remaining root causes.

---

## 2. Evidence synthesis — what is actually still leaking

Post-fix test data (maxhis' 20 h heap capture on the #240 build; bdhwrsh's
10 h sampling on the #242 build):

| Retained class | Count / size after 20 h | Likely source |
|---|---|---|
| `HIDEvent` | 1,572,804 / 168 MB | IOHID input reports delivered on the HID gesture thread |
| `CGSEventAppendix` + `CGEvent` | ~524k / 96 MB | Quartz event machinery on un-pooled threads |
| `GPProcessMonitor` → `NSXPCConnection`, `dispatch_queue_t`, … | 8,892 monitors; `leaks` ROOT LEAK, 19.5 MB + supporting tree | `NSWorkspace.frontmostApplication()` polling |
| `IOHIDManager` | **2 (stable — fixed by #240)** | — |

Behavioral measurements on the #242 build (bdhwrsh, macOS 27 beta, MX Master 3S):

- Idle/asleep 8 h: **flat** (536 MB, zero growth).
- Active use: **~110 MB/h** linear growth.
- Scroll-only 2.5 min: **+19 MB**. Click-only ~100 presses: +4 MB (noise).
- Their config diverts the hi-res wheel (`0x2121`, mul=15) and thumb wheel
  (`0x2150`, divertedRes=120) — wheel events arrive at far higher rates than
  clicks, and each diverted notification is an IOHID input report.

### 2.1 Remaining root cause A — HID read-loop pump has no autorelease pool

`_MacNativeHidDevice.read()` pumps the run loop on the **HID gesture thread**
(`core/hid_gesture.py:700`, `CFRunLoopRunInMode` in 0.05 s slices) and input
reports are delivered into `_on_input_report` (`core/hid_gesture.py:670`)
inside that pump. Nothing on that thread ever drains an autorelease pool on
master:

- PR #125 pooled the *CGEventTap* callback thread — different thread.
- PR #242 pools the injection entry points (`execute_action`,
  `inject_scroll`, …) — coverage starts only *after* the gesture recognizer
  decides to act. The per-report Foundation/IOKit temporaries created by the
  run-loop delivery itself (the `HIDEvent` cluster) are never drained.

This precisely fits "scroll leaks, clicks don't" on the #242 build: every wheel
detent produces ~15 diverted reports through this pump. It was explicitly
declared out of scope in #240 ("native read-loop pool… can follow separately").
Note that `7bae4d5` (#244) made hi-res scroll *survive* reconnects, which
increases diverted-wheel traffic — making this fix more urgent, not less.

### 2.2 Remaining root cause B — un-pooled auxiliary threads (defense in depth)

Longer-interval engine threads (battery poll every 1800 s, smart-shift poll
every 300 s, reconnect loop) touch HID/Foundation without pools. Low rate, so
they are not the main driver, but they should be wrapped while we are at it so
no macOS thread that crosses into native frameworks is left bare.

### 2.3 Remaining root cause C — `GPProcessMonitor` XPC tree from 0.3 s app polling

`AppDetector` calls `NSWorkspace.frontmostApplication()` every 0.3 s
(`core/app_detector.py:364`, poll loop at `:384`) — ~288,000 calls/day. The
call has been pool-wrapped since #125, yet `leaks` still reports the
`GPProcessMonitor` tree as a ROOT LEAK: the retention is inside the framework's
XPC machinery, so pooling alone cannot reclaim it. The only robust mitigation
is to make detection **event-driven** (NSWorkspace
`didActivateApplicationNotification`) so the call count collapses from ~288k/day
to the number of actual app switches.

### 2.4 Open discrepancy to resolve during validation

skinnyshy reports ~430 MB/h growth on the #242 build "even on standby", while
bdhwrsh measured a flat idle. Possible explanations: different idle definitions
(display asleep vs. machine in use but untouched), BLE reconnect cycles during
standby (the #240 fix is **not** in the #242 branch — the two builds each carry
only their own fix), or diverted-wheel traffic from incidental motion. First
validation step in Phase 1 is a build containing **both** fixes to remove this
confound.

---

## 3. Action plan

### Phase 0 — Land the validated fixes (immediately)

1. **Merge #240** (`fix/238-macos-hid-manager-leak`). Two independent on-device
   validations confirm the manager/port leak is gone; the residual growth is a
   separate signature. Rebase on master first — both #240 and #244 touch
   `core/hid_gesture.py`.
2. **Merge #242**. The click-path fix is confirmed by A/B measurement; it is
   strictly an improvement. Note in the merge comment that #233 stays open for
   the scroll path.
3. **Open a new focused issue** — "macOS: HIDEvent/CGEvent/GPProcessMonitor
   retention on long-running sessions" — capturing §2's residual signature and
   linking #233/#238 (maxhis already offered to track it separately). Close
   #238 once #240 is merged, pointing to the new issue for the remainder;
   keep #233 open until Phase 1 is validated.
4. Ask testers to hold further long-run measurements until a master build
   contains both merges (removes the confound in §2.4).

### Phase 1 — Fix the read-loop leak (target: v3.7.1 hotfix; closes #233)

5. **Pool the HID read-loop pump**: drain an autorelease pool around the
   `CFRunLoopRunInMode` pump in `_MacNativeHidDevice.read()`
   (`core/hid_gesture.py:691-710`). Draining once per `read()` call bounds the
   cost (the call already returns at ≤0.05 s granularity); if profiling shows
   pool-churn overhead at high wheel rates, drain every N iterations instead.
   Implementation detail: this file uses raw `ctypes`, not PyObjC — either
   reuse `objc.autorelease_pool()` guarded by availability (as `key_simulator`
   does in #242), or bind `NSAutoreleasePool` via `ctypes`/`objc_msgSend` so the
   native backend keeps working without PyObjC.
6. **Wrap the gesture-thread report-consumption loop and the auxiliary
   threads** (§2.2) with the same helper: reconnect loop, battery poll,
   smart-shift poll. One shared decorator, applied at thread entry points.
   > **Status:** steps 5–6 are implemented on this branch — `core/hid_gesture.py`
   > now binds `NSAutoreleasePool` via `libobjc` (ctypes, no PyObjC dependency,
   > graceful no-op fallback) and drains a pool around each
   > `CFRunLoopRunInMode` pump iteration in `read()` plus the
   > `enumerate_infos`/`open`/`write`/`close` entry points, covering every
   > thread that crosses into IOKit/Foundation at the choke point. Awaiting
   > on-device validation (step 7).

7. **Validate** with the reporters' existing protocols (they have offered):
   bdhwrsh's scroll-only vs. click-only A/B plus 10 h footprint sampling;
   maxhis' `heap -s`/`leaks --groupByType` before/after — expected result:
   `HIDEvent` count bounded, scroll-only delta ≈ click-only delta ≈ noise.
8. **Release v3.7.1** with #240 + #242 + this fix once two reporters confirm
   flat memory over ≥24 h.

### Phase 2 — Eliminate the `GPProcessMonitor` accumulation (v3.8)

9. Replace the 0.3 s macOS poll in `AppDetector` with
   `NSWorkspace.didActivateApplicationNotification` (event-driven; keep the
   poll as a fallback and on Windows/Linux where no equivalent leak exists).
   Per-app profiles keep working identically — `_on_change` semantics are
   unchanged, only the trigger differs.
10. Re-validate with `leaks --nostacks --groupByType`: the ROOT LEAK
    `GPProcessMonitor` tree should stop growing entirely.

### Phase 3 — Bound, observe, and prevent regressions

11. **Lightweight memory self-reporting**: log process footprint (macOS
    `phys_footprint` via `task_info`, RSS elsewhere) at startup and hourly at
    debug level. Every future report then carries the growth curve in the log
    file users already attach to the issue template.
12. **Regression tests**: extend #240's throttle tests with a high-rate
    synthetic wheel-report replay through the recognizer asserting bounded
    Python-side object counts; document the macOS-only manual checklist
    (`vmmap`/`heap`/`leaks` stress steps from #238) in `DEVELOPMENT.md` as a
    release gate, since CI runners are Linux and cannot exercise
    IOKit/Foundation paths.
13. Track an upstream radar/feedback for the `GPProcessMonitor` framework leak
    (it reproduces with a pooled caller on macOS 26.4.1/27 beta) so it can be
    linked from the code comment.

### Phase 4 — Baseline reduction (v3.8+, independent track)

14. **Review draft #243** (daemon/UI process split, ~280 MB → ~48 MB resident).
    This attacks the *baseline*, not the leaks, and is complementary. Requested
    feedback for the author: IPC auth/packaging boundaries, signing
    implications for the nested helper app, and a rebase once Phase 0–1 fixes
    land. Substantial change from a first-time contributor — schedule a real
    review rather than letting the draft go stale.

### Sequencing summary

| Order | Work | Vehicle | Closes |
|---|---|---|---|
| Now | Merge #240, #242; open residual-leak issue | existing PRs | #238 (core) |
| Next | Read-loop + thread pools (§Phase 1) | new PR → v3.7.1 | #233, residual issue (HIDEvent part) |
| Then | Event-driven app detection (§Phase 2) | new PR → v3.8 | residual issue (GPProcessMonitor part) |
| Parallel | Footprint logging + regression tests (§Phase 3) | new PR → v3.8 | — |
| Parallel | #243 review/iteration (§Phase 4) | draft PR → v3.8+ | — |

---

## 4. Verification protocol (shared by all phases)

Reproducible measurement commands, standardized from #238 so all reporters
produce comparable numbers:

```bash
PID="$(pgrep -x Mouser)"
top -l 1 -pid "$PID" -stats pid,command,cpu,mem,ports,threads,time
vmmap -summary "$PID"
heap -s -H "$PID"
leaks --nostacks --groupByType "$PID"
```

Acceptance criteria for calling the memory problem fixed:

- `IOHIDManager` count constant (2) across reconnect storms — *already met by #240*.
- Mach ports return near baseline after reconnect activity — *substantially met by #240*.
- `HIDEvent`/`CGEvent` counts bounded during sustained scrolling — *Phase 1*.
- `GPProcessMonitor` ROOT LEAK stops growing — *Phase 2*.
- Physical footprint flat (±50 MB) over 24 h of active use on BLE — *overall*.
