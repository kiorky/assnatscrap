#!/usr/bin/env bash
if [[ -n "${SDEBUG}" ]];then set -x;fi
APP_GID=${APP_GID-1000}
APP_UID=${APP_UID-1000}
usermod -g $APP_GID -u $APP_UID app
chown -R $APP_UID:$APP_GID /data
. /code/venv/bin/activate
if [[ -n "$@" ]];then
    exec gosu app bash -ec "$@"
else
    exec gosu app bash
fi
# vim:set et sts=4 ts=4 tw=80:
