ARG BASE=corpusops/ubuntu-bare:focal
FROM $BASE as dependencies
ENV PYTHONUNBUFFERED 1
ENV DEBIAN_FRONTEND=noninteractive
ARG TZ=Europe/Paris
ARG APP_TYPE=app
ARG PY_VER=3.8
ENV APP_TYPE="$APP_TYPE" \
    PY_VER="$PY_VER"
# See https://github.com/nodejs/docker-node/issues/380
ARG GPG_KEYS=B42F6819007F00F88E364FD4036A9C25BF357DD4
ARG GPG_KEYS_SERVERS="hkp://p80.pool.sks-keyservers.net:80 hkp://ipv4.pool.sks-keyservers.net hkp://pgp.mit.edu:80"

WORKDIR /code
ADD --chown=1000:1000 apt.txt /code/apt.txt

# setup project timezone, dependencies, user & workdir, gosu
RUN bash -c 'set -ex \
    && date && : "set correct timezone" \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && : "install packages" \
    && sed -i -re "s/(python-?)[0-9]\.[0-9]+/\1$PY_VER/g" /code/apt.txt \
    && apt-get update -qq \
    && apt-get install -qq -y $(grep -vE "^\s*#" /code/apt.txt|tr "\n" " ") \
    && apt-get clean all && apt-get autoclean \
    && : "project user & workdir" \
    && if ! ( getent passwd app &>/dev/null );then useradd -ms /bin/bash app --uid 1000;fi && date'

FROM dependencies as pydependencies
# See https://github.com/nodejs/docker-node/issues/380
ARG PIP_SRC=/code/pipsrc
ENV PIP_SRC=$PIP_SRC
ARG BUILD_DEV=
ARG VSCODE_VERSION=
ARG PYCHARM_VERSION=
ENV VSCODE_VERSION=$VSCODE_VERSION
ENV PYCHARM_VERSION=$PYCHARM_VERSION
ARG WITH_VSCODE=0
ENV WITH_VSCODE=$WITH_VSCODE
ARG WITH_PYCHARM=0
ENV WITH_PYCHARM=$WITH_PYCHARM
ARG CFLAGS=
ARG CPPLAGS=
ARG C_INCLUDE_PATH=/usr/include/gdal/
ARG CPLUS_INCLUDE_PATH=/usr/include/gdal/
ARG LDFLAGS=
ARG LANG=fr_FR.utf8
ENV VSCODE_VERSION="$VSCODE_VERSION" \
    PYCHARM_VERSION="$PYCHARM_VERSION" \
    WITH_VSCODE="$WITH_VSCODE" \
    CFLAGS="$CFLAGS" \
    CPPLAGS="$CPPFLAGS" \
    C_INCLUDE_PATH="$C_INCLUDE_PATH" \
    CPLUS_INCLUDE_PATH="$CPLUS_INCLUDE_PATH" \
    LDFLAGS="$LDFLAGS" \
    WITH_PYCHARM="$WITH_PYCHARM" \
    LC_ALL="$LANG" \
    LANG="$LANG"
ARG FORCE_PIP="0"
ARG FORCE_PIPENV="0"
ARG MINIMUM_SETUPTOOLS_VERSION="50.3.2"
ARG MINIMUM_PIP_VERSION="20.2.4"
ARG MINIMUM_WHEEL_VERSION="0.35.1"
ARG MINIMUM_PIPENV_VERSION="2020.11.15"
ARG SETUPTOOLS_REQ="setuptools>=${MINIMUM_SETUPTOOLS_VERSION}"
ARG PIP_REQ="pip==${MINIMUM_PIP_VERSION}"
ARG PIPENV_REQ="pipenv>=${MINIMUM_PIP_VERSION}"
ARG WHEEL_REQ="wheel>=${MINIMUM_WHEEL_VERSION}"
# warning: requirements adds are done via the *txt glob
ADD --chown=app:app setup.* *.ini *.rst *.md *.txt README* requirements* /code/
# only bring minimal py for now as we get only deps (CI optims)
ADD --chown=app:app src /code/src/

RUN bash -exc ': \
    && date && find /code -not -user app \
    | while read f;do chown app:app "$f";done \
    && gosu app:app bash -exc "if [ ! -e venv ];then python${PY_VER} -m venv venv;fi \
    && if [ ! -e requirements ];then mkdir requirements;fi \
    && devreqs=requirements-dev.txt && reqs=requirements.txt \
    && : handle retrocompat with both old and new layouts /requirements.txt and /requirements/requirements.txt \
    && find -maxdepth 1 -iname \"requirement*txt\" -or -name \"Pip*\" | sed -re \"s|./||\" \
    | while read r;do mv -vf \${r} requirements && ln -fsv requirements/\${r};done \
    && venv/bin/pip install -U --no-cache-dir \"\${SETUPTOOLS_REQ}\" \"\${WHEEL_REQ}\" \"\${PIPENV_REQ}\" \"\${PIP_REQ}\" \
    && set +x && . venv/bin/activate && set -x\
    && if [ -e Pipfile ] || [ \"x${FORCE_PIPENV}\" = \"x1\" ];then \
        pipenv_args=\"\" \
        && if [[ -n \"$BUILD_DEV\" ]];then pipenv_args=\"--dev\";fi \
        && venv/bin/pipenv install \${pipenv_args}; \
    elif [ -e \${reqs} ] || [ \"x${FORCE_PIP}\" = \"x1\" ];then \
       venv/bin/pip install -U --no-cache-dir -r \${reqs} \
       && if [[ -n \"$BUILD_DEV\" ]] && [ -e \${devreqs} ];then \
           venv/bin/pip install -U --no-cache-dir -r \${reqs} -r \${devreqs}; \
       fi; \
    fi \
    && if [ \"x$WITH_VSCODE\" = \"x1\" ];then  venv/bin/python -m pip install -U \"ptvsd${VSCODE_VERSION}\";fi \
    && if [ \"x$WITH_PYCHARM\" = \"x1\" ];then venv/bin/python -m pip install -U \"pydevd-pycharm${PYCHARM_VERSION}\";fi \
    && if [ -e setup.py ];then venv/bin/python -m pip install --no-deps -e .;fi \
    && date \
    "'

FROM pydependencies as appsetup

# Final cleanup, only work if using the docker build --squash option
ARG DEV_DEPENDENCIES_PATTERN='^#\s*dev dependencies'
RUN \
  set -ex \
  && sed -i -re "s/(python-?)[0-9]\.[0-9]+/\1$PY_VER/g" /code/apt.txt \
  && if $(egrep -q "${DEV_DEPENDENCIES_PATTERN}" /code/apt.txt);then \
    apt-get remove --auto-remove --purge \
      $(sed "1,/${DEV_DEPENDENCIES_PATTERN}/ d" /code/apt.txt|grep -v '^#'|tr "\n" " ");\
  fi \
  && rm -rf /var/lib/apt/lists/*

# if we found a static dist inside the sys directory, it has been injected during
# the CI process, we just unpack it
RUN bash -exc ': \
    && cd /code && for i in init;do if [ ! -e $i ];then mkdir -p $i;fi;done \
    && if [ -e sys/statics ];then\
     while read f;do tar xJvf ${f};done \
      < <(find sys/statics -name "*.txz" -or -name "*.xz"); \
     while read f;do tar xjvf ${f};done \
      < <(find sys/statics -name "*.tbz2" -or -name "*.bz2"); \
     while read f;do tar xzvf ${f};done \
      < <(find sys/statics -name "*.tgz" -or -name "*.gz"); \
     fi && rm -rfv sys/statics \
    && find /code -not -user app \
    | while read f;do chown app:app "$f";done'

WORKDIR /code/src
ADD --chown=app:app .git                         /code/.git
COPY ./rootfs/ /
ENTRYPOINT ["/docker-entrypoint.sh"]
# image will drop privileges itself using gosu at the end of the entrypoint
