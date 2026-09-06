# SPDX-License-Identifier: MIT
"""Mixed native/legacy output protocol and pixel tests (reference test compositor)."""
import importlib.util
from pathlib import Path
import struct

import pytest
from xclient import X11Reply, X11Error, BadAccess, BadMatch, BadLength, BadRequest


@pytest.fixture(params=['xclient', 'xclient_swapped'])
def wire(request, xserver):
    client = request.getfixturevalue(request.param)
    ext = client.query_extension('XLIBRE-FRACTIONAL-SCALE')
    assert ext
    return client, ext.opcode


def raw(ctx, op, a=0, b=0, c=0, d=0, length=5):
    client, opcode = ctx
    bo = '>' if client.swapped else '<'
    client.send_request(struct.pack(f'{bo}BBH4I', opcode, op, length, a, b, c, d))
    return client.recv_response()


def test_version_and_invalid_opcode(wire):
    client, _ = wire
    bo = '>' if client.swapped else '<'
    reply = raw(wire, 0)
    assert isinstance(reply, X11Reply)
    assert struct.unpack_from(f'{bo}6I', reply.data, 8) == (0, 1, 0, 0, 0, 0)
    reply = raw(wire, 99)
    assert isinstance(reply, X11Error) and reply.error_code == BadRequest


def test_request_length(wire):
    client, opcode = wire
    bo = '>' if client.swapped else '<'
    client.send_request(struct.pack(f'{bo}BBH3I', opcode, 0, 4, 0, 0, 0))
    reply = client.recv_response()
    assert isinstance(reply, X11Error) and reply.error_code == BadLength


@pytest.fixture
def compositor_module():
    pytest.importorskip('Xlib')
    pytest.importorskip('PIL')
    path = Path(__file__).parents[1] / 'fractional-scale' / 'compositor.py'
    spec = importlib.util.spec_from_file_location('native_compositor', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def scene(xserver, compositor_module):
    from Xlib import display
    module = compositor_module
    owner = display.Display(xserver.display)
    app = display.Display(xserver.display)
    try:
        with module.Compositor(owner, offscreen_scale=0.75) as comp:
            yield module, comp, app
    finally:
        try:
            app.close()
        finally:
            owner.close()


def draw_window(module, app, image, x, y):
    from Xlib import X
    root = app.screen().root
    window = root.create_window(x, y, *image.size, 0, 24, X.InputOutput,
                                X.CopyFromParent, background_pixel=0,
                                event_mask=X.ButtonPressMask)
    window.map()
    app.sync()
    pixmap = module.upload(root, image)
    gc = window.create_gc()
    window.copy_area(gc, pixmap, 0, 0, *image.size, 0, 0)
    gc.free()
    pixmap.free()
    app.sync()
    return window


def attach(module, comp, app, window, image):
    pixmap = module.upload(app.screen().root, image)
    try:
        module.fractional_scale(app, 5, window.id, pixmap.id, comp.crtc, comp.epoch)
    finally:
        pixmap.free()  # Server must retain an independent snapshot.
    app.sync()


def test_same_output_overlap_and_exact_native_pixels(scene, tmp_path):
    from PIL import Image
    from Xlib import X
    module, comp, app = scene
    # A high-resolution legacy UI goes through the traditional 75% reduction.
    legacy = Image.new('RGB', (400, 240))
    legacy.putdata([(255, 20, 20) if (x // 5) % 2 else (20, 20, 255)
                    for y in range(240) for x in range(400)])
    legacy_window = draw_window(module, app, legacy, 0, 0)
    fallback = Image.new('RGB', (160, 120), '#00aa00')
    native_window = draw_window(module, app, fallback, 80, 40)
    # 160x120 legacy geometry occupies 120x90 physical pixels. A one-pixel
    # checkerboard must remain bit-exact; even one extra resample blurs it.
    native_image = Image.new('RGB', (120, 90))
    native_image.putdata([(255, 255, 255) if (x + y) % 2 else (0, 0, 0)
                          for y in range(90) for x in range(120)])
    attach(module, comp, app, native_window, native_image)
    comp.render()
    actual = comp.readback()
    expected = legacy.resize((300, 180), Image.Resampling.BILINEAR)
    assert actual.crop((0, 0, 60, 180)).tobytes() == expected.crop((0, 0, 60, 180)).tobytes()
    assert actual.crop((60, 30, 180, 120)).tobytes() == native_image.tobytes()

    # A legacy window above the native window occludes it in the same scene.
    foreground = draw_window(module, app, Image.new('RGB', (40, 40), '#ff00ff'), 120, 80)
    comp.render()
    actual = comp.readback()
    assert actual.getpixel((100, 70)) == (255, 0, 255)
    assert actual.getpixel((61, 30)) == native_image.getpixel((1, 0))
    foreground.configure(stack_mode=X.Below)
    app.sync()
    comp.render()
    assert comp.readback().crop((60, 30, 180, 120)).tobytes() == native_image.tobytes()

    # Snapshot after destroying the producer's pixmap is still valid. Geometry
    # remains legacy-sized: no resize/input rewrite occurred in the server.
    geometry = native_window.get_geometry()
    assert (geometry.width, geometry.height) == (160, 120)
    actual.save(tmp_path / 'mixed-output.png')

    # A geometry change invalidates the native buffer instead of stretching it.
    native_window.configure(width=164)
    app.sync()
    assert comp.name_native(native_window) is None


def test_access_control_epochs_and_invalid_frame(scene):
    from PIL import Image
    from Xlib import error
    module, comp, app = scene
    info = module.fractional_scale(app, 1, comp.crtc)
    assert info.a == module.OFFSCREEN | module.ACTIVE
    with pytest.raises(error.BadAccess):
        module.fractional_scale(app, 2, comp.crtc, app.display.allocate_resource_id(), info.b)
    with pytest.raises(error.BadAccess):
        module.fractional_scale(app, 4, comp.session)
    pixmap = module.upload(app.screen().root, Image.new('RGB', (12, 12)))
    app.sync()
    with pytest.raises(error.BadMatch):
        module.fractional_scale(comp.dpy, 3, comp.session, pixmap.id, comp.epoch)
    with pytest.raises(error.BadMatch):
        module.fractional_scale(comp.dpy, 3, comp.session, pixmap.id, comp.epoch + 1)
    pixmap.free()
    assert module.fractional_scale(app, 1, comp.crtc).a & module.ACTIVE
    assert comp.readback().size == comp.size


def test_surface_ownership_detach_and_selection_loss(scene):
    from PIL import Image
    from Xlib import X, error
    module, comp, app = scene
    win = draw_window(module, app, Image.new('RGB', (80, 80), '#123456'), 0, 0)
    pixmap = module.upload(app.screen().root, Image.new('RGB', (60, 60), '#abcdef'))
    with pytest.raises(error.BadAccess):
        module.fractional_scale(comp.dpy, 5, win.id, pixmap.id, comp.crtc, comp.epoch)
    module.fractional_scale(app, 5, win.id, pixmap.id, comp.crtc, comp.epoch)
    named = comp.name_native(win)
    assert named is not None
    named.free()
    module.fractional_scale(app, 5, win.id)  # Explicit detach.
    assert comp.name_native(win) is None
    module.fractional_scale(app, 5, win.id, pixmap.id, comp.crtc, comp.epoch)
    # Selection transfer invalidates output and surfaces even while the old
    # compositor remains connected. No stale frame can be submitted afterward.
    win.set_selection_owner(comp.selection, X.CurrentTime)
    app.sync()
    state = module.fractional_scale(app, 1, comp.crtc)
    assert not state.a & module.ACTIVE
    assert state.b != comp.epoch
    with pytest.raises(error.XError):
        module.fractional_scale(comp.dpy, 3, comp.session, pixmap.id, comp.epoch)
    pixmap.free()


def test_compositor_disconnect_restores_fallback(xserver, compositor_module):
    from Xlib import display
    module = compositor_module
    dpy = display.Display(xserver.display)
    reader = display.Display(xserver.display)
    comp = module.Compositor(dpy, offscreen_scale=0.75)
    crtc, epoch = comp.crtc, comp.epoch
    assert module.fractional_scale(reader, 1, crtc).a & module.ACTIVE
    dpy.close()  # No Release request: exercise resource teardown.
    comp.close()  # Safe even when the borrowed connection has already closed.
    state = module.fractional_scale(reader, 1, crtc)
    assert not state.a & module.ACTIVE
    assert state.b != epoch
    reader.close()


def test_full_wire_lifecycle_in_both_byte_orders(wire):
    from proto import randr
    client, _ = wire
    bo = '>' if client.swapped else '<'
    rr = client.query_extension('RANDR')
    client.send_request(randr.QueryVersionRequest(opcode=rr.opcode))
    assert isinstance(client.recv_response(), X11Reply)
    client.send_request(randr.GetScreenResourcesCurrentRequest(opcode=rr.opcode,
                                                              window=client.root_window))
    resources = client.recv_response()
    assert isinstance(resources, X11Reply)
    crtc = struct.unpack_from(f'{bo}I', resources.data, 32)[0]

    def fields(response):
        assert isinstance(response, X11Reply)
        return struct.unpack_from(f'{bo}6I', response.data, 8)

    cap, epoch, width, height, _, _ = fields(raw(wire, 1, crtc))
    assert cap == 2  # Offscreen test target, never a physical scanout claim.
    owner = client.create_window(width=40, height=40)
    selection = client.intern_atom('_NET_WM_CM_S0')
    client.send_request(struct.pack(f'{bo}BBHIII', 22, 0, 4, owner, selection, 0))
    session = client.alloc_id()
    epoch = fields(raw(wire, 2, crtc, session, epoch))[0]
    frame = client.create_pixmap(width=width, height=height)
    fields(raw(wire, 3, session, frame, epoch))
    assert fields(raw(wire, 1, crtc))[0] == 6
    native_pixmap = client.create_pixmap(width=30, height=30)
    fields(raw(wire, 5, owner, native_pixmap, crtc, epoch))
    # Producer mutation/lifetime is independent from the retained surface.
    client.send_request(struct.pack(f'{bo}BBHI', 54, 0, 2, native_pixmap))
    named = client.alloc_id()
    assert fields(raw(wire, 6, owner, named, crtc, epoch)) == (1, 30, 30, 40, 40, 0)
    readback = client.alloc_id()
    fields(raw(wire, 7, session, readback, epoch))
    fields(raw(wire, 4, session))
    cap, next_epoch, *_ = fields(raw(wire, 1, crtc))
    assert cap == 2 and next_epoch != epoch
    # Reacquiring must not resurrect old buffers from the previous compositor.
    session = client.alloc_id()
    epoch = fields(raw(wire, 2, crtc, session, next_epoch))[0]
    fields(raw(wire, 3, session, frame, epoch))
    assert fields(raw(wire, 6, owner, client.alloc_id(), crtc, epoch))[0] == 0
    fields(raw(wire, 4, session))


def test_native_input_uses_unchanged_legacy_window_coordinates(scene):
    from PIL import Image
    from Xlib import X
    module, comp, app = scene
    window = draw_window(module, app, Image.new('RGB', (160, 120)), 80, 40)
    attach(module, comp, app, window, Image.new('RGB', (120, 90)))
    comp.render()
    # A physical output point (90, 60) maps through the existing 0.75 output
    # scale to root (120, 80). Xvfb is offscreen, so inject that root point.
    app.xtest_fake_input(X.MotionNotify, x=120, y=80)
    app.xtest_fake_input(X.ButtonPress, 1)
    app.xtest_fake_input(X.ButtonRelease, 1)
    app.sync()
    events = []
    while app.pending_events():
        events.append(app.next_event())
    press = next(event for event in events if event.type == X.ButtonPress)
    assert press.window.id == window.id
    assert (press.event_x, press.event_y) == (40, 40)
    # The native toolkit maps to buffer coordinates exactly once.
    assert (press.event_x * 0.75, press.event_y * 0.75) == (30, 30)


@pytest.mark.parametrize('scale', [0, -1, float('nan'), float('inf')])
def test_invalid_scale_leaves_display_usable(xserver, compositor_module, scale):
    from Xlib import display, X
    module = compositor_module
    dpy = display.Display(xserver.display)
    try:
        selection = dpy.intern_atom('_NET_WM_CM_S0')
        with pytest.raises(ValueError, match='finite and positive'):
            module.Compositor(dpy, offscreen_scale=scale)
        assert dpy.get_selection_owner(selection) == X.NONE
        with module.Compositor(dpy, offscreen_scale=0.75) as comp:
            assert comp.readback().size == comp.size
    finally:
        dpy.close()


@pytest.mark.parametrize('stage', ['acquire', 'first_frame'])
def test_failed_startup_rolls_back(xserver, compositor_module, monkeypatch, stage):
    from Xlib import display, X
    module = compositor_module
    dpy = display.Display(xserver.display)
    try:
        before = set(dpy.display.resource_ids)
        with monkeypatch.context() as patch:
            if stage == 'acquire':
                original = module.fractional_scale
                def fail_acquire(dpy, op, *args, **kwargs):
                    if op == 2:
                        raise RuntimeError('injected failure')
                    return original(dpy, op, *args, **kwargs)
                patch.setattr(module, 'fractional_scale', fail_acquire)
            else:
                def fail_render(self):
                    raise RuntimeError('injected failure')
                patch.setattr(module.Compositor, 'render', fail_render)
            with pytest.raises(RuntimeError, match='injected failure'):
                module.Compositor(dpy, offscreen_scale=0.75)
        assert set(dpy.display.resource_ids) == before
        assert dpy.get_selection_owner(dpy.intern_atom('_NET_WM_CM_S0')) == X.NONE
        # Reuse the same connection: disconnect must not hide leaked ownership.
        with module.Compositor(dpy, offscreen_scale=0.75) as comp:
            assert module.fractional_scale(dpy, 1, comp.crtc).a & module.ACTIVE
        assert set(dpy.display.resource_ids) == before
    finally:
        dpy.close()


def test_existing_manager_is_never_replaced(scene):
    import pytest
    module, comp, app = scene
    owner = app.get_selection_owner(comp.selection)
    with pytest.raises(RuntimeError, match='already owns'):
        module.Compositor(app, offscreen_scale=0.75)
    assert app.get_selection_owner(comp.selection) == owner
    comp.render()
    assert module.fractional_scale(app, 1, comp.crtc).a & module.ACTIVE


def test_redirect_conflict_is_reported_and_rolled_back(xserver, compositor_module):
    from Xlib import display, X, error
    from Xlib.ext import composite
    module = compositor_module
    blocker = display.Display(xserver.display)
    dpy = display.Display(xserver.display)
    try:
        blocker.screen().root.composite_redirect_subwindows(1)
        blocker.sync()
        with pytest.raises(error.BadAccess):
            module.Compositor(dpy, offscreen_scale=0.75)
        assert dpy.get_selection_owner(dpy.intern_atom('_NET_WM_CM_S0')) == X.NONE
        composite.UnredirectSubindows(display=blocker.display,
            opcode=blocker.display.get_extension_major('Composite'),
            window=blocker.screen().root, update=1)
        blocker.sync()
        with module.Compositor(dpy, offscreen_scale=0.75):
            pass
    finally:
        dpy.close()
        blocker.close()


def test_close_is_idempotent_and_does_not_close_display(scene):
    module, comp, app = scene
    crtc = comp.crtc
    comp.close()
    comp.close()
    assert not module.fractional_scale(app, 1, crtc).a & module.ACTIVE
    with pytest.raises(RuntimeError, match='closed'):
        comp.render()
    with pytest.raises(RuntimeError, match='closed'):
        comp.readback()
    with module.Compositor(comp.dpy, offscreen_scale=0.75):
        pass


@pytest.mark.parametrize('kind', ['shape', 'opacity', 'child', 'border'])
def test_unsupported_scenes_fail_explicitly_and_release_grab(scene, kind):
    from PIL import Image
    from Xlib import X, Xatom
    from Xlib.ext import shape
    module, comp, app = scene
    win = draw_window(module, app, Image.new('RGB', (20, 20)), 0, 0)
    if kind == 'shape':
        win.shape_rectangles(shape.SO.Set, shape.SK.Bounding, X.Unsorted,
                             0, 0, [(0, 0, 10, 10)])
    elif kind == 'opacity':
        win.change_property(app.intern_atom('_NET_WM_WINDOW_OPACITY'),
                            Xatom.CARDINAL, 32, [0x80000000])
    elif kind == 'child':
        child = win.create_window(0, 0, 10, 10, 0, 24, X.InputOutput, X.CopyFromParent)
        child.map()
    else:
        win.configure(border_width=1)
    app.sync()
    with pytest.raises(RuntimeError, match='Test compositor'):
        comp.render()
    # A second connection must continue processing after the failed frame.
    win.destroy()
    app.sync()
    comp.render()


def test_render_and_failed_names_do_not_leak_resource_ids(scene):
    from PIL import Image
    from Xlib import error
    module, comp, app = scene
    win = draw_window(module, app, Image.new('RGB', (20, 20)), 0, 0)
    attach(module, comp, app, win, Image.new('RGB', (15, 15)))
    before = set(comp.dpy.display.resource_ids)
    for _ in range(8):
        comp.render()
        comp.readback()
    assert set(comp.dpy.display.resource_ids) == before
    win.destroy()
    app.sync()
    with pytest.raises(error.BadWindow):
        comp.name_native(win)
    assert set(comp.dpy.display.resource_ids) == before
    # A stale session also must not leak the readback destination XID.
    comp.epoch += 1
    with pytest.raises(error.BadMatch):
        comp.readback()
    assert set(comp.dpy.display.resource_ids) == before


def test_wide_upload_and_zero_pixel_layer(xserver, compositor_module):
    from PIL import Image
    from Xlib import display
    module = compositor_module
    dpy = display.Display(xserver.display)
    app = display.Display(xserver.display)
    try:
        image = Image.new('RGB', (20000, 2), '#abcdef')
        pixmap = module.upload(app.screen().root, image)
        try:
            assert module.image_from_pixmap(pixmap).tobytes() == image.tobytes()
        finally:
            pixmap.free()
        with module.Compositor(dpy, offscreen_scale=0.25) as comp:
            draw_window(module, app, Image.new('RGB', (1, 1), 'red'), 0, 0)
            comp.render()
            assert comp.readback().getpixel((0, 0)) == (24, 32, 42)
    finally:
        app.close()
        dpy.close()


def test_cleanup_continues_after_unexpected_release_error(scene, monkeypatch):
    from Xlib import X
    module, comp, app = scene
    original = module.fractional_scale
    def fail_release(dpy, op, *args, **kwargs):
        if op == 4:
            raise RuntimeError('injected release failure')
        return original(dpy, op, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(module, 'fractional_scale', fail_release)
        with pytest.raises(RuntimeError, match='injected release failure'):
            comp.close()
    assert app.get_selection_owner(comp.selection) == X.NONE
    assert not module.fractional_scale(app, 1, comp.crtc).a & module.ACTIVE
    with module.Compositor(comp.dpy, offscreen_scale=0.75):
        pass


def test_failed_pixmap_creation_returns_local_id(scene):
    from PIL import Image
    from Xlib import error
    module, comp, app = scene
    root = app.screen().root
    dead = root.create_pixmap(1, 1, 24)
    dead.free()
    app.sync()
    before = set(app.display.resource_ids)
    with pytest.raises(error.BadDrawable):
        module.upload(dead, Image.new('RGB', (4, 4)))
    assert set(app.display.resource_ids) == before
