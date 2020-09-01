#!/usr/bin/env bash

BASEDIR=$(dirname "$0")

echo "Compiling..."
cd $1
rm -fr *.o
rm -fr e~testbench.*
rm -fr work-obj*
rm -fr fpgatest

# echo "${@:2}"

ghdl -a -fexplicit --ieee=synopsys $BASEDIR/fpgaemu.vhd ${@:2}
#ghdl -a -fexplicit --ieee=synopsys /opt/fpgaemuweb/fpgaemu.vhd ${@:2} /opt/fpgaemuweb/fpgatest.vhd

#ghdl -e -fexplicit --ieee=synopsys -Wl,-lgtk-3 -Wl,-lgdk-3 -Wl,-latk-1.0 -Wl,-lgio-2.0 -Wl,-lpangocairo-1.0 -Wl,-lgdk_pixbuf-2.0 -Wl,-lcairo-gobject -Wl,-lpango-1.0 -Wl,-lcairo -Wl,-lgobject-2.0 -Wl,-lglib-2.0 -Wl,-lpthread -Wl,/opt/fpgaemu/lib/fpgaemu_c.o fpgatest
ghdl -e -fexplicit --ieee=synopsys -Wl,-pthread -Wl,$BASEDIR/fpgaemu_c.o fpgatest

echo "Compilation finished."