/*  fpgaemu.c - Graphical interface for the FPGA board emulator.
    Copyright (C) 2020  Fabian L. Cabrera

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.

e-mail: fabian.c at ufsc.br

Modified by Eduardo L. O. Batista (eduardo.batista at ufsc.br)
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

#include <fcntl.h> 
#include <sys/stat.h> 
#include <sys/types.h> 
#include <unistd.h> 

int managereads();
void clear_input(char idx);
void set_input(char idx);
void switch_input(char idxx, char val);
void writeinmem(int idx, char mybyte);

int fifoout, fifoin;
char fifoarr[80];

int init_done=0;
char inmem[4] = {0x00, 0x00,0xF0,0x00};
char lastout[12] = {0x00, 0x00, 0x00, 0x7F, 0x7F, 0x7F, 0x7F, 0x7F, 0x7F, 0x7F, 0x7F, 0x00};
char outmem[12] = {0xFF, 0xFF, 0xFF, 0x00,0x00, 0x00, 0x00, 0x00,0x00, 0x00, 0x00, 0x00};

char ckmem[2] = {0};

//void *updatee(void *arg)
void *updatee()
{
   int change = 0;
   int forcedwrite = 0;
   int currentbyte, comparebyte,currentbit;
   int i,j;
   
   while (1) {

      ckmem[0] = ~ckmem[0];

      change = 0;

      for (i = 0; i < 11; ++i) {
         currentbyte = outmem[i];	// backup byte value
         currentbit = currentbyte;
         comparebyte = currentbyte ^ lastout[i];
         if (comparebyte != 0) {
            for (j = 0; j < 8; ++j) {
               if ((comparebyte & 1) == 1) {
                  change = 1;
               }
               comparebyte >>= 1;
               currentbit >>= 1;
            }
            lastout[i] = currentbyte;
         }
      }
      if ((change == 1) || (forcedwrite == 1)) {
         write(fifoout,outmem,11);  
         forcedwrite = 0;        
      }

      forcedwrite = managereads();
      
      usleep(1000);
   }
   
   return NULL;
}

int managereads() {
   int forcedwrite = 0, finished = 0;
   while (!finished) {
      read(fifoin,fifoarr,4);
      if (fifoarr[0] != 0) {
         if (fifoarr[0] == 'k') {
            if (fifoarr[2] == 'p') {
               clear_input(fifoarr[1]);
            } else if (fifoarr[2] == 'r') {
               set_input(fifoarr[1]);
            }            
         } else if (fifoarr[0] == 's') {
            switch_input(fifoarr[1],fifoarr[2]);
         } else if (fifoarr[0] == 'b') {
            writeinmem(fifoarr[1],fifoarr[2]);
         } else if (fifoarr[0] == 'f') {
            forcedwrite = 1;
         }
         fifoarr[0] = 0;
         if (fifoarr[3] == 0) { finished = 1; }
         else if (fifoarr[3] == 1) { forcedwrite = 1; finished = 1; }
         else if (fifoarr[3] == 2) { forcedwrite = 0; }
      } else { finished = 1; }
   }
   return forcedwrite;
}

void writeinmem(int idx, char mybyte) {
   inmem[idx] = mybyte;
}

void clear_input(char idx) {
   char mask = ~(1 << (((int) idx) + 4));
   inmem[2] = inmem[2] & mask; 
}

void set_input(char idx) {
   char mask = 1 << (((int) idx)+4);
   inmem[2] = inmem[2] | mask; 
}

void switch_input(char idxx, char val)
{
   int isw = (int) idxx;
   int idx = isw >> 3; //isw / 8; 
   int ipos = isw & 0x07; // % 8; 
   char mask = 1 << ipos;
   if (val == 0)
	   inmem[idx] = inmem[idx] & (~mask);
   else 
	   inmem[idx] = inmem[idx] | mask; 
}

static pthread_t thread_id; 
void init_gui()
{
   writeinmem(0,0x00);
   writeinmem(1,0x00);
   writeinmem(2,0xF0);
    // Criando FIFOs
   // char cwd[100];
   // if (getcwd(cwd, sizeof(cwd)) != NULL) {
   //     printf("Current working dir: %s\n", cwd);
   // }
   int pid = getpid();   
   char * myfifo = malloc(20);
   sprintf(myfifo,"myfifo%d",pid);
   char * myfifo2 = malloc(20);
   sprintf(myfifo2,"myfifo2%d",pid);
   // char * myfifo = "myfifo";
   // char * myfifo2 = "myfifo2"; 
   mkfifo(myfifo, 0666);
   fifoout = open(myfifo, O_WRONLY | O_CREAT);
   fifoarr[0] = 'o';
   fifoarr[1] = 'k';
   fifoarr[2] = '\n';
   write(fifoout,fifoarr,3);
   fifoarr[0] = '0';
   mkfifo(myfifo2,0666);
   fifoin = open(myfifo2, O_RDONLY | O_NONBLOCK);
   
   // pthread_create(&thread_id, NULL, main_gui, NULL); 
   pthread_create(&thread_id, NULL, updatee, NULL);
   init_done=1;
}

long int get_cmem(int w) {
   if (init_done == 0)
	   init_gui();
   if (init_done != 1)
	   return 0;

   switch(w) {
    	case 0 : return (long) inmem;
    	case 1 : return (long) outmem;
    	case 2 : return (long) ckmem;
   }
   return 0;
}