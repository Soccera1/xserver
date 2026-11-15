/*
 * Copyright © 2008 Red Hat, Inc
 *
 * Permission to use, copy, modify, distribute, and sell this software
 * and its documentation for any purpose is hereby granted without
 * fee, provided that the above copyright notice appear in all copies
 * and that both that copyright notice and this permission notice
 * appear in supporting documentation, and that the name of the
 * copyright holders not be used in advertising or publicity
 * pertaining to distribution of the software without specific,
 * written prior permission.  The copyright holders make no
 * representations about the suitability of this software for any
 * purpose.  It is provided "as is" without express or implied
 * warranty.
 *
 * THE COPYRIGHT HOLDERS DISCLAIM ALL WARRANTIES WITH REGARD TO THIS
 * SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
 * FITNESS, IN NO EVENT SHALL THE COPYRIGHT HOLDERS BE LIABLE FOR ANY
 * SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
 * WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN
 * AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING
 * OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS
 * SOFTWARE.
 */

/* SPDX-License-Identifier: MIT */
/* DRI extension loading shared by the GLX software and DRI2 providers. */
#include <dix-config.h>

#include <GL/internal/dri_interface.h>
#include "os.h"
#include "glxdriload.h"

#ifdef XSERVER_STATIC
#ifndef GLX_BUILTIN_DRI_DRIVERS
#define GLX_BUILTIN_DRI_DRIVERS "builtin-dri-drivers.h"
#endif

#define BUILTIN_DRI_DRIVER(name, symbol) extern const __DRIextension **symbol(void);
#include GLX_BUILTIN_DRI_DRIVERS
#undef BUILTIN_DRI_DRIVER

static const struct {
    const char *name;
    const __DRIextension **(*get_extensions)(void);
} builtin_dri_drivers[] = {
#define BUILTIN_DRI_DRIVER(name, symbol) { name, symbol },
#include GLX_BUILTIN_DRI_DRIVERS
#undef BUILTIN_DRI_DRIVER
    { NULL, NULL },
};
#else
#include <ctype.h>
#include <dlfcn.h>
#include <limits.h>
#endif

void
glxReleaseDriver(void *driver)
{
#ifndef XSERVER_STATIC
    if (driver)
        dlclose(driver);
#endif
}

#ifndef XSERVER_STATIC
static const char dri_driver_path[] = DRI_DRIVER_PATH;

/* Temporary define to allow building without a dri_interface.h from
 * updated Mesa.  Some day when we don't care about Mesa that old any
 * more this can be removed.
 */
#ifndef __DRI_DRIVER_GET_EXTENSIONS
#define __DRI_DRIVER_GET_EXTENSIONS "__driDriverGetExtensions"
#endif

#endif

void *
glxProbeDriver(const char *driverName,
               void **coreExt, const char *coreName, int coreVersion,
               void **renderExt, const char *renderName, int renderVersion)
{
    void *driver = NULL;
    const __DRIextension **extensions = NULL;

    *coreExt = *renderExt = NULL;

#ifdef XSERVER_STATIC
    for (size_t i = 0; builtin_dri_drivers[i].name; i++) {
        if (!strcmp(driverName, builtin_dri_drivers[i].name)) {
            driver = (void *) &builtin_dri_drivers[i];
            extensions = builtin_dri_drivers[i].get_extensions();
            break;
        }
    }
    if (!driver || !extensions) {
        LogMessage(X_ERROR, "AIGLX error: no built-in DRI extensions for %s\n", driverName);
        goto cleanup_failure;
    }
#else
    char filename[PATH_MAX];
    char *get_extensions_name;
    const char *path = NULL;

    /* Search in LIBGL_DRIVERS_PATH if we're not setuid. */
    if (!PrivsElevated())
        path = getenv("LIBGL_DRIVERS_PATH");

    if (!path)
        path = dri_driver_path;

    do {
        const char *next;
        int path_len;

        next = strchr(path, ':');
        if (next) {
            path_len = next - path;
            next++;
        } else {
            path_len = strlen(path);
            next = NULL;
        }

        snprintf(filename, sizeof filename, "%.*s/%s_dri.so", path_len, path,
                 driverName);

        driver = dlopen(filename, RTLD_LAZY | RTLD_LOCAL);
        if (driver != NULL)
            break;

        LogMessage(X_ERROR, "AIGLX error: dlopen of %s failed (%s)\n",
                   filename, dlerror());

        path = next;
    } while (path);

    if (driver == NULL) {
        LogMessage(X_ERROR, "AIGLX error: unable to load driver %s\n",
                  driverName);
        goto cleanup_failure;
    }

    if (asprintf(&get_extensions_name, "%s_%s",
                 __DRI_DRIVER_GET_EXTENSIONS, driverName) != -1) {
        const __DRIextension **(*get_extensions)(void);

        for (unsigned int i = 0; i < strlen(get_extensions_name); i++) {
            /* Replace all non-alphanumeric characters with underscore,
             * since they are not allowed in C symbol names. That fixes up
             * symbol name for drivers with '-drm' suffix
             */
            if (!isalnum((unsigned char)get_extensions_name[i]))
                get_extensions_name[i] = '_';
        }

        get_extensions = dlsym(driver, get_extensions_name);
        if (get_extensions)
            extensions = get_extensions();
        free(get_extensions_name);
    }

    if (!extensions)
        extensions = dlsym(driver, __DRI_DRIVER_EXTENSIONS);
    if (extensions == NULL) {
        LogMessage(X_ERROR, "AIGLX error: %s exports no extensions (%s)\n",
                   driverName, dlerror());
        goto cleanup_failure;
    }

#endif

    for (unsigned int i = 0; extensions[i]; i++) {
        if (strcmp(extensions[i]->name, coreName) == 0 &&
            extensions[i]->version >= coreVersion) {
            *coreExt = (void *) extensions[i];
        }

        if (strcmp(extensions[i]->name, renderName) == 0 &&
            extensions[i]->version >= renderVersion) {
            *renderExt = (void *) extensions[i];
        }
    }

    if (*coreExt == NULL || *renderExt == NULL) {
        LogMessage(X_ERROR,
                   "AIGLX error: %s does not export required DRI extension\n",
                   driverName);
        goto cleanup_failure;
    }
    return driver;

 cleanup_failure:
    glxReleaseDriver(driver);
    *coreExt = *renderExt = NULL;
    return NULL;
}
