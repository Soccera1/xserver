glamoregl_src = [
    'glamor_xf86_egl.c',
    'glamor_eglmodule.c',
]
if build_xv
    glamoregl_src += 'glamor_xf86_xv.c'
endif

xorg_modules += build_target(
    'glamoregl',
    glamoregl_src,
    target_type: xorg_module_type,

    include_directories: [inc, xorg_inc],
    c_args: xorg_c_args,
    dependencies: [
        common_dep,
        libdrm_dep,
        gbm_dep,
    ],
    link_with: [glamor ],

    install: not build_static,
    install_dir: module_abi_dir,
)
xorg_builtin_modules += 'BUILTIN_MODULE(glamoregl, "")'
