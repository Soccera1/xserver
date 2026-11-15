xorg_modules += build_target('vgahw',
    [ 'vgaHW.c', 'vgaHWmodule.c'],
    target_type: xorg_module_type,
    include_directories: [ inc, xorg_inc ],
    dependencies: common_dep,
    c_args: xorg_c_args,
    install: not build_static,
    install_dir: module_abi_dir,
)
xorg_builtin_modules += 'BUILTIN_MODULE(vgahw, "")'
