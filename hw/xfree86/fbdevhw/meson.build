if host_machine.system() == 'linux'
    srcs_fbdevhw = 'fbdevhw.c'
else
    srcs_fbdevhw = 'fbdevhwstub.c'
endif

xorg_modules += build_target('fbdevhw',
    srcs_fbdevhw,
    target_type: xorg_module_type,
    include_directories: [ inc, xorg_inc ],
    dependencies: common_dep,
    c_args: xorg_c_args,
    install: not build_static,
    install_dir: module_abi_dir,
    link_with: xorg_module_server,
)
xorg_builtin_modules += 'BUILTIN_MODULE(fbdevhw, "")'

install_man(configure_file(
    input: 'man/fbdevhw.man',
    output: 'fbdevhw.4',
    configuration: manpage_config,
))
