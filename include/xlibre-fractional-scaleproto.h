/* SPDX-License-Identifier: MIT
 * Experimental, versioned wire contract; see doc/mixed-scaling.md.
 */
#ifndef XLIBRE_FRACTIONAL_SCALEPROTO_H
#define XLIBRE_FRACTIONAL_SCALEPROTO_H
#include <X11/Xmd.h>
#define XLFRACTIONALSCALE_NAME "XLIBRE-FRACTIONAL-SCALE"
#define XLFRACTIONALSCALE_MAJOR 0
#define XLFRACTIONALSCALE_MINOR 1
#define XLFRACTIONALSCALE_QUERY_VERSION 0
#define XLFRACTIONALSCALE_QUERY_CRTC 1
#define XLFRACTIONALSCALE_ACQUIRE 2
#define XLFRACTIONALSCALE_SUBMIT 3
#define XLFRACTIONALSCALE_RELEASE 4
#define XLFRACTIONALSCALE_ATTACH_SURFACE 5
#define XLFRACTIONALSCALE_NAME_SURFACE 6
#define XLFRACTIONALSCALE_READ_FRAME 7
#define XLFRACTIONALSCALE_OUTPUT 1
#define XLFRACTIONALSCALE_OFFSCREEN 2
#define XLFRACTIONALSCALE_ACTIVE 4

typedef struct {
    CARD8 reqType, minor;
    CARD16 length;
    CARD32 a, b, c, d;
} xXLFractionalScaleReq;
#define sz_xXLFractionalScaleReq 20

typedef struct {
    CARD8 type, pad;
    CARD16 sequenceNumber;
    CARD32 length;
    CARD32 a, b, c, d, e, f;
} xXLFractionalScaleReply;
#define sz_xXLFractionalScaleReply 32
#endif
