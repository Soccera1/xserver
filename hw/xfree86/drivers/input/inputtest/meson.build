inputtestdrv_srcs = [
    'xf86-input-inputtest.c',
]

xorg_modules += build_target(
    'inputtest_drv',
    inputtestdrv_srcs,
    target_type: xorg_module_type,
    name_prefix: '',

    include_directories: [inc, xorg_inc],
    c_args: xorg_c_args,
    dependencies: [common_dep],

    install: not build_static,
    install_dir: join_paths(module_abi_dir, 'input'),

    link_with: xorg_module_server,
)
xorg_builtin_modules += 'BUILTIN_MODULE(inputtest, "input")'

install_man(configure_file(
    input: 'inputtestdrv.man',
    output: 'inputtestdrv.4',
    configuration: manpage_config,
))

install_data('xf86-input-inputtest-protocol.h', install_dir: xorgsdkdir)
