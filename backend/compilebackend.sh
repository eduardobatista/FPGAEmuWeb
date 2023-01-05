#!/usr/bin/env bash

BASEDIR=$(dirname "$0")
cd "$BASEDIR"

rm fpgacompileweb
cp fpgacompileweb.sh fpgacompileweb
chmod 755 fpgacompileweb

rm fpgaemu_c.o

gcc -c -Wall -W -D_REENTRANT -lpthread fpgaemu.c -o fpgaemu_c.o
