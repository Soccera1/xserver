/* SPDX-License-Identifier: MIT
 * Minimal client for doc/fractional-scaling.md. Draws vectors/text directly
 * into a window sized in physical pixels; no intermediate scaled bitmap.
 */
#include <stdio.h>
#include <stdlib.h>
#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/Xrandr.h>
#include <cairo/cairo-xlib.h>

#define SCALE_PROPERTY "_XLIBRE_OUTPUT_SCALE"
#define LOGICAL_WIDTH 360
#define LOGICAL_HEIGHT 240

/* Read the server's numerator; older servers have no property. Xlib exposes
 * format-32 property elements as longs even on a 64-bit host. */
static int
output_scale(Display *dpy, RROutput output, Atom property)
{
    Atom type;
    int format, scale = 120;
    unsigned long count, after;
    unsigned char *data = NULL;

    if (XRRGetOutputProperty(dpy, output, property, 0, 1, False, False,
                            XA_INTEGER, &type, &format, &count, &after,
                            &data) == Success &&
        type == XA_INTEGER && format == 32 && count == 1 && after == 0) {
        long value = *(long *) data;
        if (value >= 30 && value <= 960)
            scale = value;
    }
    XFree(data);
    return scale;
}

/* Use a stable anchor (the top-left client pixel), so resizing in response
 * to a scale change cannot itself switch monitors. Popups should instead
 * inherit their parent's scale. RandR monitor rectangles include transforms. */
static int
window_scale(Display *dpy, Window win, Window root, Atom property)
{
    int x, y, count, chosen = -1, scale = 120;
    Window child;
    XRRMonitorInfo *monitors;

    if (!XTranslateCoordinates(dpy, win, root, 0, 0, &x, &y, &child))
        return scale;
    monitors = XRRGetMonitors(dpy, root, True, &count);
    if (!monitors)
        return scale;
    for (int i = 0; i < count; i++) {
        if (chosen < 0 || monitors[i].primary)
            chosen = i;
        if (x >= monitors[i].x && y >= monitors[i].y &&
            x < monitors[i].x + monitors[i].width &&
            y < monitors[i].y + monitors[i].height) {
            chosen = i;
            break;
        }
    }
    if (chosen >= 0 && monitors[chosen].noutput > 0) {
        scale = 30;
        for (int i = 0; i < monitors[chosen].noutput; i++) {
            int value = output_scale(dpy, monitors[chosen].outputs[i], property);
            if (value > scale)
                scale = value;
        }
    }
    XRRFreeMonitors(monitors);
    return scale;
}

/* Rasterize at the actual fractional size, including font rasterization. */
static void
paint(cairo_surface_t *surface, int scale, int clicked)
{
    cairo_t *cr = cairo_create(surface);
    char label[80];

    cairo_set_source_rgb(cr, 0.96, 0.97, 0.98);
    cairo_paint(cr);
    cairo_scale(cr, scale / 120.0, scale / 120.0);
    cairo_set_source_rgb(cr, 0.08, 0.13, 0.2);
    cairo_select_font_face(cr, "sans", CAIRO_FONT_SLANT_NORMAL,
                           CAIRO_FONT_WEIGHT_NORMAL);
    cairo_set_font_size(cr, 22);
    cairo_move_to(cr, 24, 42);
    cairo_show_text(cr, "Native fractional scaling");
    snprintf(label, sizeof(label), "%.2f%% — rendered directly", scale * 100.0 / 120);
    cairo_set_font_size(cr, 16);
    cairo_move_to(cr, 24, 76);
    cairo_show_text(cr, label);
    cairo_set_source_rgb(cr, clicked ? 0.1 : 0.15, clicked ? 0.6 : 0.3, 0.65);
    cairo_rectangle(cr, 24, 108, 160, 48);
    cairo_fill(cr);
    cairo_set_source_rgb(cr, 1, 1, 1);
    cairo_move_to(cr, 40, 138);
    cairo_show_text(cr, clicked ? "Clicked!" : "Click here");
    cairo_set_source_rgb(cr, 0.08, 0.13, 0.2);
    cairo_move_to(cr, 24, 204);
    cairo_show_text(cr, "Move between outputs to change scale.");
    cairo_destroy(cr);
    cairo_surface_flush(surface);
}

int
main(void)
{
    Display *dpy = XOpenDisplay(NULL);
    int event_base, error_base, major = 1, minor = 5;
    int width = LOGICAL_WIDTH, height = LOGICAL_HEIGHT, scale = 0, clicked = 0;
    Window root, win;
    Atom property, protocols, close_atom;
    cairo_surface_t *surface;

    if (!dpy) {
        fprintf(stderr, "Cannot open display\n");
        return EXIT_FAILURE;
    }
    if (!XRRQueryExtension(dpy, &event_base, &error_base) ||
        !XRRQueryVersion(dpy, &major, &minor) ||
        major < 1 || (major == 1 && minor < 5)) {
        fprintf(stderr, "This example requires RandR 1.5\n");
        XCloseDisplay(dpy);
        return EXIT_FAILURE;
    }
    root = DefaultRootWindow(dpy);
    win = XCreateSimpleWindow(dpy, root, 40, 40, width, height, 0, 0, 0);
    XStoreName(dpy, win, "XLibre fractional scaling");
    property = XInternAtom(dpy, SCALE_PROPERTY, False);
    protocols = XInternAtom(dpy, "WM_PROTOCOLS", False);
    close_atom = XInternAtom(dpy, "WM_DELETE_WINDOW", False);
    XSetWMProtocols(dpy, win, &close_atom, 1);
    XSelectInput(dpy, win, ExposureMask | StructureNotifyMask | ButtonPressMask);
    /* Subscribe before the initial read so a concurrent update is not lost. */
    XRRSelectInput(dpy, root, RROutputPropertyNotifyMask | RROutputChangeNotifyMask |
                   RRCrtcChangeNotifyMask | RRScreenChangeNotifyMask |
                   RRResourceChangeNotifyMask);
    surface = cairo_xlib_surface_create(dpy, win,
                                         DefaultVisual(dpy, DefaultScreen(dpy)),
                                         width, height);
    XMapWindow(dpy, win);

    for (;;) {
        int preferred = window_scale(dpy, win, root, property);
        if (preferred != scale) {
            scale = preferred;
            width = (LOGICAL_WIDTH * scale + 60) / 120;
            height = (LOGICAL_HEIGHT * scale + 60) / 120;
            XResizeWindow(dpy, win, width, height);
            cairo_xlib_surface_set_size(surface, width, height);
        }
        paint(surface, scale, clicked);
        XEvent event;
        XNextEvent(dpy, &event);
        if (event.type == ClientMessage && event.xclient.message_type == protocols &&
            event.xclient.format == 32 && (Atom) event.xclient.data.l[0] == close_atom)
            break;
        if (event.type == DestroyNotify)
            break;
        if (event.type == ConfigureNotify && event.xconfigure.window == win) {
            width = event.xconfigure.width;
            height = event.xconfigure.height;
            cairo_xlib_surface_set_size(surface, width, height);
        }
        if (event.type == event_base + RRScreenChangeNotify)
            XRRUpdateConfiguration(&event);
        if (event.type == ButtonPress) {
            /* Input remains in X pixels. Convert once into local UI units. */
            double x = event.xbutton.x * 120.0 / scale;
            double y = event.xbutton.y * 120.0 / scale;
            if (x >= 24 && x < 184 && y >= 108 && y < 156)
                clicked = !clicked;
        }
    }
    cairo_surface_destroy(surface);
    XCloseDisplay(dpy);
    return EXIT_SUCCESS;
}
