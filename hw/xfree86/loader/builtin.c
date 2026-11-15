/* SPDX-License-Identifier: MIT */
/* Module loading for servers which cannot use dlopen, including static musl. */
#include <xorg-config.h>

#include <string.h>

#include "os.h"
#include "loader.h"
#include "loaderProcs.h"
#include "shadow.h"
#if defined(GLAMOR) && defined(GLAMOR_HAS_GBM)
#include "xf86.h"
#define GLAMOR_FOR_XORG
#include "glamor.h"
#endif
#if defined(GLXEXT) && defined(BUILD_GLX_DRI) && (defined(DRI2) || defined(DRI3))
#include "glx_extinit.h"
extern __GLXprovider __glXDRI2Provider;
#endif

#define BUILTIN_MODULE(name, subdir) extern XF86ModuleData name##ModuleData;
#include "builtin-modules.h"
#undef BUILTIN_MODULE

/* Each handle identifies the same metadata used by the shared module loader. */
static const struct builtin_module {
    const char *name;
    const char *subdir;
    const char *symbol;
    XF86ModuleData *data;
} builtin_modules[] = {
#define BUILTIN_MODULE(name, subdir) \
    { #name, subdir, #name "ModuleData", &name##ModuleData },
#include "builtin-modules.h"
#undef BUILTIN_MODULE
};

/* The modesetting driver obtains the shadow API through its module handle. */
static void *
ShadowSymbol(const char *name)
{
    static const struct {
        const char *name;
        void *address;
    } symbols[] = {
        { "shadowSetup", (void *) shadowSetup },
        { "shadowAdd", (void *) shadowAdd },
        { "shadowRemove", (void *) shadowRemove },
        { "shadowUpdate32to24", (void *) shadowUpdate32to24 },
        { "shadowUpdatePacked", (void *) shadowUpdatePacked },
    };

    for (size_t i = 0; i < ARRAY_SIZE(symbols); i++) {
        if (!strcmp(name, symbols[i].name))
            return symbols[i].address;
    }
    return NULL;
}

#if defined(GLAMOR) && defined(GLAMOR_HAS_GBM)
/* Public entry points resolved by the in-tree modesetting driver. */
static void *
GlamorSymbol(const char *name)
{
    static const struct {
        const char *name;
        void *address;
    } symbols[] = {
        { "glamor_back_pixmap_from_fd", (void *) glamor_back_pixmap_from_fd },
        { "glamor_block_handler", (void *) glamor_block_handler },
        { "glamor_clear_pixmap", (void *) glamor_clear_pixmap },
        { "glamor_egl_create_textured_pixmap", (void *) glamor_egl_create_textured_pixmap },
        { "glamor_egl_create_textured_pixmap_from_gbm_bo", (void *) glamor_egl_create_textured_pixmap_from_gbm_bo },
        { "glamor_egl_exchange_buffers", (void *) glamor_egl_exchange_buffers },
        { "glamor_egl_get_gbm_device", (void *) glamor_egl_get_gbm_device },
        { "glamor_egl_init2", (void *) glamor_egl_init2 },
        { "glamor_finish", (void *) glamor_finish },
        { "glamor_gbm_bo_from_pixmap", (void *) glamor_gbm_bo_from_pixmap },
        { "glamor_init", (void *) glamor_init },
        { "glamor_name_from_pixmap", (void *) glamor_name_from_pixmap },
        { "glamor_set_drawable_modifiers_func", (void *) glamor_set_drawable_modifiers_func },
        { "glamor_shareable_fd_from_pixmap", (void *) glamor_shareable_fd_from_pixmap },
        { "glamor_supports_pixmap_import_export", (void *) glamor_supports_pixmap_import_export },
#ifdef XV
        { "glamor_xv_init", (void *) glamor_xv_init },
#endif
        { "glamor_egl_get_driver_name", (void *) glamor_egl_get_driver_name },
    };

    for (size_t i = 0; i < ARRAY_SIZE(symbols); i++) {
        if (!strcmp(name, symbols[i].name))
            return symbols[i].address;
    }
    return NULL;
}
#endif

void *
LoaderOpen(const char *name, int *errmaj)
{
    for (size_t i = 0; i < ARRAY_SIZE(builtin_modules); i++) {
        if (!strcmp(name, builtin_modules[i].name)) {
            LogMessage(X_INFO, "Loading built-in module %s\n", name);
            return (void *) &builtin_modules[i];
        }
    }

    LogMessage(X_ERROR, "Module %s is not built into this static server\n", name);
    if (errmaj)
        *errmaj = LDR_NOENT;
    return NULL;
}

void *
LoaderSymbol(const char *name)
{
    for (size_t i = 0; i < ARRAY_SIZE(builtin_modules); i++) {
        if (!strcmp(name, builtin_modules[i].symbol))
            return builtin_modules[i].data;
    }
#if defined(GLXEXT) && defined(BUILD_GLX_DRI) && (defined(DRI2) || defined(DRI3))
    if (!strcmp(name, "__glXDRI2Provider"))
        return &__glXDRI2Provider;
#endif
#if defined(GLAMOR) && defined(GLAMOR_HAS_GBM)
    void *symbol = GlamorSymbol(name);
    if (symbol)
        return symbol;
#endif
    return ShadowSymbol(name);
}

void *
LoaderSymbolFromModule(void *handle, const char *name)
{
    ModuleDescPtr mod = handle;
    const struct builtin_module *builtin = mod->handle;

    if (!strcmp(name, builtin->symbol))
        return builtin->data;
#if defined(GLXEXT) && defined(BUILD_GLX_DRI) && (defined(DRI2) || defined(DRI3))
    if (!strcmp(builtin->name, "glx") && !strcmp(name, "__glXDRI2Provider"))
        return &__glXDRI2Provider;
#endif
    if (!strcmp(builtin->name, "shadow"))
        return ShadowSymbol(name);
#if defined(GLAMOR) && defined(GLAMOR_HAS_GBM)
    if (!strcmp(builtin->name, "glamoregl"))
        return GlamorSymbol(name);
#endif
    return NULL;
}

void
LoaderUnload(const char *name, void *handle)
{
    /* Setup/teardown still run in loadmod.c; built-in code stays resident. */
    LogMessageVerb(X_INFO, 1, "Unloading built-in module %s\n", name);
}

const char **
LoaderListBuiltinModules(const char *subdir)
{
    char **list = calloc(ARRAY_SIZE(builtin_modules) + 1, sizeof(*list));
    size_t count = 0;

    if (!list)
        return NULL;

    for (size_t i = 0; i < ARRAY_SIZE(builtin_modules); i++) {
        if (strcmp(subdir, builtin_modules[i].subdir))
            continue;
        list[count] = strdup(builtin_modules[i].name);
        if (!list[count]) {
            while (count)
                free(list[--count]);
            free(list);
            return NULL;
        }
        count++;
    }
    return (const char **) list;
}
