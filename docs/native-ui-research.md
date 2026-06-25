# SimCity 4 Native UI Research

This document records the verified behavior, resource recipes, failures, and working conventions discovered while building the SC4-3DMouseCam native control laboratory. It is intended to prevent future work from repeating unsafe experiments and to provide a foundation for the production settings and diagnostics windows.

## Current architecture

The test window is a native SimCity 4 UI window. It does not use ImGui and does not require an additional runtime DLL.

- `Dev/ui/SC4-3DMouseCam-TestUI.txt` contains the readable legacy UI script.
- `tools/build_sc4_ui_dat.py` packages that script into an uncompressed DBPF file.
- `Dev/ui/SC4-3DMouseCam-TestUI.dat` is the generated companion resource.
- The Visual Studio post-build step copies the DAT beside the plugin DLL.
- `Dev/src/SC4WindowManager.cpp` owns plugin windows and notification dialogs; its control-laboratory window registers controls, handles notifications, scrolls content, logs interactions, and writes `test.json`.
- `docs/changelog.md` is baked into the first-install greeting window by the DAT builder. The greeting version is read from `Dev/src/PluginVersion.h`, not from the changelog text.

The DBPF resource identifiers are:

| Field | Value |
| --- | --- |
| Type | `0x00000000` |
| Group | `0x3D0C0700` |
| Instance | `0x3D0C0701` |
| Root window CLSID/control ID | `0x3D0C0702` |

The window is instantiated through `cIGZUIScriptService::CreateWindowFromScript`. Controls should be authored in the UI script and then retrieved by ID with `GetChildWindowFromIDRecursive`.

## Window-manager architecture

`SC4WindowManager` is the plugin's single owner and integration point for UI. `Main.cpp` forwards lifecycle and input events to it instead of knowing how individual windows are constructed.

The manager currently owns:

- the baked first-install/version/changelog greeting window;
- the baked Controls help popup opened from the greeting window;
- the native control-laboratory window.

The production settings and diagnostics windows should be added as additional managed window objects. Each window keeps its own control IDs, layout state, and notification handling, while the manager coordinates:

- showing windows and bringing existing instances to the front;
- closing every plugin window during city shutdown;
- reporting whether any managed window is visible;
- routing mouse-wheel input to the window beneath the pointer;
- creating basic SC4 notification dialogs through the verified native wrapper.

This keeps game lifecycle policy in one place and prevents `Main.cpp` from accumulating window-specific resource IDs or control behavior.

The public factory supports three creation forms:

```cpp
manager.CreateManagedWindow();
manager.CreateManagedWindow(SC4BasicWindowOptions{ /* ... */ });
manager.CreateManagedWindow(SC4WindowTemplate::ControlLaboratory);
```

The parameterless form creates a blank 420-by-240 window with only the native X close button. Basic-window options accept a clamped width and height, title, wrapped body text, and one of four button arrangements: X only, OK, Close, or Accept. The latter three retain the X and add the named footer button.

The factory returns an `SC4WindowHandle`; zero (`InvalidSC4WindowHandle`) indicates failure. The manager retains ownership and accepts the handle in `CloseWindow`. Named templates are used for windows with specialized controls or behavior. The control laboratory is the first registered template; Settings and Diagnostics should follow the same pattern.

Basic windows are instantiated from the generic `SC4-3DMouseCam-BasicUI.txt` resource packed into the companion DAT. Runtime customization uses captions, `SetSize`, and relative `GZWinMoveTo` anchoring; it does not use either unsafe `SetArea` overload.

Important caveat: runtime customization is not yet as reliable as baked script layout. A dynamically populated basic window appeared as a blank shell or ignored runtime size/caption changes in-game. For user-facing windows that must work on first load, prefer a dedicated baked UI resource and follow the control-laboratory pattern: create from script, add to the SC4 parent, center using `rootWindow->GetW()`/`GetH()`, set the winproc, then show.

## Resource and build behavior

The UI DAT is a required runtime resource, unlike the user settings JSON files. The JSON files are created by the plugin as needed and must not be copied by the build.

The DBPF writer currently emits:

- a 96-byte DBPF header;
- UTF-8 legacy UI scripts as uncompressed resources;
- one 20-byte index entry per resource.

The packager currently emits three resources in the same type/group:

| Instance | Purpose |
| --- | --- |
| `0x3D0C0701` | Native control laboratory |
| `0x3D0C0703` | Generic basic-window template |
| `0x3D0C0705` | First-install greeting/changelog window |
| `0x3D0C0707` | Controls help popup |

The packager also substitutes the verified ordinance-style checkbox recipe and bakes `docs/changelog.md` into the greeting resource. The greeting heading is generated as `SC4-3DMouseCam v{PluginVersion::String} installed!`, so the version number remains centralized in `Dev/src/PluginVersion.h`. Keeping these transformations in the build step allows readable source files to remain easy to edit while preserving the exact native bitmap and text configuration that SC4 expects.

## UI script coordinates

Legacy UI `area` values are edges:

```text
area=(left, top, right, bottom)
```

They are not `(left, top, width, height)`. Treating the last two values as dimensions produced invalid layouts and, in some cases, parser or runtime crashes.

Child coordinates are relative to the root window. The current root is 570 by 600 pixels.

Caption attributes are literal strings. SC4's UI parser does not HTML/XML-decode text entities in captions; `&amp;` displays as `&amp;`, not `&`. Preserve plain ampersands in authored text. Only avoid or replace characters that would break the quoted attribute itself, such as double quotes and angle brackets.

## Window layout convention

The test window now has three logical bands:

- Header: title and the native X close control.
- Content viewport: vertically scrolling controls, from local Y 108 through 530.
- Footer: the background divider and a conventional full-width Close button.

The native root background contains a lower divider. It should be treated as a footer seam rather than allowing content to overlap it.

SC4 does not reliably clip child windows to a parent or viewport. A scrolling control is therefore shown only when its entire rectangle fits inside the content viewport. Partially visible controls are hidden. This avoids text, borders, and option-group outlines drawing through the header or footer.

## Verified control recipes

### Standard button

The normal SC4 button atlas currently used by the laboratory is:

```text
image={46a006b0,144161eb}
style=standard
```

### Native title-bar X button

The small close control used by native SC4 dialogs is:

```text
area=(..., ..., ...+22, ...+20)
image={46a006b0,144161f9}
showcaption=no
style=standard
tiptext="Close"
btnclicksnd={00000000,ca5c3239}
```

It is a normal `GZWinBtn`, not special window chrome. Give it its own unique control ID and handle it like any other close button.

### Ordinance-style checkbox

A checkbox is not a wide standard button with `style=radiocheck`. That combination indexes the wrong state atlas and can expose uninitialized or back-buffer pixels, producing scenery-dependent distortion.

The verified pattern is a small bitmap button plus a separate text label:

```text
clsid=GZWinBtn
area=(28,178,48,200)
image={46a006b0,14416245}
toggle=on
showcaption=no
style=radiocheck
```

The label is a mouse-transparent `GZWinText` beside the 20-by-22-pixel button. This matches the checkbox/X presentation used by the game's Ordinances window.

### Option group

`GZWinOptGrp` works with manually defined `option`, `optionmoveto`, and `optionsetsize` values. Its outline is drawn as part of the control and must remain wholly inside the content viewport; otherwise it visibly crosses fixed dividers.

### Sliders and scrollbars

Both horizontal and vertical native controls instantiate and render successfully from UI script resources. The laboratory's content scrollbar is a fixed control; the rest of the controls move beneath it.

The vertical scrollbar currently uses:

```text
minmaxvalue=(0,600)
direction=vertical
pagesize=80
linesize=20
image={46a006b0,46a006a6}
```

## Notifications observed

The root window receives command messages with `dwMessageType == 3`.

| Control/action | `dwData1` | `dwData2` | `dwData3` |
| --- | --- | --- | --- |
| Button click | `0x287259F6` | Control ID | varies/unused |
| Option-group selection | `0x88710F1C` | Control ID | Selected option (1, 2, ...) |
| Slider/scrollbar interaction | `0x887113A3` | Control ID | observed as 0 |

Buttons also emit additional state messages ending in F7, F8, and F9. These are useful diagnostic data but should not be treated as completed clicks.

`GZWinOptGrp` also creates anonymous internal option buttons. They emit button-state notifications with control ID `0` (observed as `0x287259F7`) immediately before the owning option-group selection notification. The laboratory records these as `optionGroupInternalButton`.

Only `DoWinProcMessage` should perform event handling. Forwarding both `DoWinMsg` and `DoWinProcMessage` created duplicate interaction records.

Every laboratory interaction is written to the normal plugin log and serialized into `Plugins/SC4-3DMouseCam/test.json`.

## Scrollbar handling

The SDK does not currently expose a verified concrete scrollbar interface that safely returns its value. The generic command message also reports `dwData3 == 0`.

The working laboratory implementation therefore maps the cursor position to a logical scroll offset:

- clicking the upper/lower arrow zones moves by 40 pixels;
- clicking or dragging the track maps its cursor ratio to the 0-600 content range;
- turning the mouse wheel while the pointer is inside the window activates the corresponding native scrollbar arrow;
- all scrolling inputs call the same `ApplyScrollPosition` path.

`WM_MOUSEWHEEL` coordinates are screen-relative. The canvas Win32 filter converts them to canvas-client coordinates, hit-tests the native root window, and forwards the wheel delta only when the pointer is inside it. Wheel input outside the window remains available to the city camera. Partial high-resolution wheel deltas are accumulated until they form a standard 120-unit notch.

Each completed wheel notch is translated into the same native arrow-button input used by the scrollbar itself. SC4 updates the thumb, and the resulting scrollbar notification moves the content by the matching 40-pixel line size. This avoids maintaining independent content and thumb positions.

This keeps the scrollbar thumb and content movement coupled without calling an unverified virtual method.

`GZWinMoveTo(x, y)` is misleadingly named: it applies a relative delta rather than moving to an absolute position. To make scrolling deterministic, calculate:

```text
deltaX = baseLeft - currentLeft
deltaY = desiredTop - currentTop
```

and pass those deltas to `GZWinMoveTo`. Passing absolute coordinates causes controls to drift farther on every scroll operation.

## Calling-convention and SDK hazards

SC4 is a 32-bit application, so a wrong calling convention or virtual signature corrupts the stack immediately. Debug builds report this as `_RTC_CheckEsp`; release builds may simply crash.

Verified startup popup wrapper:

```cpp
bool (__cdecl*)(cIGZString const& caption, cIGZString const& message)
```

at game address `0x78DD80`. Ignore the Boolean return value. A `__stdcall` declaration caused an ESP mismatch after dismissing the popup.

The following SDK declarations or reverse-engineered paths have proven unsafe in this context and must not be used until their ABI is verified:

- `cIGZWinCtrlMgr` programmatic control factories; `CreateLabel` caused a stack-balance failure.
- `cIGZWin::SetArea(cRZRect)`.
- `cIGZWin::SetArea(left, top, right, bottom)`.
- `CenterWindowInRect()`.

Manual centering is safe when the required movement is expressed as a relative `GZWinMoveTo` delta.

Safe geometry queries used by the laboratory are `GetL`, `GetT`, `GetR`, and `GetB`.

## Lifecycle and input behavior

The first-install/changelog popup is a baked native SC4 window generated from `docs/changelog.md`. It is displayed during the first city load for a newly installed plugin version. Controls are intentionally kept out of the changelog body; the greeting window has a `View Controls` button that opens a smaller baked controls popup.

Creating the managed greeting immediately during city-load notification caused a crash. Deferring it by a short Win32 timer, currently 3 seconds, allowed the city view and UI hierarchy to finish initializing before the plugin created its own window.

The control laboratory is created only after the UI services and city view are available. While it is visible, camera input is suppressed so clicks and drags intended for controls cannot move the city camera.

The root window and its controls should be reused by showing/hiding them. Avoid reconstructing the entire hierarchy during ordinary interaction.

## Persistence files

Runtime files are located in the `SC4-3DMouseCam` subfolder beside the plugin DLL. The plugin discovers that location dynamically rather than assuming a Documents path:

- `SC4-3DMouseCam.json`: persistent user settings and installed-version marker.
- `test.json`: control-laboratory event/state output.
- `SC4-3DMouseCam.log`: plugin log.

These files are generated at runtime and are not build artifacts. Existing root-level files from earlier development builds are migrated into the subfolder before the logger or settings system opens them. The DLL and companion UI DAT remain in the Plugins root.

## Research sources

The repositories and game resources that informed this work include:

- `0xC0000054/sc4-region-census`, especially its native UI DAT and close-button definition;
- the game's `SimCity_1.dat`, used to find native ordinance checkbox resources;
- `0xC0000054/sc4-dll-utilities` and the bundled GZCOM headers for service and plugin patterns.

## Production-window recommendations

For the settings and diagnostics UI:

1. Author controls in a companion UI DAT and retrieve them by stable IDs.
2. Use a fixed header, fixed native X, fixed footer, and one content viewport.
3. Keep a full Close or Back button in the footer for discoverability.
4. Use the verified small bitmap checkbox with a separate label.
5. Hide partially visible scrolling controls instead of depending on clipping.
6. Route every scroll input through one offset and layout function.
7. Log raw notifications for any newly introduced control before assigning semantics.
8. Do not call an SDK virtual method until its 32-bit ABI has been verified against the game.

## Open questions

- The concrete slider, spinner, text-edit, option-group, and scrollbar interfaces still need ABI-safe method declarations before values can be queried directly.
- Direct ABI-safe access to a native scrollbar's numeric value has not yet been confirmed; wheel input currently activates its native arrow controls.
- Keyboard focus, tab order, and accessibility behavior need a dedicated pass.
- The final settings window should replace laboratory-only controls and remove `test.json` event recording.
