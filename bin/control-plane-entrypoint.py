#!/usr/bin/env python3
import os
import sys

DATA_DIR = "/data"
APP_UID = 10001
APP_GID = 10001

if os.geteuid() == 0:
    os.chown(DATA_DIR, APP_UID, APP_GID)
    os.setgid(APP_GID)
    os.setuid(APP_UID)

os.execvpe(sys.argv[1], sys.argv[1:], os.environ)
