/* SPDX-License-Identifier: MIT
 * Experimental native surfaces and physical-output frame transport.
 * The compositor owns scene composition; X retains legacy geometry/input.
 */
#include <dix-config.h>
#include <X11/Xatom.h>
#include "dix/dix_priv.h"
#include "dix/request_priv.h"
#include "dix/selection_priv.h"
#include "dix/resource_priv.h"
#include "rrfractionalscale.h"
#include "gcstruct.h"
#include "pixmapstr.h"
#include "windowstr.h"
#include "property.h"
#include "Xext/randr/randrstr_priv.h"

/* All requests are 20 bytes and replies 32 bytes, including swapped clients. */
typedef xXLFractionalScaleReq FractionalScaleRequest;
typedef xXLFractionalScaleReply FractionalScaleReply;

typedef struct fractional_scale_output {
    struct fractional_scale_output *next;
    RRCrtcPtr crtc;
    RRFractionalScaleQueryProc query;
    RRFractionalScaleDamageProc damage;
    ClientPtr owner;
    XID session;
    CARD32 epoch;
    PixmapPtr frame;
} FractionalScaleOutput;

typedef struct {
    PixmapPtr pixmap;
    RRCrtc crtc;
    CARD32 epoch;
    unsigned width, height; /* Legacy window dimensions at attachment time. */
} NativeSurface;

static FractionalScaleOutput *outputs;
static RESTYPE session_type, surface_type;
static CARD32 notification;

/* Core PropertyNotify is only an invalidation hint. Authoritative state is
 * always read through this extension, never trusted from a mutable property. */
static void
notify(ScreenPtr screen)
{
    if (screen->isGPU)
        screen = screen->current_primary;
    if (!screen || !screen->root || (dispatchException & DE_TERMINATE))
        return;
    Atom atom = dixAddAtom("_XLIBRE_FRACTIONAL_SCALE_STATE");
    CARD32 value = ++notification;
    if (atom != BAD_RESOURCE)
        dixChangeWindowProperty(serverClient, screen->root, atom, XA_CARDINAL,
                                 32, PropModeReplace, 1, &value, TRUE);
}

static FractionalScaleOutput *
find_output(RRCrtcPtr crtc)
{
    for (FractionalScaleOutput *o = outputs; o; o = o->next)
        if (o->crtc == crtc)
            return o;
    return NULL;
}

/* The screen's current compositing-manager selection gates output ownership. */
static Bool
is_compositor(ClientPtr client, ScreenPtr screen)
{
    char name[64];
    Selection *selection;
    snprintf(name, sizeof(name), "_NET_WM_CM_S%d", screen->myNum);
    Atom atom = dixGetAtomID(name);
    return atom && dixLookupSelection(&selection, atom, client,
                                      DixReadAccess) == Success &&
           selection->client == client && selection->window != None;
}

/* Resource teardown also covers compositor disconnects. Clear state before
 * scheduling repaint so a reentrant DDX always sees the fallback path. */
static int
free_session(void *value, XID id)
{
    FractionalScaleOutput *o = value;
    PixmapPtr frame = o->frame;
    o->frame = NULL;
    o->session = None;
    o->owner = NULL;
    ++o->epoch;
    if (frame)
        dixDestroyPixmap(frame, 0);
    o->damage(o->crtc);
    notify(o->crtc->pScreen);
    return Success;
}

static int
free_surface(void *value, XID id)
{
    NativeSurface *surface = value;
    ScreenPtr screen = surface->pixmap->drawable.pScreen;
    dixDestroyPixmap(surface->pixmap, 0);
    free(surface);
    notify(screen);
    return Success;
}

/* Snapshot submission prevents client writes or freed/reused XIDs from
 * changing a queued frame. GPU producers must finish rendering before submit. */
static PixmapPtr
snapshot(PixmapPtr source)
{
    ScreenPtr screen = source->drawable.pScreen;
    PixmapPtr copy = screen->CreatePixmap(screen, source->drawable.width,
                                          source->drawable.height,
                                          source->drawable.depth, 0);
    if (!copy)
        return NULL;
    GCPtr gc = GetScratchGC(source->drawable.depth, screen);
    if (!gc) {
        dixDestroyPixmap(copy, 0);
        return NULL;
    }
    ValidateGC(&copy->drawable, gc);
    gc->ops->CopyArea(&source->drawable, &copy->drawable, gc, 0, 0,
                      source->drawable.width, source->drawable.height, 0, 0);
    FreeScratchGC(gc);
    return copy;
}

Bool
RRFractionalScaleRegisterCrtc(RRCrtcPtr crtc, RRFractionalScaleQueryProc query,
                     RRFractionalScaleDamageProc damage)
{
    FractionalScaleOutput *o = find_output(crtc);
    if (!o) {
        o = calloc(1, sizeof(*o));
        if (!o)
            return FALSE;
        o->next = outputs;
        outputs = o;
        o->crtc = crtc;
        o->epoch = 1;
    }
    o->query = query;
    o->damage = damage;
    return TRUE;
}

void
RRFractionalScaleCrtcChanged(RRCrtcPtr crtc)
{
    FractionalScaleOutput *o = find_output(crtc);
    if (!o)
        return;
    if (o->session)
        FreeResource(o->session, 0);
    else {
        ++o->epoch;
        notify(crtc->pScreen);
    }
}

void
RRFractionalScaleCrtcDestroy(RRCrtcPtr crtc)
{
    FractionalScaleOutput **link = &outputs;
    while (*link && (*link)->crtc != crtc)
        link = &(*link)->next;
    if (*link) {
        FractionalScaleOutput *o = *link;
        if (o->session)
            FreeResource(o->session, 0);
        *link = o->next;
        free(o);
    }
}

/* Invalidate on selection loss even if the old compositor stays connected. */
static void
selection_changed(CallbackListPtr *list, void *closure, void *data)
{
    SelectionInfoRec *info = data;
    for (FractionalScaleOutput *o = outputs; o; o = o->next) {
        char name[64];
        snprintf(name, sizeof(name), "_NET_WM_CM_S%d", o->crtc->pScreen->myNum);
        if (o->session && info->selection->selection == dixGetAtomID(name) &&
            (info->kind != SelectionSetOwner || info->selection->client != o->owner))
            FreeResource(o->session, 0);
    }
}

Bool
RRFractionalScaleCopyFrame(RRCrtcPtr crtc, PixmapPtr destination)
{
    FractionalScaleOutput *o = find_output(crtc);
    if (!o || !o->session || !o->frame)
        return FALSE;
    if (!o->query(crtc) || RRCrtcIsLeased(crtc) ||
        !is_compositor(o->owner, crtc->pScreen)) {
        FreeResource(o->session, 0);
        return FALSE;
    }
    PixmapPtr source = o->frame;
    if (source->drawable.width != destination->drawable.width ||
        source->drawable.height != destination->drawable.height ||
        source->drawable.depth != destination->drawable.depth)
        return FALSE;
    GCPtr gc = GetScratchGC(source->drawable.depth, crtc->pScreen);
    if (!gc)
        return FALSE;
    ValidateGC(&destination->drawable, gc);
    gc->ops->CopyArea(&source->drawable, &destination->drawable, gc, 0, 0,
                      source->drawable.width, source->drawable.height, 0, 0);
    FreeScratchGC(gc);
    return TRUE;
}

static int
reply(ClientPtr client, FractionalScaleReply *r)
{
    if (client->swapped) {
        swapl(&r->a); swapl(&r->b); swapl(&r->c);
        swapl(&r->d); swapl(&r->e); swapl(&r->f);
    }
    return X_SEND_REPLY_SIMPLE(client, *r);
}

static int
lookup_pixmap(ClientPtr client, XID id, ScreenPtr screen, PixmapPtr *pixmap)
{
    int rc = dixLookupResourceByType((void **) pixmap, id, RT_PIXMAP,
                                     client, DixReadAccess);
    if (rc != Success)
        return rc;
    if ((*pixmap)->drawable.pScreen != screen)
        return BadMatch;
    return Success;
}

/* QueryVersion, QueryCrtc, Acquire, Submit, Release, AttachSurface,
 * NameSurface, ReadFrame. Every successful operation has a reply. */
static int
dispatch(ClientPtr client)
{
    REQUEST(FractionalScaleRequest);
    REQUEST_SIZE_MATCH(FractionalScaleRequest);
    if (client->swapped) {
        swapl(&stuff->a); swapl(&stuff->b);
        swapl(&stuff->c); swapl(&stuff->d);
    }
    FractionalScaleReply r = { 0 };
    FractionalScaleOutput *o = NULL;
    RRCrtcPtr crtc;
    WindowPtr window;
    PixmapPtr pixmap, copy;
    NativeSurface *surface = NULL;
    int rc;

    if (stuff->minor == 0) {
        r.a = 0;
        r.b = 1;
        return reply(client, &r);
    }
    if (stuff->minor == 1 || stuff->minor == 2) {
        rc = dixLookupResourceByType((void **) &crtc, stuff->a, RRCrtcType,
                                      client, DixReadAccess);
        if (rc != Success)
            return rc;
        o = find_output(crtc);
        if (stuff->minor == 1) {
            if (o) {
                unsigned cap = RRCrtcIsLeased(crtc) ? 0 : o->query(crtc);
                if (o->session && (!cap || !is_compositor(o->owner, crtc->pScreen)))
                    FreeResource(o->session, 0);
                r.a = cap | (o->frame ? RR_FRACTIONAL_SCALE_ACTIVE : 0);
                r.b = o->epoch;
            }
            if (crtc->mode) {
                r.c = crtc->mode->mode.width;
                r.d = crtc->mode->mode.height;
            }
            return reply(client, &r);
        }
        if (!o || !o->query(crtc) || !crtc->mode || RRCrtcIsLeased(crtc))
            return BadMatch;
        if (!is_compositor(client, crtc->pScreen) || o->session)
            return BadAccess;
        if (stuff->c != o->epoch)
            return BadMatch;
        LEGAL_NEW_RESOURCE(stuff->b, client);
        if (!AddResource(stuff->b, session_type, o))
            return BadAlloc;
        o->session = stuff->b;
        o->owner = client;
        r.a = ++o->epoch;
        notify(crtc->pScreen);
        return reply(client, &r);
    }
    if (stuff->minor == 3 || stuff->minor == 4 || stuff->minor == 7) {
        rc = dixLookupResourceByType((void **) &o, stuff->a, session_type,
                                      client, DixWriteAccess);
        if (rc != Success)
            return rc;
        if (o->owner != client || !is_compositor(client, o->crtc->pScreen))
            return BadAccess;
        if (stuff->minor == 4) {
            FreeResource(stuff->a, 0);
            return reply(client, &r);
        }
        if (!o->query(o->crtc) || RRCrtcIsLeased(o->crtc) ||
            !o->crtc->mode || stuff->c != o->epoch)
            return BadMatch;
        if (stuff->minor == 7) {
            LEGAL_NEW_RESOURCE(stuff->b, client);
            if (!o->frame)
                return BadMatch;
            copy = o->crtc->pScreen->CreatePixmap(o->crtc->pScreen,
                o->frame->drawable.width, o->frame->drawable.height,
                o->frame->drawable.depth, 0);
            if (!copy)
                return BadAlloc;
            if (!RRFractionalScaleCopyFrame(o->crtc, copy)) {
                dixDestroyPixmap(copy, 0);
                return BadMatch;
            }
            if (!AddResource(stuff->b, RT_PIXMAP, copy))
                return BadAlloc;
            return reply(client, &r);
        }
        rc = lookup_pixmap(client, stuff->b, o->crtc->pScreen, &pixmap);
        if (rc != Success)
            return rc;
        if (pixmap->drawable.width != o->crtc->mode->mode.width ||
            pixmap->drawable.height != o->crtc->mode->mode.height ||
            pixmap->drawable.depth != o->crtc->pScreen->rootDepth)
            return BadMatch;
        copy = snapshot(pixmap);
        if (!copy)
            return BadAlloc;
        Bool first = o->frame == NULL;
        if (o->frame)
            dixDestroyPixmap(o->frame, 0);
        o->frame = copy;
        o->damage(o->crtc);
        if (first)
            notify(o->crtc->pScreen);
        return reply(client, &r);
    }
    if (stuff->minor != 5 && stuff->minor != 6)
        return BadRequest;
    rc = dixLookupWindow(&window, stuff->a, client,
                          stuff->minor == 5 ? DixWriteAccess : DixReadAccess);
    if (rc != Success)
        return rc;
    if (window->drawable.class != InputOutput || !window->parent)
        return BadMatch;
    if (stuff->minor == 5 && dixClientIdForXID(stuff->a) != client->index)
        return BadAccess;
    if (stuff->minor == 5 && stuff->b == None) {
        FreeResourceByType(stuff->a, surface_type, FALSE);
        return reply(client, &r);
    }
    rc = dixLookupResourceByType((void **) &crtc, stuff->c, RRCrtcType,
                                  client, DixReadAccess);
    if (rc != Success)
        return rc;
    o = find_output(crtc);
    if (!o || !o->frame || !o->query(crtc) || RRCrtcIsLeased(crtc) ||
        stuff->d != o->epoch ||
        crtc->pScreen != window->drawable.pScreen ||
        !is_compositor(o->owner, crtc->pScreen))
        return BadMatch;
    if (stuff->minor == 6) {
        if (o->owner != client)
            return BadAccess;
        LEGAL_NEW_RESOURCE(stuff->b, client);
        rc = dixLookupResourceByType((void **) &surface, stuff->a, surface_type,
                                      client, DixReadAccess);
        if (rc != Success && rc != BadValue)
            return rc;
        if (rc != Success || surface->crtc != crtc->id ||
            surface->epoch != o->epoch || surface->width != window->drawable.width ||
            surface->height != window->drawable.height)
            return reply(client, &r); /* Use the normal Composite pixmap. */
        ++surface->pixmap->refcnt;
        if (!AddResource(stuff->b, RT_PIXMAP, surface->pixmap))
            return BadAlloc;
        r.a = 1;
        r.b = surface->pixmap->drawable.width;
        r.c = surface->pixmap->drawable.height;
        r.d = surface->width;
        r.e = surface->height;
        return reply(client, &r);
    }
    rc = lookup_pixmap(client, stuff->b, window->drawable.pScreen, &pixmap);
    if (rc != Success)
        return rc;
    /* Depth 32 allows premultiplied ARGB; otherwise use the window's visual. */
    if (pixmap->drawable.depth != window->drawable.depth && pixmap->drawable.depth != 32)
        return BadMatch;
    surface = calloc(1, sizeof(*surface));
    if (!surface)
        return BadAlloc;
    surface->pixmap = snapshot(pixmap);
    if (!surface->pixmap) {
        free(surface);
        return BadAlloc;
    }
    surface->crtc = crtc->id;
    surface->epoch = o->epoch;
    surface->width = window->drawable.width;
    surface->height = window->drawable.height;
    NativeSurface *previous;
    rc = dixLookupResourceByType((void **) &previous, stuff->a, surface_type,
                                 client, DixWriteAccess);
    if (rc != Success && rc != BadValue) {
        dixDestroyPixmap(surface->pixmap, 0);
        free(surface);
        return rc;
    }
    if (rc == Success) {
        PixmapPtr old = previous->pixmap;
        *previous = *surface;
        free(surface);
        dixDestroyPixmap(old, 0);
    }
    else if (!AddResource(stuff->a, surface_type, surface))
        return BadAlloc;
    notify(window->drawable.pScreen);
    return reply(client, &r);
}

static void
reset(ExtensionEntry *entry)
{
    DeleteCallback(&SelectionCallback, selection_changed, NULL);
}

void
RRFractionalScaleExtensionInit(void)
{
    session_type = CreateNewResourceType(free_session, "FractionalScaleOutputSession");
    surface_type = CreateNewResourceType(free_surface, "NativeSurface");
    if (!session_type || !surface_type)
        return;
    if (!AddCallback(&SelectionCallback, selection_changed, NULL))
        return;
    if (!AddExtension(XLFRACTIONALSCALE_NAME, 0, 0, dispatch, dispatch, reset,
                      StandardMinorOpcode))
        DeleteCallback(&SelectionCallback, selection_changed, NULL);
}
