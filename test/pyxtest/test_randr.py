# SPDX-License-Identifier: MIT
#
# Security tests for RandR extension vulnerabilities.

import os
import struct
import subprocess
import time

import pytest
from proto import randr
from xclient import (
    BadAccess, BadIDChoice, BadLength, BadMatch, BadValue,
    Extension, X11Error, X11Reply,
)


def _get_first_output(xclient, opcode):
    """Return the first RandR output ID, or skip if none available."""
    req = randr.GetScreenResourcesCurrentRequest(
        opcode=opcode,
        window=xclient.root_window,
    )
    xclient.send_request(req)
    resp = xclient.recv_response(timeout=5.0)
    if not isinstance(resp, X11Reply) or len(resp.data) < 32:
        pytest.skip("Failed to get RandR screen resources")

    bo = ">" if xclient.swapped else "<"
    n_crtcs = struct.unpack_from(f"{bo}H", resp.data, 16)[0]
    n_outputs = struct.unpack_from(f"{bo}H", resp.data, 18)[0]
    if n_outputs == 0:
        pytest.skip("No RandR outputs available")

    offset = 32 + n_crtcs * 4
    return struct.unpack_from(f"{bo}I", resp.data, offset)[0]


@pytest.fixture
def randr_xclient(xclient):
    """Provide an xclient with RandR initialized, returning (xclient, opcode, output_id)."""
    ext = xclient.query_extension(Extension.RANDR)
    if not ext:
        pytest.skip("RANDR extension not available")

    req = randr.QueryVersionRequest(opcode=ext.opcode)
    xclient.send_request(req)
    xclient.recv_response(timeout=5.0)

    output_id = _get_first_output(xclient, ext.opcode)
    return xclient, ext.opcode, output_id


@pytest.fixture
def randr_xclient_swapped(xclient_swapped):
    """Provide a byte-swapped xclient with RandR initialized."""
    ext = xclient_swapped.query_extension(Extension.RANDR)
    if not ext:
        pytest.skip("RANDR extension not available")

    req = randr.QueryVersionRequest(opcode=ext.opcode)
    xclient_swapped.send_request(req)
    xclient_swapped.recv_response(timeout=5.0)

    return xclient_swapped, ext.opcode


class TestRandROutputProperty:
    """Tests for RRChangeOutputProperty vulnerabilities."""

    def test_prepend_property_size_and_offset(self, xserver, randr_xclient):
        """
        CVE-2023-5367 / ZDI-CAN-22153: Incorrect size and offset
        calculation when prepending to RandR output properties.

        Two bugs in RRChangeOutputProperty (copy-pasted from the XI code):
        1. new_value.size was set to ``len`` instead of ``total_len``
           (new + existing), so the property lost the old data's size.
        2. The old_data offset for PropModePrepend used
           ``prop_value->size`` instead of ``len``, placing old data at
           the wrong position and writing out of bounds.

        This test sets a property, prepends to it, and reads back the
        result.  On a fixed server the property contains all values in
        the correct order.

        Fixed in commit 541ab2ecd41d ("Xi/randr: fix handling of
        PropModeAppend/Prepend").
        """
        xclient, opcode, output_id = randr_xclient

        prop_atom = xclient.intern_atom("_TEST_RR_PREPEND")
        type_atom = xclient.intern_atom("INTEGER")

        # Step 1: Set initial property with values [10, 20, 30]
        initial_data = struct.pack("<III", 10, 20, 30)
        req = randr.ChangeOutputPropertyRequest(
            opcode=opcode,
            output=output_id,
            property_atom=prop_atom,
            type_atom=type_atom,
            format=32,
            mode=randr.PropModeReplace,
            data=initial_data,
        )
        xclient.send_request(req)
        xclient.flush_responses(timeout=0.5)

        # Step 2: Prepend values [1, 2]
        prepend_data = struct.pack("<II", 1, 2)
        req = randr.ChangeOutputPropertyRequest(
            opcode=opcode,
            output=output_id,
            property_atom=prop_atom,
            type_atom=type_atom,
            format=32,
            mode=randr.PropModePrepend,
            data=prepend_data,
        )
        xclient.send_request(req)
        xclient.flush_responses(timeout=0.5)

        assert xserver.is_alive, (
            "Server crashed - OOB write in RRChangeOutputProperty prepend (CVE-2023-5367)"
        )

        # Step 3: Read back and verify
        req = randr.GetOutputPropertyRequest(
            opcode=opcode,
            output=output_id,
            property_atom=prop_atom,
            type_atom=type_atom,
        )
        xclient.send_request(req)
        resp = xclient.recv_response(timeout=2.0)

        assert isinstance(resp, X11Reply), f"Expected a reply, got {resp}"
        num_items = struct.unpack_from("<I", resp.data, 16)[0]
        assert num_items == 5, (
            f"Expected 5 items (2 prepended + 3 original), got {num_items}"
        )

        values = struct.unpack_from(f"<{num_items}I", resp.data, 32)
        assert values == (1, 2, 10, 20, 30), (
            f"Expected (1, 2, 10, 20, 30), got {values}"
        )

    def test_change_output_property_num_items_overflow(self, xserver, randr_xclient):
        """
        CVE-2023-6478 / ZDI-CAN-22561: Integer truncation in
        ProcRRChangeOutputProperty length check.

        ``totalSize = nUnits * sizeInBytes`` was computed as a 32-bit int.
        With format=32 and nUnits=0x40000000, the multiplication overflows
        to 0, passing the REQUEST_FIXED_SIZE check.

        The fix changed totalSize from ``int`` to ``uint64_t``.

        Fixed in commit 14f480010a93 ("randr: avoid integer truncation in
        length check of ProcRRChange*Property").
        """
        xclient, opcode, output_id = randr_xclient

        prop_atom = xclient.intern_atom("_TEST_RR_OVERFLOW")
        type_atom = xclient.intern_atom("INTEGER")

        req = randr.ChangeOutputPropertyRequest(
            opcode=opcode,
            output=output_id,
            property_atom=prop_atom,
            type_atom=type_atom,
            format=32,
            mode=randr.PropModeReplace,
            num_items=0x40000000,
            data=b"",
        )
        xclient.send_request(req)
        resp = xclient.recv_response(timeout=2.0)

        assert xserver.is_alive, (
            "Server crashed - integer truncation in RRChangeOutputProperty (CVE-2023-6478)"
        )
        # The server should reject with BadLength (16).  Without the fix
        # the truncated totalSize (0) passes REQUEST_FIXED_SIZE and the
        # server tries to allocate 4 GB, failing with BadAlloc (11)
        # instead.
        assert isinstance(resp, X11Error), f"Expected an error, got {resp}"
        assert resp.error_code == BadLength, (
            f"Expected BadLength ({BadLength}), got error code {resp.error_code} - "
            f"integer truncation not caught by length check"
        )


class TestRandRSetScreenConfig:
    @pytest.mark.swapped_client
    def test_set_screen_config_config_timestamp_swapped(
        self, xserver, randr_xclient_swapped
    ):
        """
        SProcRRSetScreenConfig was missing swapl(&stuff->configTimestamp).

        First query the server's configTimestamp via GetScreenResources,
        then send it back in SetScreenConfig.  Without the fix, the
        unswapped configTimestamp won't match → the reply has
        status=RRSetConfigInvalidConfigTime (1) instead of
        RRSetConfigSuccess (0).

        Fixed in commit ac45f9b29e3a ("randr: add missing byte swapping
        for various fields").
        """
        conn, opcode = randr_xclient_swapped

        # Get screen resources to obtain the configTimestamp
        req = randr.GetScreenResourcesCurrentRequest(
            opcode=opcode,
            window=conn.root_window,
        )
        conn.send_request(req)
        resp = conn.recv_response(timeout=5.0)

        assert isinstance(resp, X11Reply), f"Expected reply, got {resp}"
        assert len(resp.data) >= 32, "Reply too short"

        # xRRGetScreenResourcesReply:
        #   [8]  timestamp(4)
        #   [12] configTimestamp(4)
        config_ts = struct.unpack_from(">I", resp.data, 12)[0]

        req = randr.SetScreenConfigRequest(
            opcode=opcode,
            drawable=conn.root_window,
            timestamp=0,  # CurrentTime
            config_timestamp=config_ts,
            size_id=0,
            rotation=1,
        )
        conn.send_request(req)
        resp = conn.recv_response(timeout=5.0)

        assert xserver.is_alive, "Server crashed"
        assert isinstance(resp, X11Reply), f"Expected reply, got {resp}"

        # xRRSetScreenConfigReply:
        #   [1] status
        # RRSetConfigSuccess = 0
        # RRSetConfigInvalidConfigTime = 1
        # RRSetConfigInvalidTime = 2
        # RRSetConfigFailed = 3
        #
        # Without the fix, the unswapped configTimestamp fails
        # the equality check → status 1 (RRSetConfigInvalidConfigTime).
        status = resp.data[1]
        assert status != 1, (
            "SetScreenConfig status = 1 "
            "(RRSetConfigInvalidConfigTime) - configTimestamp "
            "was not byte-swapped correctly."
        )


class TestRandRCreateLease:
    @pytest.mark.swapped_client
    def test_create_lease_lid_swapped(self, xserver, randr_xclient_swapped):
        """
        SProcRRCreateLease was missing swapl(&stuff->lid).
        Without the swap, the garbled lid fails LEGAL_NEW_RESOURCE
        → BadIDChoice error (error code 14).

        With the fix, the request should succeed far enough to reach
        the crtc/output validation (possibly returning BadValue for
        the empty lists, but NOT BadIDChoice).

        Fixed in commit ac45f9b29e3a ("randr: add missing byte swapping
        for various fields").
        """
        conn, opcode = randr_xclient_swapped

        lid = conn.alloc_id()

        # Get screen resources to find a crtc and output
        req = randr.GetScreenResourcesCurrentRequest(
            opcode=opcode,
            window=conn.root_window,
        )
        conn.send_request(req)
        resp = conn.recv_response(timeout=5.0)
        assert isinstance(resp, X11Reply), f"Expected reply, got {resp}"

        n_crtcs = struct.unpack_from(">H", resp.data, 16)[0]
        n_outputs = struct.unpack_from(">H", resp.data, 18)[0]

        crtcs = []
        outputs = []
        if n_crtcs > 0:
            crtcs = [struct.unpack_from(">I", resp.data, 32)[0]]
        if n_outputs > 0:
            offset = 32 + n_crtcs * 4
            outputs = [struct.unpack_from(">I", resp.data, offset)[0]]

        req = randr.CreateLeaseRequest(
            opcode=opcode,
            window=conn.root_window,
            lid=lid,
            crtcs=crtcs,
            outputs=outputs,
        )
        conn.send_request(req)
        resp = conn.recv_response(timeout=5.0)

        assert xserver.is_alive, "Server crashed"

        # Without the fix: BadIDChoice (error code 14).
        # With the fix: either success or some other error.
        if isinstance(resp, X11Error):
            assert resp.error_code != BadIDChoice, (
                "CreateLease returned BadIDChoice - lid not byte-swapped"
            )


@pytest.fixture(params=["xclient", "xclient_swapped"])
def scale_client(request, xserver):
    """Exercise the scale contract in both wire byte orders."""
    client = request.getfixturevalue(request.param)
    ext = client.query_extension(Extension.RANDR)
    assert ext
    client.send_request(randr.QueryVersionRequest(opcode=ext.opcode))
    assert isinstance(client.recv_response(), X11Reply)
    output = _get_first_output(client, ext.opcode)
    atom = client.intern_atom("_XLIBRE_OUTPUT_SCALE")
    return client, ext, output, atom


class TestFractionalScale:
    def read_scale(self, ctx, pending=False):
        client, ext, output, atom = ctx
        client.send_request(randr.GetOutputPropertyRequest(
            opcode=ext.opcode, output=output, property_atom=atom,
            pending=pending,
        ))
        reply = client.recv_response()
        assert isinstance(reply, X11Reply)
        bo = ">" if client.swapped else "<"
        assert reply.data[1] == 32
        assert struct.unpack_from(f"{bo}III", reply.data, 8) == (19, 0, 1)
        return struct.unpack_from(f"{bo}i", reply.data, 32)[0]

    def change_scale(self, ctx, values, fmt=32, mode=0, type_atom=19):
        client, ext, output, atom = ctx
        bo = ">" if client.swapped else "<"
        code = {8: "B", 16: "H", 32: "i"}[fmt]
        client.send_request(randr.ChangeOutputPropertyRequest(
            opcode=ext.opcode, output=output, property_atom=atom,
            type_atom=type_atom, format=fmt, mode=mode,
            data=struct.pack(f"{bo}{len(values)}{code}", *values),
        ))

    def test_default_and_range(self, scale_client):
        assert self.read_scale(scale_client) == 120
        client, ext, output, atom = scale_client
        bo = ">" if client.swapped else "<"
        # RRQueryOutputProperty
        client.send_request(struct.pack(f"{bo}BBHII", ext.opcode, 11, 3,
                                        output, atom))
        reply = client.recv_response()
        assert isinstance(reply, X11Reply)
        assert reply.data[8:11] == bytes([0, 1, 0])
        assert struct.unpack_from(f"{bo}ii", reply.data, 32) == (30, 960)

    @pytest.mark.parametrize("scale", [30, 120, 150, 160, 180, 210, 960])
    def test_immediate_value_and_notification(self, scale_client, scale):
        client, ext, output, atom = scale_client
        bo = ">" if client.swapped else "<"
        # RROutputPropertyNotifyMask
        client.send_request(randr.SelectInputRequest(
            opcode=ext.opcode, window=client.root_window, enable=8,
        ))
        self.change_scale(scale_client, [scale])
        event = client.recv_response()
        assert isinstance(event, X11Reply)
        assert event.data[0:2] == bytes([ext.first_event + 1, 2])
        assert struct.unpack_from(f"{bo}III", event.data, 4) == (
            client.root_window, output, atom,
        )
        assert event.data[20] == 0  # PropertyNewValue
        assert self.read_scale(scale_client) == scale
        assert self.read_scale(scale_client, pending=True) == scale

    @pytest.mark.parametrize("values,fmt,mode,type_atom,error", [
        ([0], 32, 0, 19, BadValue),
        ([-1], 32, 0, 19, BadValue),
        ([29], 32, 0, 19, BadValue),
        ([961], 32, 0, 19, BadValue),
        ([2147483647], 32, 0, 19, BadValue),
        ([], 32, 0, 19, BadValue),
        ([150, 180], 32, 0, 19, BadValue),
        ([150], 32, 1, 19, BadValue),
        ([], 32, 2, 19, BadValue),
        ([150], 8, 0, 19, BadMatch),
        ([150], 16, 0, 19, BadMatch),
        ([150], 32, 0, 6, BadMatch),  # CARDINAL, not INTEGER
    ])
    def test_invalid_write_is_atomic(self, scale_client, values, fmt, mode,
                                     type_atom, error):
        self.change_scale(scale_client, values, fmt, mode, type_atom)
        reply = scale_client[0].recv_response()
        assert isinstance(reply, X11Error)
        assert reply.error_code == error
        assert self.read_scale(scale_client) == 120

    @pytest.mark.parametrize("operation", ["delete", "read-delete", "configure"])
    def test_contract_cannot_be_removed(self, scale_client, operation):
        client, ext, output, atom = scale_client
        bo = ">" if client.swapped else "<"
        if operation == "delete":
            client.send_request(struct.pack(f"{bo}BBHII", ext.opcode, 14, 3,
                                            output, atom))
        elif operation == "read-delete":
            client.send_request(randr.GetOutputPropertyRequest(
                opcode=ext.opcode, output=output, property_atom=atom,
                delete=True,
            ))
        else:
            # RRConfigureOutputProperty: cannot make scale pending.
            client.send_request(struct.pack(f"{bo}BBHIIBB2xii", ext.opcode,
                                            12, 6, output, atom, 1, 1, 30, 960))
        reply = client.recv_response()
        assert isinstance(reply, X11Error)
        assert reply.error_code == BadAccess
        assert self.read_scale(scale_client) == 120

    def test_does_not_change_existing_output_state(self, scale_client):
        client, ext, output, atom = scale_client
        bo = ">" if client.swapped else "<"
        dpi = client.intern_atom("DPI")

        def snapshot():
            client.send_request(randr.GetScreenResourcesCurrentRequest(
                opcode=ext.opcode, window=client.root_window,
            ))
            resources = client.recv_response()
            assert isinstance(resources, X11Reply)
            n_crtcs = struct.unpack_from(f"{bo}H", resources.data, 16)[0]
            requests = [
                struct.pack(f"{bo}BBHII", ext.opcode, 9, 3, output, 0),
                struct.pack(f"{bo}BBHI", 14, 0, 2, client.root_window),
                randr.GetOutputPropertyRequest(
                    opcode=ext.opcode, output=output, property_atom=dpi,
                ),
            ]
            for i in range(n_crtcs):
                crtc = struct.unpack_from(f"{bo}I", resources.data, 32 + i * 4)[0]
                requests.extend([
                    struct.pack(f"{bo}BBHII", ext.opcode, 20, 3, crtc, 0),
                    struct.pack(f"{bo}BBHI", ext.opcode, 27, 2, crtc),
                ])
            result = [resources.data[8:]]
            for req in requests:
                client.send_request(req)
                reply = client.recv_response()
                assert isinstance(reply, X11Reply)
                result.append(reply.data[8:])  # Exclude request sequence.
            return result

        before = snapshot()
        self.change_scale(scale_client, [180])
        assert self.read_scale(scale_client) == 180
        assert snapshot() == before

    def test_reference_client_rendering_and_input(self, scale_client, xserver):
        demo = os.environ.get("FRACTIONAL_SCALE_DEMO")
        if not demo:
            pytest.skip("Set FRACTIONAL_SCALE_DEMO to the built reference client")
        pytest.importorskip("Xlib")
        from Xlib import X, display, protocol

        def wait_for(check):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                result = check()
                if result:
                    return result
                time.sleep(0.01)
            pytest.fail("Reference client did not reach the expected state")

        dpy = display.Display(xserver.display)
        root = dpy.screen().root
        proc = subprocess.Popen([demo], env={**os.environ, "DISPLAY": xserver.display})
        try:
            def find_window():
                assert proc.poll() is None
                return next((w for w in root.query_tree().children
                             if w.get_wm_name() == "XLibre fractional scaling"), None)

            win = wait_for(find_window)

            def has_size(width, height):
                geometry = win.get_geometry()
                return (geometry.width, geometry.height) == (width, height)

            for scale in (120, 150, 180):
                self.change_scale(scale_client, [scale])
                assert self.read_scale(scale_client) == scale
                wait_for(lambda: has_size(360 * scale // 120, 240 * scale // 120))

            # At 150%, (240, 200) hits logical (160, 133.33) in the button;
            # treating it as unscaled input would miss the button entirely.
            def pixel():
                return win.get_image(240, 200, 1, 1, X.ZPixmap, 0xFFFFFFFF).data

            background = win.get_image(0, 0, 1, 1, X.ZPixmap, 0xFFFFFFFF).data
            wait_for(lambda: pixel() != background)
            before = pixel()
            win.send_event(protocol.event.ButtonPress(
                time=X.CurrentTime, root=root, window=win, child=X.NONE,
                root_x=280, root_y=240, event_x=240, event_y=200,
                state=0, detail=1, same_screen=1,
            ), event_mask=X.ButtonPressMask)
            dpy.flush()
            wait_for(lambda: pixel() != before)

            # Honor a WM/user resize; returning to 100% requests logical size.
            win.configure(width=600, height=400)
            dpy.sync()
            wait_for(lambda: has_size(600, 400))
            self.change_scale(scale_client, [120])
            assert self.read_scale(scale_client) == 120
            wait_for(lambda: has_size(360, 240))
            assert proc.poll() is None
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            dpy.close()
