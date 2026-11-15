/* SPDX-License-Identifier: MIT */
/* Fixture entry points used only by the static DRI loader unit test. */
BUILTIN_DRI_DRIVER("test", __driDriverGetExtensions_test)
BUILTIN_DRI_DRIVER("test-alias", __driDriverGetExtensions_test_alias)
BUILTIN_DRI_DRIVER("empty", __driDriverGetExtensions_empty)
BUILTIN_DRI_DRIVER("no-core", __driDriverGetExtensions_no_core)
BUILTIN_DRI_DRIVER("no-render", __driDriverGetExtensions_no_render)
