#!/bin/bash
set -ue

DEVAPPSERVER=$(which dev_appserver.py) \
  || (echo "ERROR: dev_appserver.py must be in your PATH"; exit 1)
while [ -L $DEVAPPSERVER ]
do
  DEVAPPSERVER=$(readlink $DEVAPPSERVER)
done

BIN_DIR=$(dirname $DEVAPPSERVER)

if [ "$(basename $BIN_DIR)" == "bin" ]
then
  SDK_HOME=$(dirname $BIN_DIR)
  if [ -d $SDK_HOME/platform/google_appengine ]
  then
    SDK_HOME=$SDK_HOME/platform/google_appengine
  fi
else
  SDK_HOME=$BIN_DIR
fi
PYTHONPATH=$SDK_HOME python scripts/run_tests.py
