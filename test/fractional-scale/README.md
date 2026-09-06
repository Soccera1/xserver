# Native scaling reference test compositor

`compositor.py` is maintained test infrastructure for XLIBRE-FRACTIONAL-SCALE 0.1. It
composes legacy and native windows in one output, maintains an ordinary legacy
overlay, and reads submitted physical frames back through the server's bypass
copy path. It is not installed as a desktop component.

## Supported profile

* One CRTC; positive uniform scale; nearest or bilinear filtering without
  parameters. `--offscreen-scale` is restricted to OFFSCREEN targets such as
  Xvfb. Physical use requires the server's OUTPUT capability.
* Opaque, rectangular, borderless, root-child windows using the root's RGB888
  TrueColor visual at depth 24, with 32-bit packed pixels. Both image byte
  orders are supported. Mapped drawing descendants, shaped windows, alpha
  visuals, and opacity properties below full opacity are rejected explicitly.
* Bottom-to-top stacking, output origin, clipped/offscreen windows, and native
  attachments matching the rounded physical window dimensions. A stale or
  incorrectly sized attachment falls back to ordinary window pixels.
* RGB software images limited to 16M pixels and 32767 pixels per axis. An
  output layer rounded to zero pixels is omitted from the physical frame.

The Pillow legacy filter is a deterministic test implementation, not a claim
of bit-identical reconstruction for every GPU or Render filtering convention.
Tests separately require exact, unresampled native pixels. The fixture does
not implement a window manager, frame scheduling, GPU synchronization,
multimonitor policy, or automatic renegotiation after output/ownership changes.

## Ownership and failures

The caller lends a python-xlib display connection and must use it from one
thread. Prefer `with Compositor(display, ...) as comp:`. Startup validates the
output profile before claiming ownership, refuses an existing compositor,
and rolls back partial acquisition on failure. `close()` is idempotent and
keeps that connection open. Cleanup attempts each owned resource even after
an error; unexpected cleanup errors are reported. Output or selection
invalidation stops rendering and requires a fresh instance.

Rendering holds a server grab through capture and submission so application
writes, destruction, geometry, and stacking changes cannot race a test frame.
The grab is released on exceptions. This deliberately pauses other clients
during software readback and is suitable only for isolated tests. Do not run
it as an interactive production compositor.

Pixmap/GC creation, uploads, redirection, overlay input shape, and fallback
copies check asynchronous X errors. Temporary pixmaps and local resource IDs
are released on success and failure. Uploads tile both axes within the core
request limit. The small python-xlib 0.33 compatibility workarounds are kept
beside their affected protocol requests.

## Running and extending tests

Install python-xlib, Pillow, and pytest in the test Python environment. Build
Xvfb with Composite, RandR, Shape, and XLIBRE-FRACTIONAL-SCALE enabled, then run:

```sh
pytest test/pyxtest/test_fractional_scale.py --server-path=build/hw/vfb/Xvfb
# Or, with pytest dependencies available when Meson was configured:
meson test -C build pyxtest-test_fractional_scale.py --print-errorlogs
```

The suite uses isolated Xvfb processes. It covers wire requests in both byte
orders, same-output legacy/native overlap, exact native checkerboard pixels,
restacking, input coordinates, invalidation, access control, disconnection,
startup rollback, redirection conflicts, resource reuse, unsupported scenes,
and upload boundaries. Add observable pixel or lifecycle assertions when
extending the fixture; a successful Submit alone does not prove composition.

For manual inspection of an isolated server:

```sh
python test/fractional-scale/compositor.py --display :99 --offscreen-scale .75 --png frame.png
```

Xvfb tests exercise OFFSCREEN transport and the shared bypass copy routine.
They do not validate physical GPU scanout, hardware cursor behavior, or timing.
