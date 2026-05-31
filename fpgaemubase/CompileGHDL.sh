#!/bin/bash

docker build -t cmpghdl -f Dockerfile_CompileGHDL .

CONT_ID=$(docker create cmpghdl)

docker cp $CONT_ID:/home/builtghdl6.tar.gz ./builtghdl6.tar.gz

docker container rm $CONT_ID

docker image rm cmpghdl
