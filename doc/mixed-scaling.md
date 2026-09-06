# Experimental mixed scaling: XLIBRE-FRACTIONAL-SCALE 0.1

This extension separates a window's **legacy X geometry** from its **native
pixel buffer**, and separates the compositor's **physical output frame** from
the **legacy root framebuffer**. Native and traditional clients can occupy and
overlap on the same CRTC. The compositor resolves stacking, clipping, and
occlusion before handing the server one final frame.

This is an experimental server/compositor interface, not a replacement desktop
stack. No existing compositor or toolkit gains support automatically. The
software compositor in `test/fractional-scale/compositor.py` is a maintained protocol and
pixel-test fixture, not an installed desktop component. Its supported scene
profile and lifecycle guarantees are documented in [the fixture README](../test/fractional-scale/README.md).

## The 200% followed by 75% case

Keep the existing root coordinate system and output transform. A logical
100 × 100 widget can have a 200 × 200 X window, just as before.

* A traditional client continues drawing its 200 × 200 buffer. The compositor
  samples it at 75%, yielding 150 × 150 physical pixels.
* A native client draws a separate 150 × 150 pixmap directly, then attaches it
  to its 200 × 200 X window. The compositor uses those pixels 1:1, in the same
  stacking order as the traditional windows. It does not enlarge that pixmap
  to 200 × 200 first.
* The compositor submits a frame matching the physical mode. The server copies
  that frame into the CRTC's final shadow **before and instead of** the ordinary
  root-framebuffer transform/filter operation. The frame is not reduced again.
* Input continues arriving in the 200 × 200 window's coordinate system. The
  native client maps coordinates into its own logical UI/buffer space. No
  event rewriting or pointer warping is introduced.

For physical pixels per logical unit `S` and output reduction factor `T`, use
legacy window scale `S / T` and native buffer scale `S`. For example, `S=1.5`
and `T=0.75` mean legacy geometry at 2.0 and a native buffer at 1.5. RandR's
matrix maps output coordinates to framebuffer coordinates: its diagonal is
`1/T`, not `T`. Include the CRTC origin when mapping positions.

The `_XLIBRE_OUTPUT_SCALE` preference can provide `S` for a client that has
negotiated this path. It is not another multiplier on an existing toolkit DPI
scale. On the ordinary property-only path, its original pre-transform semantics
remain unchanged; merely setting that property does not enable mixed scaling.

## Server support and capability gating

The initial physical backend is Xorg's software-transformed CRTC shadow path
in `xf86Rotate.c`, used by compatible modesetting configurations. It supports
positive uniform scaling with an independent hardware cursor. It declines:

* GPU secondary screens and driver/hardware-performed output transforms;
* identity/no-shadow paths (the ordinary untransformed path needs no bypass);
* rotation, reflection, shear, nonuniform or projective scaling;
* software-cursor-only configurations and additional master pointers.

A backend advertises support dynamically. Losing support cancels the session
when the backend next consumes a frame or when queried. CRTC configuration
changes, ownership loss, and compositor disconnection invalidate it immediately.
The ordinary transform stays configured throughout, so unsupported states use
the legacy fallback. Native clients must re-query after invalidation hints.

Xvfb advertises **OFFSCREEN**, not **OUTPUT**. It exercises frame ownership,
submission, native surfaces, and the same 1:1 copy used by the physical backend,
and exposes the result through ReadFrame. It does not claim to implement a
physical scanout bypass or apply the synthetic transform to X input. The tests
supply a 0.75 reduction explicitly to the reference test compositor. A real client
must require OUTPUT and ACTIVE before treating its pixels as native scanout.

No RandR transform, screen size, monitor DPI, window geometry, or input event is
changed by acquisition/submission. The compositor must continue maintaining its
normal root/overlay composition, and native clients must maintain their normal
window contents, so fallback remains usable. Hardware cursors continue on the
existing cursor path. Root screenshots continue seeing the ordinary composition;
physical-resolution capture needs compositor support or the owner's ReadFrame.

## Wire protocol

The extension name is `XLIBRE-FRACTIONAL-SCALE`. The public wire layouts and constants are
in `include/xlibre-fractional-scaleproto.h`. This is version **0.1** and may evolve before
stabilization; clients must check that version rather than assuming a stable ABI.
All requests are exactly 20 bytes:

```
CARD8 extensionOpcode, CARD8 minorOpcode, CARD16 length (=5)
CARD32 a, b, c, d
```

Every successful request returns a 32-byte reply: the usual 8-byte X reply
header followed by six CARD32 fields `a` through `f`. Unspecified request fields
should be zero. Unspecified reply fields are zero. Normal X byte ordering is
used, including on swapped clients. There are no new error or event numbers.

| Minor | Request fields | Reply fields |
| --- | --- | --- |
| 0 QueryVersion | all zero | a=major (0), b=minor (1) |
| 1 QueryCrtc | a=CRTC | a=flags, b=epoch, c=physical width, d=physical height |
| 2 Acquire | a=CRTC, b=new session XID, c=expected epoch | a=new epoch |
| 3 Submit | a=session, b=source pixmap, c=epoch | all zero |
| 4 Release | a=session | all zero |
| 5 AttachSurface | a=window, b=source pixmap (None detaches), c=CRTC, d=epoch | all zero |
| 6 NameSurface | a=window, b=new pixmap XID, c=CRTC, d=epoch | a=1 if available, b/c=native width/height, d/e=legacy window width/height |
| 7 ReadFrame | a=session, b=new pixmap XID, c=epoch | all zero; creates a snapshot pixmap |

Flags are OUTPUT=1 (physical backend available), OFFSCREEN=2 (test/readback
backend), ACTIVE=4 (a compositor has submitted a frame). No backend capability
means Acquire fails. ACTIVE alone is insufficient to enable physical native
rendering. An epoch belongs to one CRTC and changes on configuration/session
transitions; stale epochs are rejected. Do not reuse it across outputs.

Only the current owner of `_NET_WM_CM_Sn` can acquire that screen's CRTCs.
Acquisition is exclusive and uses a client-owned resource, so disconnecting
releases it. A first Submit activates the path. Submit and ReadFrame require
the acquiring client, current selection ownership, and the matching epoch.

Submit accepts a pixmap on the same screen, at the exact physical mode size
and root depth. The server snapshots it before acknowledging; a producer may
reuse or free the source pixmap after the reply. For core/Render drawing on the
same connection, request ordering provides synchronization. Independently
submitted GPU work must be completed before Submit or AttachSurface; this
prototype has no explicit fence/idle-event protocol. The reply acknowledges the
snapshot, **not** a vblank or page flip. A newer frame replaces the queued frame.

AttachSurface requires the calling client to own the InputOutput window. The
window must be a non-root window on the CRTC's screen. The source must be on the
same screen, either at window depth or depth 32 for premultiplied ARGB. The
server snapshots it, records the window dimensions, target CRTC and current
epoch, and ties its lifetime to the window. Source pixmap destruction or writes
do not change that attachment. None detaches without needing an active session.
Native content is only eligible during the active session it was attached to.

NameSurface is restricted to the acquiring compositor. If no eligible native
surface exists, it returns `a=0` and does not allocate the requested pixmap ID;
the compositor should use CompositeNameWindowPixmap. A resize or a different
CRTC/epoch makes old native content ineligible. If successful, the new pixmap
name holds a reference to that snapshot until the compositor frees it. Treat
it as read-only. A subsequent attachment does not mutate older named snapshots.
Window destruction and client disconnect automatically release attachments.

The compositor must clip native pixels to the window's transformed visible
region and resolve all layers in order, including legacy windows above native
ones. Legacy sampling must preserve the configured RandR transform, filter and
filter parameters; do not silently substitute a different legacy scaling policy.
It must never resize an eligible native image merely to fit a stale
viewport; request a replacement or use the legacy fallback. Round positions and
shared edges consistently. A one-pixel rounding discrepancy can be clipped or
padded without filtering the native buffer. Spanning windows currently have one
CRTC-specific native attachment; other CRTCs use the legacy fallback. A future
version could allow per-CRTC attachments for the same window.

The server changes root property `_XLIBRE_FRACTIONAL_SCALE_STATE` (CARDINAL/32) and sends
normal PropertyNotify as an invalidation hint when sessions or surfaces change.
Subscribe on the root before querying. Its value is not authoritative and is
not an authorization token; re-query the extension. Compositors also need their
usual Damage, window, output, and selection notifications. Re-name native
surfaces on invalidation. This initial transport does full-frame snapshots and
copies; partial damage, explicit fences and zero-copy presentation are future
performance work, not part of the quality/correctness contract.

BadMatch covers unavailable/stale configurations and incompatible pixmaps;
BadAccess covers ownership violations; ordinary BadWindow/BadPixmap/BadValue
resource errors, BadIDChoice, BadLength and BadAlloc apply as appropriate.
Rejected submissions retain the previous frame. A failed surface snapshot leaves
the previous attachment intact. An incompatible new output configuration cancels
the session rather than reinterpreting the old frame at a different scale.

## Disposable compositor and tests

The reference compositor supports borderless, opaque, depth-24, root-child
windows on a little-endian server and a uniform positive scale with nearest or
bilinear filtering (other filters/parameters are refused). It reads pixels
back to software deliberately, to make the composition easy to inspect and
assert. It does not implement a window manager, effects, ARGB blending, arbitrary
window shapes, nested client hierarchies, or production event-driven scheduling.
Those remain compositor responsibilities; the server transport does not flatten
or reorder the supplied scene. It refuses to replace an existing compositor and
exits on an invalidated session rather than attempting desktop policy decisions.

Install pytest, python-xlib and Pillow in a test environment, then run:

```sh
PYTHONDONTWRITEBYTECODE=1 pytest test/pyxtest/test_fractional_scale.py \
    --server-path=build/hw/vfb/Xvfb
```

The tests mix traditional and native windows at a 0.75 reduction on **one**
output, check bit-exact native checkerboard pixels, compare the traditional
region against the expected bilinear reduction, change stacking, and exercise
input, stale geometry, ownership, source-pixmap destruction, selection transfer,
release, reconnection, and swapped-client requests. ReadFrame exercises the same
1:1 copy helper called by the Xorg scanout bypass. This verifies the transport and
reference composition; it is not a physical-GPU scanout or timing test.

For manual experimentation on an otherwise unused Xvfb display:

```sh
python test/fractional-scale/compositor.py --display :99 --offscreen-scale 0.75
```

On a supported transformed Xorg output, omit `--offscreen-scale`; the compositor
reads the actual RandR transform. `--png frame.png` captures one physical output
frame and exits. The offscreen option is rejected on physical-output backends,
so a synthetic test scale cannot accidentally override desktop policy.
