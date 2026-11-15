xcb_dep = dependency('xcb', static: build_static, required: false)
xcb_sync_dep = dependency('xcb-sync', static: build_static, required: false)

if get_option('xvfb')
    if xcb_dep.found() and xcb_sync_dep.found()
        sync = executable('sync', 'sync.c', dependencies: [xcb_dep, xcb_sync_dep])
        test('sync', simple_xinit, args: [sync, '--', xvfb_server])
    endif
endif
