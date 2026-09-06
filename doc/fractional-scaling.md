# Native fractional client scaling

XLibre exposes an opt-in, per-output rendering scale through the RandR output
property `_XLIBRE_OUTPUT_SCALE`. Participating clients lay out their UI in local
logical units and rasterize text and graphics directly at the requested pixel
size. For example, a 360 × 240 logical-unit window at 125% uses a 450 × 300 pixel
window and backing buffer. There is no intermediate 200% bitmap or downsampling
pass in this path.

This is a new XLibre client convention, not a standard X11 extension or automatic
scaling of existing applications. Toolkits and window managers must implement
it. X11 window geometry, pixmap sizes, input coordinates, root coordinates, and
Present/DRI buffers remain in X pixels. Unlike Wayland, the server does not expose
a separate logical surface coordinate space. Applications own that conversion.
The 1/120 representation follows the precision used by Wayland's
[fractional-scale protocol](https://gitlab.freedesktop.org/wayland/wayland-protocols/-/blob/main/staging/fractional-scale/fractional-scale-v1.xml).

## Configuration

On the patched server, inspect output names and choose a scale:

```sh
xrandr --prop
xrandr --output eDP-1 --set _XLIBRE_OUTPUT_SCALE 150  # 125%
xrandr --output DP-1 --set _XLIBRE_OUTPUT_SCALE 180   # 150%
xrandr --output eDP-1 --set _XLIBRE_OUTPUT_SCALE 120  # 100%
```

The scale numerator is the percentage multiplied by 1.2: 100%, 125%, 150%,
175%, and 200% correspond to 120, 150, 180, 210, and 240. Values from 30 to 960
(25% to 800%) are supported in steps of 1/120. Each newly created output starts
at 120. Desktop display settings should restore the user's preferences when
outputs are created and when a session starts; the server does not persist them.

The reference client is built as `build/test/fractional-scale-demo` when
`cairo-xlib` and `xrandr >= 1.5` development libraries are available. Run it on the
patched display, change the property, and move its window between monitors. It
redraws at the new scale and converts button coordinates to logical units.
It can also be built independently:

```sh
cc -o /tmp/fractional-scale-demo test/fractional-scale-demo.c \
    $(pkg-config --cflags --libs x11 xrandr cairo-xlib)
/tmp/fractional-scale-demo
```

## Wire contract

The property is created on every RandR output, including virtual outputs and
outputs subsequently created by hotplug. No new protocol opcode or driver ABI
is required; clients use RandR 1.2 output property requests.

| Field | Value |
| --- | --- |
| Name | `_XLIBRE_OUTPUT_SCALE` |
| Type / format / item count | `INTEGER` / 32 / 1 |
| Value | Signed positive numerator, denominator 120 |
| Default / valid range | 120 / inclusive 30–960 |
| Pending / range / immutable flags | false / true / false |
| Update mode | `PropModeReplace` only |

A successful change takes effect immediately, without a modeset. Both current
and pending reads return the same value. Normal `RRNotify_OutputProperty`
notifications with `PropertyNewValue` are delivered to clients selecting
`RROutputPropertyNotifyMask`, including when the same value is written again.
Driver property get/set hooks do not intercept this server-owned property.

An incorrect type or format returns `BadMatch`. An out-of-range value, wrong
item count, or append/prepend operation returns `BadValue`. Rejected requests
leave the existing value intact and send no change notification. The value is
mutable, but deleting the property (including a get-with-delete request) or
changing its metadata returns `BadAccess`; configuring the identical metadata
is allowed. This keeps its interpretation stable across clients and drivers.

## Toolkit and window manager integration

1. Select output-property, output, CRTC, screen, and resource change events on
   the root **before** reading the initial configuration. Re-query after events;
   do not rely on the continued existence of a hot-unplugged output ID.
2. Select an active output for each top-level window using its root-relative
   pixel position. A stable anchor, or largest intersection with hysteresis,
   avoids oscillation when resizing across a monitor boundary. The example uses
   the top-left client pixel and RandR 1.5 monitor rectangles, falling back to
   the primary monitor or first active monitor. For mirrored outputs, choose
   one scale consistently (the example chooses the largest). Transient windows
   and popups should inherit their parent's scale.
3. Read the property, checking its type, format, count, and range. Missing or
   malformed properties on other servers mean no preference; retain the
   toolkit's existing scaling policy. The example falls back to 120.
4. Use `s = numerator / 120.0` as the selected rendering scale. For a positive
   logical dimension `L`, allocate `floor(L * numerator / 120 + 0.5)` X pixels,
   using sufficiently wide arithmetic. Rasterize vectors and fonts at that
   scale directly into the resulting window or pixmap. Present and DRI require
   no new buffer handling. Recreate or resize backing buffers when necessary.
5. Convert incoming window-local input from pixels to logical units by dividing
   by `s`. Convert logical child-window bounds, size hints, popup offsets, damage
   rectangles, and regions to pixels when making X requests. Round shared
   rectangle edges consistently to avoid seams. Keep subpixel layout precision;
   round only when crossing into integer X coordinates.
6. On a scale change, preserve the intended logical size when window-manager
   policy permits, request the corresponding pixel size, and redraw. Honor the
   actual pixel size from ConfigureNotify, especially for maximized or tiled
   windows. Window managers need the same convention for decorations and their
   own UI; this server change does not implement a window manager policy.

The property is a rendering preference, not an additional multiplier on an
already DPI-scaled UI. A toolkit should select a single rendering-scale source,
with explicit application/user overrides taking precedence as appropriate.
It should not multiply this preference by Xft.dpi, XSettings scale, or its
existing device-pixel ratio. Physical monitor dimensions are not modified.

## Coexistence with traditional scaling

The limitations below apply to the **property-only** path described above.
For native and traditional windows sharing one transformed output, use the
experimental [XLIBRE-FRACTIONAL-SCALE mixed-scaling transport](mixed-scaling.md).
That path keeps legacy window geometry, attaches separate native buffers, and
lets a capable compositor submit a final physical-resolution output frame which
bypasses the extra output resampling. It requires explicit compositor/client
support and a backend advertising the capability; the property alone does not
activate it.

This feature does not read, reset, or change CRTC transforms, filters, panning,
framebuffer dimensions, DPI, cursor policy, or any global settings. Existing
applications continue to use their existing paths. Keeping the property at 120
lets a desktop continue using its traditional scale-up/scale-down setup.
Different outputs can use different policies.

A non-identity CRTC transform still applies to **all** pixels scanned out on
that CRTC, including those from participating clients. The rendering preference
is in pre-transform X framebuffer pixels per logical unit; any existing output
transform composes with it. Desktop policy must avoid applying the desired
scale twice. This is not a per-window bypass around a CRTC transform. Sharp
native rendering on a given output normally uses its native mode and an identity
transform. Mixed native and legacy clients on that same output do not acquire
separate scanout transforms through this convention.

A window spanning outputs still has a single pixel backing store and one chosen
rendering scale. Different simultaneous rasterizations of that same window on
multiple outputs are outside this contract.
