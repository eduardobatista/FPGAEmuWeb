#!/usr/bin/env bash

BASEDIR=$(dirname "$0")
cd "$BASEDIR"

rm fpgacompileweb
cp fpgacompileweb.sh fpgacompileweb
chmod 755 fpgacompileweb

rm fpgaemu_c.o

gcc -c -Wall -W -D_REENTRANT -lpthread fpgaemu.c -o fpgaemu_c.o

# mkdir /opt/fpgaemuweb
# mkdir /opt/fpgaemuweb/lib
# mkdir /opt/fpgaemuweb/examples
# mkdir /opt/fpgaemuweb/examples/io
# mkdir /opt/fpgaemuweb/examples/register
# mkdir /opt/fpgaemuweb/examples/counter
# # cp -fr all_leds.bmp /opt/fpgaemu/
# cp -fr fpgaemu.c /opt/fpgaemuweb/
# cp -fr fpgaemu.vhd /opt/fpgaemuweb/
# cp -fr COPYING /opt/fpgaemuweb/
# cp -fr fpgatest.vhd /opt/fpgaemuweb/
# cp -fr usertop_1.vhd /opt/fpgaemuweb/examples/io/usertop.vhd
# cp -fr usertop_2.vhd /opt/fpgaemuweb/examples/register/usertop.vhd
# cp -fr usertop_3.vhd /opt/fpgaemuweb/examples/counter/usertop.vhd
# cp -fr fpgacompileweb.sh /usr/local/bin/fpgacompileweb
# chmod -R 755 /opt/fpgaemuweb
# chmod 777 /usr/local/bin/fpgacompileweb

# rm /opt/fpgaemuweb/lib/fpgaemu_c.o

# #gcc -c -Wall -W -D_REENTRANT -lpthread -I/usr/include/gtk-3.0 -I/usr/include/atk-1.0 -I/usr/include/at-spi2-atk/2.0 -I/usr/include/pango-1.0 -I/usr/include/gio-unix-2.0/ -I/usr/include/cairo -I/usr/include/gdk-pixbuf-2.0 -I/usr/include/glib-2.0 -I/usr/include/glib-2.0 -I/usr/lib/arm-linux-gnueabihf/glib-2.0/include -I/usr/include/at-spi-2.0 -I/usr/include/dbus-1.0 -I/usr/include/dbus-1.0/dbus -I/usr/include/libdrm -I/usr/include/harfbuzz -I/usr/include/freetype2 -I/usr/include/fribidi -I/usr/include/libpng15 -I/usr/include/uuid -I/usr/include/pixman-1  -lgtk-3 -lgdk-3 -latk-1.0 -lgio-2.0 -lpangocairo-1.0 -lgdk_pixbuf-2.0 -lcairo-gobject -lpango-1.0 -lcairo -lgobject-2.0 -lglib-2.0 /opt/fpgaemu/fpgaemu.c -o /opt/fpgaemu/lib/fpgaemu_c.o
# gcc -c -Wall -W -D_REENTRANT -lpthread /opt/fpgaemuweb/fpgaemu.c -o /opt/fpgaemuweb/lib/fpgaemu_c.o



