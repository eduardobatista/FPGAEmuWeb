#!/usr/bin/env bash

BASEDIR=$(dirname "$0")

#echo "Analyzing..."
cd $1

if [ -x "$(command -v ghwdump)" ]; then
    ghwdump -h $2
else 
    ~/gtkwave/bin/ghwdump -h $2
fi

#echo "Analysis finished."