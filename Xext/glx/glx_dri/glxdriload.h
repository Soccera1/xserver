/* SPDX-License-Identifier: MIT */
#ifndef GLX_DRI_LOAD_H
#define GLX_DRI_LOAD_H

/* Resolve a driver's DRI extension table and check the required interfaces. */
void *glxProbeDriver(const char *name,
                     void **coreExt, const char *coreName, int coreVersion,
                     void **renderExt, const char *renderName, int renderVersion);

/* Release a shared driver, or leave a statically linked driver resident. */
void glxReleaseDriver(void *driver);

#endif
