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
        # Defining location assigments (TODO: to be improved)
        locaassig = []
        for pair in ProjectExporter.locassigtableDE1SOC:
            aux = ProjectExporter.locationassignmenttemplate.replace("{{PIN}}", pair[0])
            aux = aux.replace("{{PORT}}", pair[1])
            locaassig.append(aux)
        qsfdata = qsfdata.replace("{{LOCATIONASSIGNMENTS}}","\n".join(locaassig))
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

    locationassignmenttemplate = "set_location_assignment {{PIN}} -to {{PORT}}"

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
{{LOCATIONASSIGNMENTS}}
set_global_assignment -name PARTITION_NETLIST_TYPE SOURCE -entity ghrd_top -section_id Top
set_global_assignment -name PARTITION_FITTER_PRESERVATION_LEVEL PLACEMENT_AND_ROUTING -entity ghrd_top -section_id Top
set_global_assignment -name PARTITION_COLOR 16764057 -entity ghrd_top -section_id Top
set_instance_assignment -name PARTITION_HIERARCHY root_partition -to | -entity ghrd_top -section_id Top
set_instance_assignment -name PARTITION_HIERARCHY root_partition -to | -section_id Top
{{VHDLFILESINPROJECT}}
    '''

    locassigtableDE1SOC = [ ("PIN_AA16", "CLOCK2_50"),
                            ("PIN_Y26", "CLOCK3_50"),
                            ("PIN_K14", "CLOCK4_50"),
                            ("PIN_AF14", "CLOCK_50"),     
                            ("PIN_AE26", "HEX0[0]"),
                            ("PIN_AE27", "HEX0[1]"),
                            ("PIN_AE28", "HEX0[2]"),
                            ("PIN_AG27", "HEX0[3]"),
                            ("PIN_AF28", "HEX0[4]"),
                            ("PIN_AG28", "HEX0[5]"),
                            ("PIN_AH28", "HEX0[6]"),
                            ("PIN_AJ29", "HEX1[0]"),
                            ("PIN_AH29", "HEX1[1]"),
                            ("PIN_AH30", "HEX1[2]"),
                            ("PIN_AG30", "HEX1[3]"),
                            ("PIN_AF29", "HEX1[4]"),
                            ("PIN_AF30", "HEX1[5]"),
                            ("PIN_AD27", "HEX1[6]"),
                            ("PIN_AB23", "HEX2[0]"),
                            ("PIN_AE29", "HEX2[1]"),
                            ("PIN_AD29", "HEX2[2]"),
                            ("PIN_AC28", "HEX2[3]"),
                            ("PIN_AD30", "HEX2[4]"),
                            ("PIN_AC29", "HEX2[5]"),
                            ("PIN_AC30", "HEX2[6]"),
                            ("PIN_AD26", "HEX3[0]"),
                            ("PIN_AC27", "HEX3[1]"),
                            ("PIN_AD25", "HEX3[2]"),
                            ("PIN_AC25", "HEX3[3]"),
                            ("PIN_AB28", "HEX3[4]"),
                            ("PIN_AB25", "HEX3[5]"),
                            ("PIN_AB22", "HEX3[6]"),
                            ("PIN_AA24", "HEX4[0]"),
                            ("PIN_Y23", "HEX4[1]"),
                            ("PIN_Y24", "HEX4[2]"),
                            ("PIN_W22", "HEX4[3]"),
                            ("PIN_W24", "HEX4[4]"),
                            ("PIN_V23", "HEX4[5]"),
                            ("PIN_W25", "HEX4[6]"),
                            ("PIN_V25", "HEX5[0]"),
                            ("PIN_AA28", "HEX5[1]"),
                            ("PIN_Y27", "HEX5[2]"),
                            ("PIN_AB27", "HEX5[3]"),
                            ("PIN_AB26", "HEX5[4]"),
                            ("PIN_AA26", "HEX5[5]"),
                            ("PIN_AA25", "HEX5[6]"),
                            ("PIN_AA30", "IRDA_RXD"),
                            ("PIN_AB30", "IRDA_TXD"),
                            ("PIN_AA14", "KEY[0]"),
                            ("PIN_AA15", "KEY[1]"),
                            ("PIN_W15", "KEY[2]"),
                            ("PIN_Y16", "KEY[3]"),
                            ("PIN_V16", "LEDR[0]"),
                            ("PIN_W16", "LEDR[1]"),
                            ("PIN_V17", "LEDR[2]"),
                            ("PIN_V18", "LEDR[3]"),
                            ("PIN_W17", "LEDR[4]"),
                            ("PIN_W19", "LEDR[5]"),
                            ("PIN_Y19", "LEDR[6]"),
                            ("PIN_W20", "LEDR[7]"),
                            ("PIN_W21", "LEDR[8]"),
                            ("PIN_Y21", "LEDR[9]"),
                            ("PIN_AD7", "PS2_CLK"),
                            ("PIN_AD9", "PS2_CLK2"),
                            ("PIN_AE7", "PS2_DAT"),
                            ("PIN_AE9", "PS2_DAT2"),
                            ("PIN_AB12", "SW[0]"),
                            ("PIN_AC12", "SW[1]"),
                            ("PIN_AF9", "SW[2]"),
                            ("PIN_AF10", "SW[3]"),
                            ("PIN_AD11", "SW[4]"),
                            ("PIN_AD12", "SW[5]"),
                            ("PIN_AE11", "SW[6]"),
                            ("PIN_AC9", "SW[7]"),
                            ("PIN_AD10", "SW[8]"),
                            ("PIN_AE12", "SW[9]")]
