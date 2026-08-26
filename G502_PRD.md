# G502 family — Product requirements & plan

Status: living PRD  
Scope: G502 / G502 HERO / G502 LIGHTSPEED / G502 X / G502 X PLUS  
App: Mouser fork (current `3.7.9+`)  
Platform priority: Windows (Lightspeed + wired); Linux/macOS follow same HID++ rules

---

## 1. Goal

Make Mouser useful on G-series gaming mice that **do not expose** `REPROG_CONTROLS_V4` (`0x1B04`):

- Connect reliably on a real HID++ interface
- Remap every button the OS can see
- Control sensor DPI when HID++ allows it
- Be honest in UI when firmware owns a control

Non-goal: replace G HUB for RGB, onboard profile editors, or full flash programming in v1 of this plan.

---

## 2. Current baseline (shipped)

| Capability | State |
|---|---|
| Connect without REPROG_V4 | Shipped (`connect_without_reprog`) |
| Reject Windows VHF WPID stubs | Shipped (was false “connected” with zero features) |
| Prefer Lightspeed `0xC547` / vendor UP | Shipped |
| Require `ADJUSTABLE_DPI` before OS-level connect | Shipped |
| `setSensorDpi` while connected | Shipped |
| OS remap: middle, back, forward, tilt | Shipped |
| Installer `setup-windows.bat` | Shipped |
| Catalog Host-mode comment (optional/risky) | Shipped (Phase A) |
| Hide dead gesture / mode_shift / dpi_switch on G502 | Shipped (catalog + layout note) |
| Status toast: need Lightspeed HID++ / not VHF | Shipped (rate-limited) |
| Restore toast: skip connection-only failures | Shipped |
| Reconnect DPI replay: short settle + verify for OS-level | Shipped (Phase B) |
| Opt-in Host mode for DPI persistence (default off) | Shipped (Phase B) |
| MouseButtonSpy (0x8110) sniper + DPI switch remap | Shipped (Phase C) |
| Spy reapply after sleep / reboot | Shipped (Phase C) |
| Report rate (0x8060) Host-gated | Shipped (Phase D.1) |
| Onboard profiles read-only dump + Scroll UI | Shipped (Phase D.2) |
| Interactive G502 layout (photo + hotspot dots) | Shipped |

Acceptance already met: device dump shows `adjustable_dpi: true` and non-empty HID++ features; DPI slider changes feel; VHF stub no longer claims connect.

---

## 3. Constraints (hardware / protocol)

```
┌──────────────┐     HID++      ┌─────────────────────────┐
│  Mouser      │◄──────────────►│  Real interface         │
│              │  0x2201 DPI    │  C547 receiver / C09x   │
│              │  (optional     │  usage page ≥ 0xFF00    │
│              │   0x8100)      └───────────┬─────────────┘
└──────────────┘                            │
                                            │ onboard profile owns:
                                            │  DPI stages, sniper,
                                            │  DPI± buttons, LEDs
┌──────────────┐     OS HID     ┌───────────▼─────────────┐
│  Mouser OS   │◄──────────────►│  Boot mouse collection  │
│  remap path  │  middle/back/  │  (movement + some btns) │
│              │  forward/tilt  └─────────────────────────┘
└──────────────┘

Windows VHF “HID VHF Driver” (WPID 0x4099, UP 0x59)
→ catalog match only → MUST NOT connect
```

Hard limits without onboard-profile flash writes:

- No REPROG divert → no gesture / mode_shift / dpi_switch via HID++ divert
- DPI± and sniper are consumed onboard → never appear as OS events in default profile
- Host mode (`0x8100` → Host) can make DPI stickier but has reset the mouse (LEDs/link drop) on this hardware path — treat as risky

---

## 4. Quirk backlog (all)

### Q1 — Persistent DPI across sleep / power-cycle

**Problem**  
`setSensorDpi` works while connected; after sleep/reboot onboard profile may restore old DPI.

**User outcome**  
Saved Mouser DPI is reapplied after reconnect and, when safe, survives profile ownership.

**Approach options (ordered)**  
1. **Reconnect replay only** (already partially present) — ensure G502 path always reapplies saved DPI when `dpi_idx` is live; no Host switch.  
2. **Optional Host mode** — probe `0x8100` once at connect; switch to Host only if user opts in (setting); never on every DPI write.  
3. **Onboard profile sector write** (Solaar-style) — edit active profile DPI stages in flash. Highest fidelity; highest risk.

**Acceptance**  
- Change DPI → unplug/replug (or sleep/wake) → sensor DPI matches saved value within 5 s of HID ready  
- Mouse does not drop connect / go dark during normal DPI changes  
- Dump still shows `adjustable_dpi: true` after wake  

**Priority:** P0  
**Risk:** Med (Host), High (flash)

---

### Q2 — DPI up / down + sniper remappable

**Problem**  
Firmware consumes these buttons onboard; OS never sees them, so OS-level remap cannot bind them.

**User outcome**  
Either remap those buttons in Mouser, or UI clearly marks them as onboard-only with a path to enable them.

**Approach options**  
1. **UI honesty** — show DPI± / sniper on G502 layout as “onboard only”; link to docs.  
2. **Onboard profile button map edit** — rewrite profile button behaviors (function vs HID click) via `0x8100` memory write (Solaar profiles).  
3. **MOUSE_BUTTON_SPY (`0x8110`)** — research whether spy notifications expose those CIDs without REPROG; if yes, map to engine actions without divert.

**Acceptance**  
- If spy/profile path works: sniper and DPI± appear in mappings and fire configured actions  
- If not feasible: UI never offers a silent no-op binding; labels say onboard-owned  

**Priority:** P1  
**Risk:** High (flash), Unknown (spy)

---

### Q3 — Gesture / full button divert parity with MX mice

**Problem**  
No `REPROG_CONTROLS_V4` → no HID++ gesture divert, rawXY gesture button, or mode_shift divert.

**User outcome**  
Best available: keep OS remaps; do not fake gesture UI that cannot work.

**Approach**  
1. Keep `gesture_cids=()` for G502 catalog  
2. Hide gesture / mode_shift editors when inventory says unavailable  
3. Optional later: profile-defined “gesture-like” button → HID click that OS remaps  

**Acceptance**  
- G502 UI does not show dead gesture controls  
- Supported buttons remain middle / x1 / x2 / hscroll L/R only unless Q2 unlocks more  

**Priority:** P2  
**Risk:** Low

---

### Q4 — Reconnect “could not restore settings” toast

**Problem**  
Toast fires when saved-settings replay fails (often DPI). False connects and Host-mode disconnects made this noisy.

**User outcome**  
Toast only when a required restore actually failed on a live HID++ session.

**Approach**  
1. Replay DPI only if `dpi_supported`  
2. Never soft-skip silently without logging  
3. If DPI write fails once, retry once; then toast with concrete reason (“DPI write failed”)  

**Acceptance**  
- No toast on healthy reconnect when DPI write succeeds  
- Toast text names which setting failed  
- No toast storm on VHF / waiting-for-connection  

**Priority:** P1  
**Risk:** Low

---

### Q5 — Interface selection / diagnostics

**Problem**  
Wrong interface → empty features → user thinks Mouser “supports” G502 but nothing works.

**User outcome**  
Clear status: connected with features vs waiting vs wrong interface.

**Approach**  
1. Keep VHF reject + DPI-required connect  
2. Status line: “Need Lightspeed HID++ (046D:C547)” when only VHF seen  
3. Device dump always includes path, UP, PID, `adjustable_dpi`, feature list  

**Acceptance**  
- Repro of old VHF dump cannot show Connected  
- Waiting state explains missing HID++ interface  

**Priority:** P1 (polish)  
**Risk:** Low

---

### Q6 — Report rate / other gaming features (stretch)

**Problem**  
`0x8060` report rate and related gaming features are unused.

**User outcome**  
Optional report-rate control when feature present and safe.

**Approach**  
Discover at connect; expose slider only if feature index found; same “no Host churn” rule.

**Priority:** P3  
**Risk:** Med

---

## 5. Delivery plan

### Phase A — Stabilize honesty (no flash writes) ✅

1. Q5 status copy for missing HID++ interface — toast via `STATUS_NEED_LIGHTSPEED_HIDPP`
2. Q3 hide dead gesture/mode_shift/dpi_switch UI on G502 — catalog buttons + layout note
3. Q4 precise restore toast — suppress connection-only; keep DPI failure
4. Catalog comment fix (Host mode is optional/risky, not required for live `setSensorDpi`)

**Exit:** UI matches hardware truth; no false affordances.

### Phase B — Durable DPI ✅

1. Harden reconnect DPI replay for G502 — 1 s settle, read-back verify + rewrite  
2. Behind setting: “Prefer Host mode for DPI persistence” (default **off**)  
3. If Host enabled: switch once at connect / ensure path only; never on each slider tick  
4. Measure on hardware: wake/replug keeps saved DPI without disconnect  

**Exit:** Q1 acceptance with Host opt-in or replay-only if Host still unsafe.

### Phase C — Onboard-owned buttons ✅

1. Spike `0x8110` MOUSE_BUTTON_SPY on G502 X — **done** (nibble Start/zero)
2. Spike read-only onboard profile dump (`0x8100`) — **done** (read-only)
3. Decide: spy path vs profile rewrite vs document as unsupported — **spy path**
4. Implement chosen path + tests — **done** (G502 X map: sniper=bit4, DPI=bit8)
5. Reapply spy remapping after sleep / `0x41` link-up — **done** (hw: survives reboot)

**Exit:** Q2 remappable via runtime MouseButtonSpy (no flash).

### Phase D — Stretch / hardening

1. Report rate (Q6) — **done**: discover `0x8060`; write only when Host opt-in on
2. Read-only active onboard DPI stages in device dump + Scroll UI — **done**
3. Optional profile DPI stage *editor* (flash write) — still out of v1
4. ~~Verify spy remaps survive sleep/wake~~ — **done**

---

## 6. Non-functional requirements

- Tests first for connect/DPI/interface selection regressions  
- Windows installer patch (`setup-windows.bat`) rebuilt on every user-facing HID fix  
- Version bump per shippable slice  
- No Host-mode or flash write on the DPI slider hot path unless behind explicit setting  
- Device dump remains the support contract for “is this the real interface?”

---

## 7. Out of scope (this PRD)

- RGB / lighting  
- Full G HUB profile import  
- Emulating REPROG_V4 that the firmware does not expose  
- Supporting VHF stubs as HID++ endpoints  

---

## 8. Success metrics

- Connect success rate on G502 X Lightspeed without VHF false positives  
- DPI change success without disconnect  
- DPI persistence across wake (Phase B)  
- Zero gesture UI dead-ends on G502 (Phase A)  
- Support dumps always distinguishable: good HID++ vs VHF stub  

---

## 9. Open questions

1. Is Host mode safe on this user’s G502 X if done once at connect only?  
2. Does `0x8110` report sniper / DPI± presses on G502 X firmware?  
3. Wired `0xC099` vs Lightspeed `0xC547` — any feature gap for Phase C?  
4. Should persistence default to “replay only” forever if Host remains flaky?
