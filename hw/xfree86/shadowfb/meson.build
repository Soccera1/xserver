xorg_modules += build_target('shadowfb',
    [ 'shadowfb.c', 'sfbmodule.c'],
    target_type: xorg_module_type,
    include_directories: [ inc, xorg_inc ],
    dependencies: common_dep,
    c_args: xorg_c_args,
    install: not build_static,
    install_dir: module_abi_dir,
    link_with: xorg_module_server,
)
xorg_builtin_modules += 'BUILTIN_MODULE(shadowfb, "")'
