from pathlib import Path
from datetime import datetime
from zipfile import ZipFile


class ProjectExporter:

    def __init__(self,projname,toplevel):
        self.projname = projname
        self.toplevel = toplevel
        if "/" in self.toplevel:
            self.toplevel = self.toplevel.split("/")[1]
        self.filelist = []

    def addFiles(self,filelist):
        for ff in filelist:
            self.filelist.append(ff)
        
    def clearFileList(self):
        self.filelist = []

    def generateProject(self,projdir,outputdir):
        messages = []
        outputdir = Path(outputdir)
        datecreatedtext = datetime.now().strftime("%H:%M:%S  %B %-d, %Y")
        qpfdata = ProjectExporter.qpftemplate.replace("{{PROJNAME}}", f"{self.projname}")
        qpfdata = qpfdata.replace("{{DATECREATED}}", datecreatedtext)
        qpffile = outputdir / f"{self.projname}.qpf"
        if qpffile.exists():
            qpffile.unlink()
        qpffile.touch()
        with open(qpffile,"wt") as ff:
            ff.write(qpfdata)
        vhdfilestext = ""
        for ff in self.filelist:
            vhdfilestext += ProjectExporter.vhdlfilerowDE1SOC.replace("{{FILENAME}}", ff.name) + "\n"
        qsfdata = ProjectExporter.qsftemplateDE1SOC.replace("{{VHDLFILESINPROJECT}}",vhdfilestext)
        qsfdata = qsfdata.replace("{{DATECREATED}}", datecreatedtext)
        qsfdata = qsfdata.replace("{{TOPLEVELENTITY}}",self.toplevel)
        mapfile = projdir / (self.toplevel + ".vhd.map")
        if mapfile.exists():
            with open(mapfile,"r") as ff:
                aux = ff.readline()
                if len(aux) > 2:  # If first line has more than two bytes, map is active.
                    messages.append("<strong style='color:red;'>Mapper configuration is active:</strong>")
                    aux = ff.readline()
                    while aux:
                        vari,auxmapi = aux.strip().split(":")
                        mapi = auxmapi.split(",")
                        if mapi[0].startswith("CLK"):
                            return ["Error: exporting projects with mapped clock inputs not allowed yet."]
                        for k in range(1,len(mapi)):
                            mapi[k] = int(mapi[k])                        
                        if len(mapi) == 3:
                            messages.append( f"- <strong>{vari}</strong> to <strong>{mapi[0]}({mapi[1]} downto {mapi[2]})</strong>" )
                            for k in range(mapi[1]-mapi[2]+1):
                                qsfdata = qsfdata.replace(f"{mapi[0]}[{mapi[2]+k}]",f"{vari}[{k}]")
                        else:
                            messages.append( f"- <strong>{vari}</strong> to <strong>{mapi[0]}({mapi[1]})</strong>" )
                            qsfdata = qsfdata.replace(f"{mapi[0]}[{mapi[1]}]",f"{vari}")
                        aux = ff.readline()
        qsffile = outputdir / f"{self.projname}.qsf"
        if qsffile.exists():
            qsffile.unlink()
        qsffile.touch()
        with open(qsffile,"wt") as ff:
            ff.write(qsfdata)
        zipname = Path(outputdir,f'{self.projname}.zip')
        if zipname.exists(): 
            zipname.unlink()
        zipobj = ZipFile(zipname, 'w')
        zipobj.write(qpffile,qpffile.relative_to(outputdir))
        zipobj.write(qsffile,qsffile.relative_to(outputdir))
        for f in self.filelist:
            zipobj.write(f,f.relative_to(projdir))    
        zipobj.close()
        return messages


    qpftemplate = '''
QUARTUS_VERSION = "13.1"
DATE = "{{DATECREATED}}"

# Revisions

PROJECT_REVISION = "{{PROJNAME}}"
    '''

    vhdlfilerowDE1SOC = "set_global_assignment -name VHDL_FILE {{FILENAME}}"

    qsftemplateDE1SOC = '''
set_global_assignment -name FAMILY "Cyclone V"
set_global_assignment -name DEVICE 5CSEMA5F31C6
set_global_assignment -name TOP_LEVEL_ENTITY {{TOPLEVELENTITY}}
set_global_assignment -name ORIGINAL_QUARTUS_VERSION 13.1
set_global_assignment -name PROJECT_CREATION_TIME_DATE "{{DATECREATED}}"
set_global_assignment -name LAST_QUARTUS_VERSION 13.1
set_global_assignment -name PROJECT_OUTPUT_DIRECTORY output_files
set_global_assignment -name MIN_CORE_JUNCTION_TEMP 0
set_global_assignment -name MAX_CORE_JUNCTION_TEMP 85
set_global_assignment -name ERROR_CHECK_FREQUENCY_DIVISOR 256
set_global_assignment -name POWER_PRESET_COOLING_SOLUTION "23 MM HEAT SINK WITH 200 LFPM AIRFLOW"
set_global_assignment -name POWER_BOARD_THERMAL_MODEL "NONE (CONSERVATIVE)"
set_global_assignment -name PARTITION_NETLIST_TYPE SOURCE -section_id Top
set_global_assignment -name PARTITION_FITTER_PRESERVATION_LEVEL PLACEMENT_AND_ROUTING -section_id Top
set_global_assignment -name PARTITION_COLOR 16764057 -section_id Top
set_location_assignment PIN_AJ4 -to ADC_CS_N
set_location_assignment PIN_AK4 -to ADC_DIN
set_location_assignment PIN_AK3 -to ADC_DOUT
set_location_assignment PIN_AK2 -to ADC_SCLK
set_location_assignment PIN_K7 -to AUD_ADCDAT
set_location_assignment PIN_K8 -to AUD_ADCLRCK
set_location_assignment PIN_H7 -to AUD_BCLK
set_location_assignment PIN_J7 -to AUD_DACDAT
set_location_assignment PIN_H8 -to AUD_DACLRCK
set_location_assignment PIN_G7 -to AUD_XCK
set_location_assignment PIN_AA16 -to CLOCK2_50
set_location_assignment PIN_Y26 -to CLOCK3_50
set_location_assignment PIN_K14 -to CLOCK4_50
set_location_assignment PIN_AF14 -to CLOCK_50
set_location_assignment PIN_AK14 -to DRAM_ADDR[0]
set_location_assignment PIN_AH14 -to DRAM_ADDR[1]
set_location_assignment PIN_AG15 -to DRAM_ADDR[2]
set_location_assignment PIN_AE14 -to DRAM_ADDR[3]
set_location_assignment PIN_AB15 -to DRAM_ADDR[4]
set_location_assignment PIN_AC14 -to DRAM_ADDR[5]
set_location_assignment PIN_AD14 -to DRAM_ADDR[6]
set_location_assignment PIN_AF15 -to DRAM_ADDR[7]
set_location_assignment PIN_AH15 -to DRAM_ADDR[8]
set_location_assignment PIN_AG13 -to DRAM_ADDR[9]
set_location_assignment PIN_AG12 -to DRAM_ADDR[10]
set_location_assignment PIN_AH13 -to DRAM_ADDR[11]
set_location_assignment PIN_AJ14 -to DRAM_ADDR[12]
set_location_assignment PIN_AF13 -to DRAM_BA[0]
set_location_assignment PIN_AJ12 -to DRAM_BA[1]
set_location_assignment PIN_AF11 -to DRAM_CAS_N
set_location_assignment PIN_AK13 -to DRAM_CKE
set_location_assignment PIN_AH12 -to DRAM_CLK
set_location_assignment PIN_AG11 -to DRAM_CS_N
set_location_assignment PIN_AK6 -to DRAM_DQ[0]
set_location_assignment PIN_AJ7 -to DRAM_DQ[1]
set_location_assignment PIN_AK7 -to DRAM_DQ[2]
set_location_assignment PIN_AK8 -to DRAM_DQ[3]
set_location_assignment PIN_AK9 -to DRAM_DQ[4]
set_location_assignment PIN_AG10 -to DRAM_DQ[5]
set_location_assignment PIN_AK11 -to DRAM_DQ[6]
set_location_assignment PIN_AJ11 -to DRAM_DQ[7]
set_location_assignment PIN_AH10 -to DRAM_DQ[8]
set_location_assignment PIN_AJ10 -to DRAM_DQ[9]
set_location_assignment PIN_AJ9 -to DRAM_DQ[10]
set_location_assignment PIN_AH9 -to DRAM_DQ[11]
set_location_assignment PIN_AH8 -to DRAM_DQ[12]
set_location_assignment PIN_AH7 -to DRAM_DQ[13]
set_location_assignment PIN_AJ6 -to DRAM_DQ[14]
set_location_assignment PIN_AJ5 -to DRAM_DQ[15]
set_location_assignment PIN_AB13 -to DRAM_LDQM
set_location_assignment PIN_AE13 -to DRAM_RAS_N
set_location_assignment PIN_AK12 -to DRAM_UDQM
set_location_assignment PIN_AA13 -to DRAM_WE_N
set_location_assignment PIN_AA12 -to FAN_CTRL
set_location_assignment PIN_J12 -to FPGA_I2C_SCLK
set_location_assignment PIN_K12 -to FPGA_I2C_SDAT
set_location_assignment PIN_AC18 -to GPIO_0[0]
set_location_assignment PIN_AH18 -to GPIO_0[10]
set_location_assignment PIN_AH17 -to GPIO_0[11]
set_location_assignment PIN_AG16 -to GPIO_0[12]
set_location_assignment PIN_AE16 -to GPIO_0[13]
set_location_assignment PIN_AF16 -to GPIO_0[14]
set_location_assignment PIN_AG17 -to GPIO_0[15]
set_location_assignment PIN_AA18 -to GPIO_0[16]
set_location_assignment PIN_AA19 -to GPIO_0[17]
set_location_assignment PIN_AE17 -to GPIO_0[18]
set_location_assignment PIN_AC20 -to GPIO_0[19]
set_location_assignment PIN_Y17 -to GPIO_0[1]
set_location_assignment PIN_AH19 -to GPIO_0[20]
set_location_assignment PIN_AJ20 -to GPIO_0[21]
set_location_assignment PIN_AH20 -to GPIO_0[22]
set_location_assignment PIN_AK21 -to GPIO_0[23]
set_location_assignment PIN_AD19 -to GPIO_0[24]
set_location_assignment PIN_AD20 -to GPIO_0[25]
set_location_assignment PIN_AE18 -to GPIO_0[26]
set_location_assignment PIN_AE19 -to GPIO_0[27]
set_location_assignment PIN_AF20 -to GPIO_0[28]
set_location_assignment PIN_AF21 -to GPIO_0[29]
set_location_assignment PIN_AD17 -to GPIO_0[2]
set_location_assignment PIN_AF19 -to GPIO_0[30]
set_location_assignment PIN_AG21 -to GPIO_0[31]
set_location_assignment PIN_AF18 -to GPIO_0[32]
set_location_assignment PIN_AG20 -to GPIO_0[33]
set_location_assignment PIN_AG18 -to GPIO_0[34]
set_location_assignment PIN_AJ21 -to GPIO_0[35]
set_location_assignment PIN_Y18 -to GPIO_0[3]
set_location_assignment PIN_AK16 -to GPIO_0[4]
set_location_assignment PIN_AK18 -to GPIO_0[5]
set_location_assignment PIN_AK19 -to GPIO_0[6]
set_location_assignment PIN_AJ19 -to GPIO_0[7]
set_location_assignment PIN_AJ17 -to GPIO_0[8]
set_location_assignment PIN_AJ16 -to GPIO_0[9]
set_location_assignment PIN_AB17 -to GPIO_1[0]
set_location_assignment PIN_AG26 -to GPIO_1[10]
set_location_assignment PIN_AH24 -to GPIO_1[11]
set_location_assignment PIN_AH27 -to GPIO_1[12]
set_location_assignment PIN_AJ27 -to GPIO_1[13]
set_location_assignment PIN_AK29 -to GPIO_1[14]
set_location_assignment PIN_AK28 -to GPIO_1[15]
set_location_assignment PIN_AK27 -to GPIO_1[16]
set_location_assignment PIN_AJ26 -to GPIO_1[17]
set_location_assignment PIN_AK26 -to GPIO_1[18]
set_location_assignment PIN_AH25 -to GPIO_1[19]
set_location_assignment PIN_AA21 -to GPIO_1[1]
set_location_assignment PIN_AJ25 -to GPIO_1[20]
set_location_assignment PIN_AJ24 -to GPIO_1[21]
set_location_assignment PIN_AK24 -to GPIO_1[22]
set_location_assignment PIN_AG23 -to GPIO_1[23]
set_location_assignment PIN_AK23 -to GPIO_1[24]
set_location_assignment PIN_AH23 -to GPIO_1[25]
set_location_assignment PIN_AK22 -to GPIO_1[26]
set_location_assignment PIN_AJ22 -to GPIO_1[27]
set_location_assignment PIN_AH22 -to GPIO_1[28]
set_location_assignment PIN_AG22 -to GPIO_1[29]
set_location_assignment PIN_AB21 -to GPIO_1[2]
set_location_assignment PIN_AF24 -to GPIO_1[30]
set_location_assignment PIN_AF23 -to GPIO_1[31]
set_location_assignment PIN_AE22 -to GPIO_1[32]
set_location_assignment PIN_AD21 -to GPIO_1[33]
set_location_assignment PIN_AA20 -to GPIO_1[34]
set_location_assignment PIN_AC22 -to GPIO_1[35]
set_location_assignment PIN_AC23 -to GPIO_1[3]
set_location_assignment PIN_AD24 -to GPIO_1[4]
set_location_assignment PIN_AE23 -to GPIO_1[5]
set_location_assignment PIN_AE24 -to GPIO_1[6]
set_location_assignment PIN_AF25 -to GPIO_1[7]
set_location_assignment PIN_AF26 -to GPIO_1[8]
set_location_assignment PIN_AG25 -to GPIO_1[9]
set_location_assignment PIN_AE26 -to HEX0[0]
set_location_assignment PIN_AE27 -to HEX0[1]
set_location_assignment PIN_AE28 -to HEX0[2]
set_location_assignment PIN_AG27 -to HEX0[3]
set_location_assignment PIN_AF28 -to HEX0[4]
set_location_assignment PIN_AG28 -to HEX0[5]
set_location_assignment PIN_AH28 -to HEX0[6]
set_location_assignment PIN_AJ29 -to HEX1[0]
set_location_assignment PIN_AH29 -to HEX1[1]
set_location_assignment PIN_AH30 -to HEX1[2]
set_location_assignment PIN_AG30 -to HEX1[3]
set_location_assignment PIN_AF29 -to HEX1[4]
set_location_assignment PIN_AF30 -to HEX1[5]
set_location_assignment PIN_AD27 -to HEX1[6]
set_location_assignment PIN_AB23 -to HEX2[0]
set_location_assignment PIN_AE29 -to HEX2[1]
set_location_assignment PIN_AD29 -to HEX2[2]
set_location_assignment PIN_AC28 -to HEX2[3]
set_location_assignment PIN_AD30 -to HEX2[4]
set_location_assignment PIN_AC29 -to HEX2[5]
set_location_assignment PIN_AC30 -to HEX2[6]
set_location_assignment PIN_AD26 -to HEX3[0]
set_location_assignment PIN_AC27 -to HEX3[1]
set_location_assignment PIN_AD25 -to HEX3[2]
set_location_assignment PIN_AC25 -to HEX3[3]
set_location_assignment PIN_AB28 -to HEX3[4]
set_location_assignment PIN_AB25 -to HEX3[5]
set_location_assignment PIN_AB22 -to HEX3[6]
set_location_assignment PIN_AA24 -to HEX4[0]
set_location_assignment PIN_Y23 -to HEX4[1]
set_location_assignment PIN_Y24 -to HEX4[2]
set_location_assignment PIN_W22 -to HEX4[3]
set_location_assignment PIN_W24 -to HEX4[4]
set_location_assignment PIN_V23 -to HEX4[5]
set_location_assignment PIN_W25 -to HEX4[6]
set_location_assignment PIN_V25 -to HEX5[0]
set_location_assignment PIN_AA28 -to HEX5[1]
set_location_assignment PIN_Y27 -to HEX5[2]
set_location_assignment PIN_AB27 -to HEX5[3]
set_location_assignment PIN_AB26 -to HEX5[4]
set_location_assignment PIN_AA26 -to HEX5[5]
set_location_assignment PIN_AA25 -to HEX5[6]
set_location_assignment PIN_AA30 -to IRDA_RXD
set_location_assignment PIN_AB30 -to IRDA_TXD
set_location_assignment PIN_AA14 -to KEY[0]
set_location_assignment PIN_AA15 -to KEY[1]
set_location_assignment PIN_W15 -to KEY[2]
set_location_assignment PIN_Y16 -to KEY[3]
set_location_assignment PIN_V16 -to LEDR[0]
set_location_assignment PIN_W16 -to LEDR[1]
set_location_assignment PIN_V17 -to LEDR[2]
set_location_assignment PIN_V18 -to LEDR[3]
set_location_assignment PIN_W17 -to LEDR[4]
set_location_assignment PIN_W19 -to LEDR[5]
set_location_assignment PIN_Y19 -to LEDR[6]
set_location_assignment PIN_W20 -to LEDR[7]
set_location_assignment PIN_W21 -to LEDR[8]
set_location_assignment PIN_Y21 -to LEDR[9]
set_location_assignment PIN_AD7 -to PS2_CLK
set_location_assignment PIN_AD9 -to PS2_CLK2
set_location_assignment PIN_AE7 -to PS2_DAT
set_location_assignment PIN_AE9 -to PS2_DAT2
set_location_assignment PIN_AB12 -to SW[0]
set_location_assignment PIN_AC12 -to SW[1]
set_location_assignment PIN_AF9 -to SW[2]
set_location_assignment PIN_AF10 -to SW[3]
set_location_assignment PIN_AD11 -to SW[4]
set_location_assignment PIN_AD12 -to SW[5]
set_location_assignment PIN_AE11 -to SW[6]
set_location_assignment PIN_AC9 -to SW[7]
set_location_assignment PIN_AD10 -to SW[8]
set_location_assignment PIN_AE12 -to SW[9]
set_location_assignment PIN_H15 -to TD_CLK27
set_location_assignment PIN_D2 -to TD_DATA[0]
set_location_assignment PIN_B1 -to TD_DATA[1]
set_location_assignment PIN_E2 -to TD_DATA[2]
set_location_assignment PIN_B2 -to TD_DATA[3]
set_location_assignment PIN_D1 -to TD_DATA[4]
set_location_assignment PIN_E1 -to TD_DATA[5]
set_location_assignment PIN_C2 -to TD_DATA[6]
set_location_assignment PIN_B3 -to TD_DATA[7]
set_location_assignment PIN_A5 -to TD_HS
set_location_assignment PIN_F6 -to TD_RESET_N
set_location_assignment PIN_A3 -to TD_VS
set_location_assignment PIN_B13 -to VGA_B[0]
set_location_assignment PIN_G13 -to VGA_B[1]
set_location_assignment PIN_H13 -to VGA_B[2]
set_location_assignment PIN_F14 -to VGA_B[3]
set_location_assignment PIN_H14 -to VGA_B[4]
set_location_assignment PIN_F15 -to VGA_B[5]
set_location_assignment PIN_G15 -to VGA_B[6]
set_location_assignment PIN_J14 -to VGA_B[7]
set_location_assignment PIN_F10 -to VGA_BLANK_N
set_location_assignment PIN_A11 -to VGA_CLK
set_location_assignment PIN_J9 -to VGA_G[0]
set_location_assignment PIN_J10 -to VGA_G[1]
set_location_assignment PIN_H12 -to VGA_G[2]
set_location_assignment PIN_G10 -to VGA_G[3]
set_location_assignment PIN_G11 -to VGA_G[4]
set_location_assignment PIN_G12 -to VGA_G[5]
set_location_assignment PIN_F11 -to VGA_G[6]
set_location_assignment PIN_E11 -to VGA_G[7]
set_location_assignment PIN_B11 -to VGA_HS
set_location_assignment PIN_A13 -to VGA_R[0]
set_location_assignment PIN_C13 -to VGA_R[1]
set_location_assignment PIN_E13 -to VGA_R[2]
set_location_assignment PIN_B12 -to VGA_R[3]
set_location_assignment PIN_C12 -to VGA_R[4]
set_location_assignment PIN_D12 -to VGA_R[5]
set_location_assignment PIN_E12 -to VGA_R[6]
set_location_assignment PIN_F13 -to VGA_R[7]
set_location_assignment PIN_C10 -to VGA_SYNC_N
set_location_assignment PIN_D11 -to VGA_VS
set_global_assignment -name PARTITION_NETLIST_TYPE SOURCE -entity ghrd_top -section_id Top
set_global_assignment -name PARTITION_FITTER_PRESERVATION_LEVEL PLACEMENT_AND_ROUTING -entity ghrd_top -section_id Top
set_global_assignment -name PARTITION_COLOR 16764057 -entity ghrd_top -section_id Top
set_instance_assignment -name PARTITION_HIERARCHY root_partition -to | -entity ghrd_top -section_id Top
set_instance_assignment -name PARTITION_HIERARCHY root_partition -to | -section_id Top
{{VHDLFILESINPROJECT}}
    '''
