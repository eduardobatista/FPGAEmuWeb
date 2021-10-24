#!/usr/bin/env bash

BASEDIR=$(dirname "$1")

# echo "Simulating..."
cd $1
rm -fr *.o
rm -fr e~testbench.*
rm -fr work-obj*
rm -fr fpgatest
rm -fr output.ghw

# echo "$0"
# echo "$1"
# echo "$2"
# echo "${@:3}"

if [ -x "$(command -v ghdl)" ]; then
    ghdl -a -fexplicit --ieee=synopsys ${@:4}
    ghdl -e -fexplicit --ieee=synopsys $3
    ghdl -r $3 --wave=output.ghw --stop-time=$2
else 
    /opt/local/bin/ghdl -a -fexplicit --ieee=synopsys ${@:4}
    /opt/local/bin/ghdl -e -fexplicit --ieee=synopsys $3
    /opt/local/bin/ghdl -r $3 --wave=output.ghw --stop-time=$2
fi


# ghdl -a -fexplicit --ieee=synopsys $BASEDIR/fpgaemu.vhd ${@:2}
#ghdl -a -fexplicit --ieee=synopsys /opt/fpgaemuweb/fpgaemu.vhd ${@:2} /opt/fpgaemuweb/fpgatest.vhd

#ghdl -e -fexplicit --ieee=synopsys -Wl,-lgtk-3 -Wl,-lgdk-3 -Wl,-latk-1.0 -Wl,-lgio-2.0 -Wl,-lpangocairo-1.0 -Wl,-lgdk_pixbuf-2.0 -Wl,-lcairo-gobject -Wl,-lpango-1.0 -Wl,-lcairo -Wl,-lgobject-2.0 -Wl,-lglib-2.0 -Wl,-lpthread -Wl,/opt/fpgaemu/lib/fpgaemu_c.o fpgatest
# ghdl -e -fexplicit --ieee=synopsys -Wl,-pthread -Wl,$BASEDIR/fpgaemu_c.o fpgatest

echo "Simulation finished."