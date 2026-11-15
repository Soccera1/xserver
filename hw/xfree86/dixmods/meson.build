xorg_modules += build_target(
    'wfb',
    'fbmodule.c',
    target_type: xorg_module_type,

    include_directories: [inc, xorg_inc],
    c_args: [ xorg_c_args, wfb_args ],
    dependencies: common_dep,
    link_whole: libxserver_wfb,
    link_with: xorg_module_server,

    install: not build_static,
    install_dir: module_abi_dir,
)

xorg_modules += build_target(
    'shadow',
    'shmodule.c',
    target_type: xorg_module_type,

    include_directories: [inc, xorg_inc],
    c_args: xorg_c_args,
    dependencies: common_dep,
    link_whole: libxserver_miext_shadow,
    link_with: xorg_module_server,

    install: not build_static,
    install_dir: module_abi_dir,
)

xorg_builtin_modules += [
    'BUILTIN_MODULE(wfb, "")',
    'BUILTIN_MODULE(shadow, "")',
]

if build_glx
    xorg_modules += build_target(
        'glx',
        [ 'glxmodule.c', srcs_glxdri2 ],
        target_type: xorg_module_type,

        include_directories: [ inc, xorg_inc ],
        c_args: [ xorg_c_args, glx_align64 ],
        dependencies: [ common_dep, dl_dep, dri_dep, static_dri_dep ],
        link_whole: libxserver_glx,
        link_with: xorg_module_server,

        install: not build_static,
        install_dir: join_paths(module_abi_dir, 'extensions')
    )
    xorg_builtin_modules += 'BUILTIN_MODULE(glx, "extensions")'
endif
