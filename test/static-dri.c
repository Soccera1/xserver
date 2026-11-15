/* SPDX-License-Identifier: MIT */
#include <dix-config.h>
#undef NDEBUG
#include <assert.h>
#include <GL/internal/dri_interface.h>

#include "os.h"
#include "Xext/glx/glx_dri/glxdriload.h"

#define BUILTIN_DRI_DRIVER(name, symbol) extern const __DRIextension **symbol(void);
#include "builtin-dri-drivers.h"
#undef BUILTIN_DRI_DRIVER

static const __DRIextension core = { __DRI_CORE, 3 };
static const __DRIextension render = { __DRI_SWRAST, 4 };
static const __DRIextension *extensions[] = { &core, &render, NULL };
static const __DRIextension *no_core[] = { &render, NULL };
static const __DRIextension *no_render[] = { &core, NULL };

const __DRIextension **
__driDriverGetExtensions_test(void)
{
    return extensions;
}

const __DRIextension **
__driDriverGetExtensions_test_alias(void)
{
    return extensions;
}

const __DRIextension **
__driDriverGetExtensions_empty(void)
{
    return NULL;
}

const __DRIextension **
__driDriverGetExtensions_no_core(void)
{
    return no_core;
}

const __DRIextension **
__driDriverGetExtensions_no_render(void)
{
    return no_render;
}

/* The loader's diagnostics need no initialized server or log file here. */
void
LogMessage(MessageType type, const char *format, ...)
{
}

static void
CheckFailure(const char *name, int core_version, int render_version)
{
    void *core_ext = (void *) &core;
    void *render_ext = (void *) &render;

    assert(!glxProbeDriver(name, &core_ext, __DRI_CORE, core_version,
                          &render_ext, __DRI_SWRAST, render_version));
    assert(!core_ext && !render_ext);
}

int
main(void)
{
    void *core_ext = NULL;
    void *render_ext = NULL;
    void *handle, *reopened;

    assert(!setenv("LIBGL_DRIVERS_PATH", "/nonexistent", 1));
    handle = glxProbeDriver("test", &core_ext, __DRI_CORE, 3,
                            &render_ext, __DRI_SWRAST, 4);
    assert(handle && core_ext == &core && render_ext == &render);
    glxReleaseDriver(handle);
    reopened = glxProbeDriver("test", &core_ext, __DRI_CORE, 1,
                              &render_ext, __DRI_SWRAST, 1);
    assert(reopened == handle);
    glxReleaseDriver(reopened);
    glxReleaseDriver(NULL);

    handle = glxProbeDriver("test-alias", &core_ext, __DRI_CORE, 1,
                            &render_ext, __DRI_SWRAST, 1);
    assert(handle && core_ext == &core && render_ext == &render);
    glxReleaseDriver(handle);

    CheckFailure("unregistered", 1, 1);
    CheckFailure("empty", 1, 1);
    CheckFailure("no-core", 1, 1);
    CheckFailure("no-render", 1, 1);
    CheckFailure("test", 4, 1);
    CheckFailure("test", 1, 5);
    return 0;
}
