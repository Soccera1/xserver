# Static Linux servers

`-Dstatic=true` links the servers and their dependencies statically on Linux,
with either musl or glibc. Xorg's enabled in-tree modules become archives linked
into Xorg. Module discovery, version checks, setup and teardown use their usual
metadata and entry points, without `dlopen` or files in the module directory.
The default shared build is unchanged.

Install static archives and pkg-config files for every enabled dependency,
including the private dependencies reported by `pkg-config --static`. All
archives must use the same target architecture and libc. For cross compilation,
use a Meson cross file and a pkg-config sysroot for that target.

For example, this builds Xorg, Xvfb and the Linux framebuffer server Xfbdev:

```sh
meson setup build-static --prefix=/usr \
    -Dstatic=true -Dxorg=true -Dxvfb=true -Dxfbdev=true -Dxnest=false \
    -Dglx=false -Dglamor=false -Dgbm=false \
    -Dudev=false -Dudev_kms=false -Dseatd_libseat=false \
    -Dsystemd_logind=false -Dsystemd_notify=false -Dxselinux=false \
    -Ddocs=false -Ddevel-docs=false
meson compile -C build-static
meson test -C build-static --suite static
```

The CI recipe in [build-static.yml](../.github/workflows/build-static.yml)
builds and tests both libc variants. Its dependency helper also shows how to
build archives that development packages omit. In particular, libxcvt 0.1.3
hardcodes a shared library target; change that target to `library()` before
building it with `-Ddefault_library=static`.

## GLX and glamor

XLibre supports linking both modules into static Xorg. Enabling either feature
also requires graphics libraries that can operate inside a static process.
The non-graphics build above is supported with distribution libraries plus
the missing archives built by CI. The graphics configurations below describe
the integration contract for custom dependency builds; they do not imply that
stock Mesa and libepoxy already support fully static rendering.

XLibre handles the following internally:

* `glx` and `glamoregl` use the built-in module registry and normal module setup.
* The GLX DRI2 provider and the glamor entry points used by modesetting resolve
  directly to linked symbols.
* GLX software rendering and DRI2 share a DRI driver registry. It calls linked
  driver factories, checks their extension names and versions, and keeps code
  resident when screens release their handles. Static GLX does not search
  `LIBGL_DRIVERS_PATH`, call `dlopen`, or pass built-in handles to `dlclose`.
* Graphics dependencies are requested with Meson's `static: true`, including
  private pkg-config dependencies. Configure checks that the requested DRI
  factories can actually be linked with `-static`.

### GLX with built-in DRI drivers

In addition to the common static build options, select the drivers and a
pkg-config package that supplies their archives:

```sh
PKG_CONFIG_PATH=/opt/static-graphics/lib/pkgconfig meson setup build-static-glx \
    --prefix=/usr -Dstatic=true -Dxorg=true -Dxnest=false \
    -Dglx=true -Dglx_dri=true -Dglamor=false -Dgbm=false \
    -Dstatic_dri_drivers=swrast \
    -Dstatic_dri_dependency=mesa-static-dri
```

`mesa-static-dri` is an example package name, not a package shipped by Mesa or
XLibre. A downstream build can provide any pkg-config package name. Its
`Libs`/`Libs.private` and `Requires.private` must supply the driver archives and
their complete dependencies, including any C++ runtime, threading, compression
or LLVM libraries the selected renderer needs. `gl.pc` must separately supply a
static OpenGL dispatch implementation.

Each driver must export the same per-driver factory used by the shared DRI
loader, with this C ABI:

```c
const __DRIextension **__driDriverGetExtensions_swrast(void);
```

The factory returns a NULL-terminated table of DRI extensions with process-long
lifetime. The software GLX provider requests `swrast`; Mesa may implement it
with softpipe or llvmpipe. Add hardware driver names, such as `iris`, to the
comma-separated list for DRI2. Hyphens in names become underscores in symbols,
so `example-drm` maps to `__driDriverGetExtensions_example_drm`. Names are matched
exactly when the server probes a driver. Registering an unavailable driver
fails configuration; probing an unregistered driver fails normally without
trying a shared library.

For example, an integration package for a downstream aggregate archive could
start with:

```pkgconfig
prefix=/opt/static-graphics
libdir=${prefix}/lib
includedir=${prefix}/include

Name: mesa-static-dri
Description: Statically linked Mesa DRI driver factories
Version: 1
Libs: -L${libdir} -lmesa_static_dri
Cflags: -I${includedir}
```

Add the archive's actual private dependencies to that file. The example archive
name is illustrative. XLibre references each factory explicitly, so merely
putting the factories in the supplied archives is sufficient; constructors or
dynamic symbol export tables are not required. Driver archives must avoid
colliding generic globals such as multiple `__driDriverExtensions` definitions.
The unique factories should return their respective extension tables instead.

### Glamor and its EGL GLX provider

With suitable static `epoxy.pc`, EGL/GL and GBM dependencies, enable:

```sh
PKG_CONFIG_PATH=/opt/static-graphics/lib/pkgconfig meson setup build-static-egl \
    --prefix=/usr -Dstatic=true -Dxorg=true -Dxnest=false \
    -Dglamor=true -Dgbm=true -Dglx=true -Dglx_dri=false
```

This uses glamor's existing EGL GLX provider, so no GLX DRI registry is needed.
Both paths can also be enabled together by supplying the DRI options above.
Glamor remains an explicit opt-in in a static build; `glamor=auto` leaves it
disabled. GLX without either built-in DRI drivers or glamor is rejected at
configuration time because it would have no rendering provider.

### Work required in the graphics dependencies

These are requirements for Mesa/libepoxy or a downstream integration, rather
than additional XLibre loader changes:

| Component | Required static behavior |
| --- | --- |
| Mesa DRI | Produce linkable archives exposing the selected per-driver factories and satisfying the DRI interfaces requested by GLX. |
| OpenGL dispatch | Supply the GL entry points and `glXGetProcAddressARB` used by GLX. Driver context setup and GL calls must use the same dispatch state; separate incompatible copies of libglapi will not work. |
| Mesa EGL | Link the selected platform/rendering backends and implement `eglGetProcAddress` for linked functions without loading vendor or driver shared libraries. |
| GBM | Link an appropriate backend and create/map the buffers required by modesetting without loading a backend `.so`. |
| libepoxy | Supply a static GL/EGL resolver that uses the linked implementations. Archiving its ordinary resolver, which opens GL/EGL libraries dynamically, is insufficient. Its pkg-config private dependencies must name the linked graphics implementations. |
| Dependency metadata | Describe all transitive static libraries, their required link order and a consistent target architecture/libc. |

Meson's `default_library=static` alone cannot implement those runtime changes.
Likewise, a static GLVND loader that still opens vendor `.so` files is insufficient.
The registry avoids XLibre's dynamic loading paths, but it cannot prevent an
unmodified dependency from trying its own loader. This matters especially for
musl static processes, where `dlopen` is unavailable. The same built-in paths
are used for glibc; shared driver loading is not used as a fallback there.

### Validation

CI exercises the static DRI loader with fixture factories on musl and glibc,
including lookup, extension/version rejection and handle release. The module
loader test additionally checks GLX registration and glamor symbol lookup when
those modules are enabled. These tests do not substitute for rendering tests
against a real static graphics dependency build.

After preparing that build, run:

```sh
meson compile -C build-static-glx
meson test -C build-static-glx --suite static
```

Also verify the final ELF files as below, then exercise GLX context creation
and rendering on Xvfb with the software DRI path (enable indirect GLX with
`+iglx` when testing an indirect client). For glamor, verify EGL context creation,
shader execution, framebuffer/texture import and an actual GLX rendering client
on the target KMS device. Repeat on each supported libc and hardware backend.
Successful linkage or the presence of the GLX extension alone is not evidence
that rendering works.

## Other drivers and runtime requirements

* Optional dependencies can be enabled when their complete static dependency
  chain is available.
* The modesetting driver is included when GBM and DRM are enabled. This needs a
  static libgbm **with a statically linked backend**. A libgbm archive whose
  backend still needs `dlopen` cannot provide KMS in a static musl process.
  Stock Mesa's dynamically loaded GBM backends do not meet this requirement.
  The example above disables GBM; its Xorg has no built-in video driver. Use
  Xfbdev for a framebuffer display, or provide a suitable static GBM build for
  Xorg modesetting. Hardware KMS operation is not exercised by this CI job.
* Xorg includes its enabled nullinput and inputtest drivers. External input and
  video `.so` drivers cannot be loaded. Adding another static driver requires
  linking its archive and adding its module metadata to the built-in registry
  (see the in-tree driver Meson files). Xfbdev has its own built-in Linux input
  drivers.
* Static linking does not bundle fonts, keyboard data, configuration files or
  the external `xkbcomp` executable. These remain runtime requirements.
* A glibc static executable can still use dynamic NSS modules according to the
  target's `/etc/nsswitch.conf`. Those modules need a matching glibc runtime;
  musl does not have that glibc-specific dependency.

To check linkage, `readelf -l build-static/hw/xfree86/Xorg` should show no
`INTERP` segment, and `readelf -d` should show no `NEEDED` entries. Xorg logs
`Loading built-in module ...` when it loads a statically linked module.
