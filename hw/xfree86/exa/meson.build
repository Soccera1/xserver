xorg_exa = build_target('exa',
    'examodule.c',
    target_type: xorg_module_type,
    include_directories: [inc, xorg_inc],
    dependencies: common_dep,
    link_with: [libxserver_exa, xorg_module_server],
    c_args: xorg_c_args,
    install: not build_static,
    install_dir: module_abi_dir,
)
xorg_modules += xorg_exa
xorg_builtin_modules += 'BUILTIN_MODULE(exa, "")'

install_man(configure_file(
    input: 'man/exa.man',
    output: 'exa.4',
    configuration: manpage_config,
))
