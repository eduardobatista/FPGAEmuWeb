#!/usr/bin/env bash

BASEDIR=$(dirname "$0")

echo "Analyzing..."
cd $1

if [ -x "$(command -v ghdl)" ]; then
    ghdl -a -fexplicit --ieee=synopsys $2
else 
    /opt/local/bin/ghdl -a -fexplicit --ieee=synopsys $2
fi

echo "Analysis finished."