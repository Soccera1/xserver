srcs_xorg_loader = [
    'loader.c',
    'loadmod.c',
]
if build_static
    srcs_xorg_loader += 'builtin.c'
endif

xorg_loader = static_library('xorg_loader',
    srcs_xorg_loader,
    include_directories: [inc, xorg_inc],
    dependencies: [common_dep, dl_dep],
    c_args: xorg_c_args,
)

if not build_static
    xorg_symbol_test = executable('xorg_symbol_test',
        'symbol-test.c',
        dependencies: dl_dep,
    )
endif
