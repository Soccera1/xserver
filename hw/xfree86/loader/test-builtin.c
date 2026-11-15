/* SPDX-License-Identifier: MIT */
#undef NDEBUG
#include <xorg-config.h>

#include <assert.h>
#include <string.h>

#include "os.h"
#include "loader.h"
#include "loaderProcs.h"
#include "shadow.h"
#include "xf86.h"
#include "xf86Xinput.h"
#include "xf86Module_priv.h"
#include "xf86_priv.h"
#include "xf86InPriv.h"
#if defined(GLAMOR) && defined(GLAMOR_HAS_GBM)
#define GLAMOR_FOR_XORG
#include "glamor.h"
#endif

#if defined(GLAMOR) && defined(GLAMOR_HAS_GBM)
/* Match the API requested by modesetting, including optional feature builds. */
static void
CheckGlamorSymbols(ModuleDescPtr module)
{
    const char *symbols[] = {
        "glamor_back_pixmap_from_fd",
        "glamor_block_handler",
        "glamor_clear_pixmap",
        "glamor_egl_create_textured_pixmap",
        "glamor_egl_create_textured_pixmap_from_gbm_bo",
        "glamor_egl_exchange_buffers",
        "glamor_egl_get_gbm_device",
        "glamor_egl_init2",
        "glamor_finish",
        "glamor_gbm_bo_from_pixmap",
        "glamor_init",
        "glamor_name_from_pixmap",
        "glamor_set_drawable_modifiers_func",
        "glamor_shareable_fd_from_pixmap",
        "glamor_supports_pixmap_import_export",
#ifdef XV
        "glamor_xv_init",
#endif
        "glamor_egl_get_driver_name",
    };

    for (size_t i = 0; i < ARRAY_SIZE(symbols); i++) {
        void *symbol = LoaderSymbolFromModule(module, symbols[i]);
        assert(symbol && symbol == LoaderSymbol(symbols[i]));
    }
    assert(LoaderSymbolFromModule(module, "glamor_init") == (void *) glamor_init);
    assert(!LoaderSymbolFromModule(module, "shadowAdd"));
}
#endif

/* Exercise real module metadata, setup and teardown without graphics hardware. */
static void
CheckModules(const char *subdir)
{
    const char **modules = LoaderListDir(subdir, NULL);

    assert(modules);
    for (size_t i = 0; modules[i]; i++) {
        int error = 0;
        int input_drivers = xf86NumInputDrivers;
        int video_drivers = xf86NumDrivers;
        ModuleDescPtr module = LoadModule(modules[i], NULL, NULL, &error);
        ModuleDescPtr copy;
        char *symbol;

        assert(module && module != (void *) 1);
        assert(module->VersionInfo);
        assert(!strcmp(module->VersionInfo->modname, modules[i]));
        assert(asprintf(&symbol, "%sModuleData", modules[i]) >= 0);
        assert(LoaderSymbolFromModule(module, symbol) == LoaderSymbol(symbol));
        assert(!LoaderSymbolFromModule(module, "missingSymbol"));
        free(symbol);

        if (!strcmp(subdir, "input"))
            assert(xf86NumInputDrivers == input_drivers + 1);
        if (!strcmp(subdir, "drivers"))
            assert(xf86NumDrivers == video_drivers + 1);

        if (!strcmp(modules[i], "shadow"))
            assert(LoaderSymbolFromModule(module, "shadowAdd") == (void *) shadowAdd);
#if defined(GLXEXT) && defined(BUILD_GLX_DRI) && (defined(DRI2) || defined(DRI3))
        if (!strcmp(modules[i], "glx"))
            assert(LoaderSymbolFromModule(module, "__glXDRI2Provider") ==
                   LoaderSymbol("__glXDRI2Provider"));
#endif
#if defined(GLAMOR) && defined(GLAMOR_HAS_GBM)
        if (!strcmp(modules[i], "glamoregl"))
            CheckGlamorSymbols(module);
#endif

        copy = DuplicateModule(module, NULL);
        assert(copy && copy->handle == module->handle);
        UnloadModule(copy);
        UnloadModule(module);
        free((void *) modules[i]);
    }
    free(modules);
}

int
main(void)
{
    int error = 0;
    XF86ModReqInfo incompatible = {
        .majorversion = 255,
    };
    ModuleDescPtr module;

    /* Built-ins must load even when no module files or search path exist. */
    LoaderInit();
    CheckModules("");
    CheckModules("input");
    CheckModules("drivers");
    CheckModules("extensions");
#if defined(GLXEXT) && defined(BUILD_GLX_DRI) && (defined(DRI2) || defined(DRI3))
    assert(LoaderSymbol("__glXDRI2Provider"));
#else
    assert(!LoaderSymbol("__glXDRI2Provider"));
#endif

    assert(!LoadModule("missing", NULL, NULL, &error));
    assert(error == LDR_NOENT);
    assert(!LoadModule("shadow", NULL, &incompatible, &error));
    assert(error == LDR_MISMATCH);
    assert(!LoaderSymbol("missingSymbol"));

    /* Canonical names, aliases and submodule ownership use the normal loader. */
    module = LoadModule("/nonexistent/libshadow.so", NULL, NULL, &error);
    assert(module);
    assert(LoadSubModule(module, "shadowfb", NULL, NULL, NULL, NULL, &error, NULL));
    UnloadModule(module);
    if (LoaderSymbol("int10ModuleData")) {
        module = LoadModule("vbe", NULL, NULL, &error);
        assert(module && !strcmp(module->VersionInfo->modname, "int10"));
        UnloadModule(module);
    }
    LoaderClose();
    return 0;
}
