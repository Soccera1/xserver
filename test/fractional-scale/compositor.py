#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reference XLIBRE-FRACTIONAL-SCALE test compositor, not a desktop.

Uses software readback so tests can assert exact output pixels. Supports opaque,
root-child, borderless TrueColor windows and uniform positive output scaling.
Never replaces a running compositing manager. --offscreen-scale is Xvfb-only.
"""
import argparse
import math
import time
from PIL import Image
from Xlib import X, display, error
from Xlib.protocol import rq, request
from contextlib import contextmanager

OUTPUT, OFFSCREEN, ACTIVE = 1, 2, 4


class FractionalScaleRequest(rq.ReplyRequest):
    _request = rq.Struct(rq.Card8('opcode'), rq.Card8('minor'), rq.RequestLength(),
                         *(rq.Card32(k) for k in 'abcd'))
    _reply = rq.Struct(rq.ReplyCode(), rq.Pad(1), rq.Card16('sequence_number'),
                       rq.ReplyLength(), *(rq.Card32(k) for k in 'abcdef'))


class ReleaseOverlay(rq.Request):
    _request = rq.Struct(rq.Card8('opcode'), rq.Opcode(8), rq.RequestLength(),
                         rq.Window('window'))


def fractional_scale(dpy, op, a=0, b=0, c=0, d=0):
    # python-xlib 0.33's RandR module mistakenly registers its relative error
    # codes over core BadRequest/BadValue with non-protocol Exception classes.
    for code, cls in ((1, error.BadRequest), (2, error.BadValue)):
        existing = dpy.display.error_classes.get(code, cls)
        if not issubclass(existing, error.XError):
            dpy.display.error_classes[code] = cls
    ext = dpy.query_extension('XLIBRE-FRACTIONAL-SCALE')
    if not ext or not ext.present:
        raise RuntimeError('XLIBRE-FRACTIONAL-SCALE is unavailable')
    return FractionalScaleRequest(display=dpy.display, opcode=ext.major_opcode, minor=op,
                         a=a, b=b, c=c, d=d)


@contextmanager
def checked(low):
    """Turn asynchronous errors on requests in this scope into exceptions."""
    catcher = error.CatchError()
    yield catcher
    request.GetInputFocus(display=low)
    if catcher.get_error() is not None:
        raise catcher.get_error()


def pixel_format(low):
    """Validate the fixture's packed depth-24 transport and return PIL layout."""
    formats = [f for f in low.info.pixmap_formats if f.depth == 24]
    if not formats or formats[0].bits_per_pixel != 32 or formats[0].scanline_pad != 32:
        raise RuntimeError('Test compositor requires depth 24 with 32-bit pixels')
    return 'BGRX' if low.info.image_byte_order == X.LSBFirst else 'XRGB'


def check_size(size):
    """Bound software allocations, including transformed offscreen windows."""
    if min(size) <= 0 or max(size) > 32767 or math.prod(size) > 16 * 1024 * 1024:
        raise ValueError('Image exceeds test compositor limits (32767 axis, 16M pixels)')


def image_from_pixmap(pixmap):
    """Read an opaque RGB888 pixmap; callers own and release the resource."""
    geometry = pixmap.get_geometry()
    if geometry.depth != 24:
        raise RuntimeError('Test compositor only supports depth 24')
    size = geometry.width, geometry.height
    check_size(size)
    layout = pixel_format(pixmap.display)
    data = pixmap.get_image(0, 0, *size, X.ZPixmap, 0xffffffff).data
    return Image.frombytes('RGB', size, data, 'raw', layout)


def create_gc(drawable):
    """Create a GC synchronously, returning its XID on server-side failure."""
    low = drawable.display
    xid = low.allocate_resource_id()
    try:
        with checked(low) as catch:
            request.CreateGC(display=low, onerror=catch, cid=xid,
                             drawable=drawable, attrs={})
    except BaseException:
        low.free_resource_id(xid)
        raise
    return low.resource_classes['gc'](low, xid, owner=1)


def upload(root, image):
    """Upload RGB pixels with checked, bounded requests; return an owned pixmap."""
    check_size(image.size)
    if image.mode != 'RGB':
        raise ValueError('Upload requires an RGB image')
    low = root.display
    layout = pixel_format(low)
    xid = low.allocate_resource_id()
    try:
        with checked(low) as catch:
            request.CreatePixmap(display=low, onerror=catch, depth=24,
                                 pid=xid, drawable=root, width=image.width,
                                 height=image.height)
    except BaseException:
        low.free_resource_id(xid)
        raise
    pixmap = low.resource_classes['pixmap'](low, xid, owner=1)
    gc = None
    try:
        gc = create_gc(pixmap)
        # Tile both axes so even a very wide image fits a core request.
        budget = min(60000, low.info.max_request_length * 4 - 24)
        tile_width = min(image.width, budget // 4)
        rows = max(1, budget // (tile_width * 4))
        with checked(low) as catch:
            for x in range(0, image.width, tile_width):
                for y in range(0, image.height, rows):
                    part = image.crop((x, y, min(x + tile_width, image.width),
                                       min(y + rows, image.height)))
                    pixmap.put_image(gc, x, y, *part.size, X.ZPixmap, 24, 0,
                                     part.tobytes('raw', layout), onerror=catch)
        return pixmap
    except BaseException:
        pixmap.free()
        raise
    finally:
        if gc is not None:
            gc.free()


def rounded(value):
    return math.floor(value + 0.5)


class Compositor:
    def __init__(self, dpy, crtc=None, offscreen_scale=None):
        self.dpy = dpy
        self.root = dpy.screen().root
        self.session = None
        self.owner = self.overlay = None
        self.redirected = False
        self.closed = False
        pixel_format(dpy.display)
        screen = dpy.screen()
        visuals = [v for depth in screen.allowed_depths for v in depth.visuals
                   if v.visual_id == screen.root_visual]
        if (screen.root_depth != 24 or not visuals or
                visuals[0].visual_class != X.TrueColor or
                (visuals[0].red_mask, visuals[0].green_mask, visuals[0].blue_mask) !=
                (0xff0000, 0xff00, 0xff)):
            raise RuntimeError('Test compositor requires an RGB888 TrueColor root')
        version = fractional_scale(dpy, 0)
        if (version.a, version.b) != (0, 1):
            raise RuntimeError('Unsupported experimental protocol version')
        self.selection = dpy.intern_atom('_NET_WM_CM_S%d' % dpy.get_default_screen())
        resources = self.root.xrandr_get_screen_resources_current()
        if not resources.crtcs:
            raise RuntimeError('No CRTC is available')
        self.crtc = crtc or resources.crtcs[0]
        info = fractional_scale(dpy, 1, self.crtc)
        self.size = info.c, info.d
        ci = dpy.xrandr_get_crtc_info(self.crtc, resources.config_timestamp)
        self.origin = ci.x, ci.y
        if offscreen_scale is not None:
            if not info.a & OFFSCREEN or info.a & OUTPUT:
                raise RuntimeError('Synthetic transform is allowed only on offscreen targets')
            self.factor = offscreen_scale
            self.filter = Image.Resampling.BILINEAR
        else:
            if not info.a & OUTPUT:
                raise RuntimeError('No physical-output bypass; use Xvfb --offscreen-scale for testing')
            transform = dpy.xrandr_get_crtc_transform(self.crtc)
            matrix = transform.current_transform
            if (matrix.matrix12 or matrix.matrix13 or matrix.matrix21 or matrix.matrix23 or
                    matrix.matrix31 or matrix.matrix32 or matrix.matrix33 != 65536 or
                    matrix.matrix11 != matrix.matrix22 or matrix.matrix11 <= 0):
                raise RuntimeError('Test compositor only implements uniform scaling')
            self.factor = 65536.0 / matrix.matrix11
            name = transform.current_filter_name
            if isinstance(name, bytes):
                name = name.decode('ascii')
            if name not in ('', 'nearest', 'bilinear') or transform.current_filter_params:
                raise RuntimeError('Test compositor cannot preserve this output filter')
            self.filter = (Image.Resampling.BILINEAR if name == 'bilinear'
                           else Image.Resampling.NEAREST)
        if not math.isfinite(self.factor) or self.factor <= 0:
            raise ValueError('Scale must be finite and positive')
        check_size(self.size)
        try:
            # Serialize check-and-claim: never steal an existing manager's selection.
            dpy.grab_server()
            try:
                if dpy.get_selection_owner(self.selection) != X.NONE:
                    raise RuntimeError('A compositor already owns this screen')
                self.owner = self.root.create_window(0, 0, 1, 1, 0, 0, X.InputOnly,
                                                     X.CopyFromParent)
                with checked(dpy.display) as catch:
                    self.owner.set_selection_owner(self.selection, X.CurrentTime,
                                                   onerror=catch)
                if dpy.get_selection_owner(self.selection) != self.owner:
                    raise RuntimeError('Could not acquire compositor selection')
                with checked(dpy.display) as catch:
                    self.root.composite_redirect_subwindows(1, onerror=catch)
                self.redirected = True
            finally:
                dpy.ungrab_server()
                dpy.flush()
            session = dpy.display.allocate_resource_id()
            try:
                self.epoch = fractional_scale(dpy, 2, self.crtc, session, info.b).a
            except BaseException:
                dpy.display.free_resource_id(session)
                raise
            self.session = session
            self.overlay = self.root.composite_get_overlay_window().overlay_window
            from Xlib.ext import shape
            with checked(dpy.display) as catch:
                shape.Rectangles(display=dpy.display, onerror=catch,
                    opcode=dpy.display.get_extension_major('SHAPE'),
                    destination_window=self.overlay, operation=shape.SO.Set,
                    destination_kind=shape.SK.Input, ordering=X.Unsorted,
                    x_offset=0, y_offset=0, rectangles=[])
            self.render()
        except BaseException as failure:
            try:
                self.close()
            except Exception as cleanup:
                failure.add_note('Compositor rollback failed: %s' % cleanup)
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def _require_open(self):
        if self.closed:
            raise RuntimeError('Compositor is closed')

    def name_native(self, window):
        """Return an owned immutable surface reference, or None for fallback."""
        self._require_open()
        xid = self.dpy.display.allocate_resource_id()
        try:
            result = fractional_scale(self.dpy, 6, window.id, xid, self.crtc, self.epoch)
        except BaseException:
            self.dpy.display.free_resource_id(xid)
            raise
        if not result.a:
            self.dpy.display.free_resource_id(xid)
            return None
        return self.dpy.create_resource_object('pixmap', xid)

    def render(self):
        """Capture and submit one coherent scene while producers are paused.

        The server grab deliberately favors deterministic tests over interactive
        latency. Never use this software fixture as a production compositor.
        """
        self._require_open()
        self.dpy.grab_server()
        try:
            return self._render()
        finally:
            self.dpy.ungrab_server()
            self.dpy.flush()

    def _render(self):
        state = fractional_scale(self.dpy, 1, self.crtc)
        if state.b != self.epoch:
            raise RuntimeError('Output changed or compositor ownership was lost; renegotiate')
        frame = Image.new('RGB', self.size, '#18202a')
        root_geometry = self.root.get_geometry()
        root_size = root_geometry.width, root_geometry.height
        check_size(root_size)
        legacy = Image.new('RGB', root_size, '#18202a')
        # XQueryTree returns bottom-to-top order, including legacy/native overlap.
        for window in self.root.query_tree().children:
            if window.id in (self.owner.id, self.overlay.id):
                continue
            attributes = window.get_attributes()
            if attributes.win_class != X.InputOutput or attributes.map_state != X.IsViewable:
                continue
            geometry = window.get_geometry()
            if geometry.border_width:
                raise RuntimeError('Test compositor requires borderless root children')
            if attributes.visual != self.dpy.screen().root_visual:
                raise RuntimeError('Test compositor requires the root visual')
            extents = window.shape_query_extents()
            if extents.bounding_shaped or extents.clip_shaped:
                raise RuntimeError('Test compositor does not support shaped windows')
            opacity = window.get_full_property(
                self.dpy.intern_atom('_NET_WM_WINDOW_OPACITY'), X.AnyPropertyType)
            if opacity is not None and (opacity.format != 32 or
                    list(opacity.value) != [0xffffffff]):
                raise RuntimeError('Test compositor requires opaque windows')
            for child in window.query_tree().children:
                attr = child.get_attributes()
                if attr.win_class == X.InputOutput and attr.map_state == X.IsViewable:
                    raise RuntimeError('Test compositor requires leaf root children')
            ordinary = None
            try:
                with checked(self.dpy.display) as catch:
                    ordinary = window.composite_name_window_pixmap(onerror=catch)
            except BaseException:
                if ordinary is not None:
                    self.dpy.display.free_resource_id(ordinary.id)
                raise
            try:
                fallback = image_from_pixmap(ordinary)
            finally:
                ordinary.free()
            legacy.paste(fallback, (geometry.x, geometry.y))
            left = rounded((geometry.x - self.origin[0]) * self.factor)
            top = rounded((geometry.y - self.origin[1]) * self.factor)
            width = rounded(geometry.width * self.factor)
            height = rounded(geometry.height * self.factor)
            if width == 0 or height == 0:
                continue
            check_size((width, height))
            # Before the first Submit there is no active native session.
            source = self.name_native(window) if state.a & ACTIVE else None
            if source is not None:
                try:
                    pixels = image_from_pixmap(source)
                finally:
                    source.free()
                if pixels.size != (width, height):
                    # A resize/output transition cannot stretch a stale native buffer.
                    pixels = fallback.resize((width, height), self.filter)
            else:
                pixels = fallback.resize((width, height), self.filter)
            frame.paste(pixels, (left, top))
        fallback_pixmap = upload(self.root, legacy)
        gc = None
        try:
            gc = create_gc(self.overlay)
            with checked(self.dpy.display) as catch:
                self.overlay.copy_area(gc, fallback_pixmap, 0, 0, legacy.width,
                                       legacy.height, 0, 0, onerror=catch)
        finally:
            if gc is not None:
                gc.free()
            fallback_pixmap.free()
        pixmap = upload(self.root, frame)
        try:
            fractional_scale(self.dpy, 3, self.session, pixmap.id, self.epoch)
        finally:
            pixmap.free()
        return frame

    def readback(self):
        """Read the server-owned frame through the actual bypass copy path."""
        self._require_open()
        xid = self.dpy.display.allocate_resource_id()
        try:
            fractional_scale(self.dpy, 7, self.session, xid, self.epoch)
        except BaseException:
            self.dpy.display.free_resource_id(xid)
            raise
        pixmap = self.dpy.create_resource_object('pixmap', xid)
        try:
            return image_from_pixmap(pixmap)
        finally:
            pixmap.free()

    def close(self):
        """Release all owned resources once, leaving the borrowed display open."""
        if self.closed:
            return
        self.closed = True
        failures = []

        def attempt(action):
            try:
                action()
            except error.ConnectionClosedError:
                pass  # Disconnect already destroys server resources.
            except Exception as exc:
                failures.append(exc)

        if self.session is not None:
            def release():
                try:
                    fractional_scale(self.dpy, 4, self.session)
                except error.BadValue:
                    pass  # Selection/output invalidation destroys the session.
            attempt(release)
            self.dpy.display.free_resource_id(self.session)
            self.session = None
        if self.overlay is not None:
            def release_overlay():
                with checked(self.dpy.display) as catch:
                    ReleaseOverlay(display=self.dpy.display, onerror=catch,
                        opcode=self.dpy.display.get_extension_major('Composite'),
                        window=self.root)
            attempt(release_overlay)
            self.overlay = None
        if self.redirected:
            def unredirect():
                # python-xlib 0.33's convenience wrapper sends RedirectWindow.
                from Xlib.ext import composite
                with checked(self.dpy.display) as catch:
                    composite.UnredirectSubindows(display=self.dpy.display, onerror=catch,
                        opcode=self.dpy.display.get_extension_major('Composite'),
                        window=self.root, update=1)
            attempt(unredirect)
            self.redirected = False
        if self.owner is not None:
            def destroy_owner():
                with checked(self.dpy.display) as catch:
                    self.owner.destroy(onerror=catch)
            attempt(destroy_owner)
            self.owner = None
        if failures:
            raise RuntimeError('Compositor cleanup failed: %s' % failures) from failures[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--display')
    parser.add_argument('--offscreen-scale', type=float)
    parser.add_argument('--png', help='Write one physical frame and exit')
    args = parser.parse_args()
    dpy = display.Display(args.display)
    comp = None
    try:
        comp = Compositor(dpy, offscreen_scale=args.offscreen_scale)
        if args.png:
            comp.readback().save(args.png)
        else:
            while True:
                comp.render()
                time.sleep(1 / 30)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if comp:
                comp.close()
        finally:
            dpy.close()


if __name__ == '__main__':
    main()
