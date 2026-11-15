srcs = [
    'ephyr.c',
    'ephyrinit.c',
    'ephyrcursor.c',
    'ephyr_draw.c',
    'hostx.c',
    '../../stubs/ddxBeforeReset.c',
]

xephyr_dep = [
    common_dep,
    dependency('xcb', static: build_static),
    dependency('xcb-shape', static: build_static),
    dependency('xcb-render', static: build_static),
    dependency('xcb-renderutil', static: build_static),
    dependency('xcb-aux', static: build_static),
    dependency('xcb-image', static: build_static),
    dependency('xcb-icccm', static: build_static),
    dependency('xcb-shm', static: build_static, version : '>=1.9.3'),
    dependency('xcb-keysyms', static: build_static),
    dependency('xcb-randr', static: build_static),
    dependency('xcb-xkb', static: build_static),
]

xephyr_glamor = []
if build_glamor
    srcs += 'ephyr_glamor.c'
    xephyr_glamor += glamor
    xephyr_dep += epoxy_dep
    xephyr_dep += dependency('xcb-glx', static: build_static)
endif

if build_xv
    srcs += 'ephyrvideo.c'
    xephyr_dep += dependency('xcb-xv', static: build_static)
endif

# mingw needs this for nanosleep()
if host_machine.system() == 'windows'
    xephyr_dep += cc.find_library('pthread', required : true, static: true)
endif

xephyr_server = executable(
    'Xephyr',
    srcs,
    include_directories: [
        inc,
        include_directories('../src')
    ],
    dependencies: xephyr_dep,
    link_with: [
        libxserver_main,
        libxserver_exa,
        xephyr_glamor,
        kdrive,
        libxserver_fb,
        libxserver,
        libxserver_config,
        libxserver_xkeyboard_stubs,
        libxserver_xi_stubs,
        libxserver_glx,
        libglxvnd,
    ],
    install: true,
)

xephyr_man = configure_file(
    input: 'man/Xephyr.man',
    output: 'Xephyr.1',
    configuration: manpage_config,
)
install_man(xephyr_man)
