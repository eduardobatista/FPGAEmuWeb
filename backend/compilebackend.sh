#!/usr/bin/env bash

BASEDIR=$(dirname "$0")
cd "$BASEDIR"

rm fpgacompileweb
if [[ $(ghdl --version | grep 'GHDL 3.') == *GHDL* ]]; then
    echo "GHDL 3.0.0 found."
    cp fpgacompileweb3.sh fpgacompileweb
    chmod 755 fpgacompileweb
elif [[ $(ghdl --version | grep 'GHDL 4.') == *GHDL* ]]; then
    echo "GHDL 4.0.0 found."
    cp fpgacompileweb3.sh fpgacompileweb
    chmod 755 fpgacompileweb
elif [[ $(ghdl --version | grep 'GHDL 5.') == *GHDL* ]]; then
    echo "GHDL 5 found."
    cp fpgacompileweb3.sh fpgacompileweb
    chmod 755 fpgacompileweb
else
    echo "GHDL version is not 3.0.0."
    cp fpgacompileweb1.sh fpgacompileweb
    chmod 755 fpgacompileweb
fi

rm fpgaemu_c.o

gcc -c -Wall -W -D_REENTRANT -lpthread fpgaemu.c -o fpgaemu_c.o
