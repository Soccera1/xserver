/* SPDX-License-Identifier: MIT */
#ifndef RR_FRACTIONAL_SCALE_H
#define RR_FRACTIONAL_SCALE_H
#include "randrstr.h"
#include "xlibre-fractional-scaleproto.h"

/* Experimental XLIBRE-FRACTIONAL-SCALE 0.1. See doc/mixed-scaling.md. */
#define RR_FRACTIONAL_SCALE_OUTPUT XLFRACTIONALSCALE_OUTPUT
#define RR_FRACTIONAL_SCALE_OFFSCREEN XLFRACTIONALSCALE_OFFSCREEN
#define RR_FRACTIONAL_SCALE_ACTIVE XLFRACTIONALSCALE_ACTIVE

typedef unsigned (*RRFractionalScaleQueryProc)(RRCrtcPtr crtc);
typedef void (*RRFractionalScaleDamageProc)(RRCrtcPtr crtc);

/* Register a DDX which can consume physical-resolution output frames. */
extern _X_EXPORT Bool RRFractionalScaleRegisterCrtc(RRCrtcPtr crtc,
                                          RRFractionalScaleQueryProc query,
                                          RRFractionalScaleDamageProc damage);
/* Copy the compositor's final frame 1:1, before any legacy scanout transform.
 * Returns FALSE when the ordinary scanout path must be used instead. */
extern _X_EXPORT Bool RRFractionalScaleCopyFrame(RRCrtcPtr crtc, PixmapPtr destination);
void RRFractionalScaleExtensionInit(void);
void RRFractionalScaleCrtcChanged(RRCrtcPtr crtc);
void RRFractionalScaleCrtcDestroy(RRCrtcPtr crtc);
#endif
