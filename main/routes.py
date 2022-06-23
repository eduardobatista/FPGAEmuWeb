from pathlib import Path
import shutil
from flask import session, redirect, url_for, render_template, request, current_app, send_from_directory, flash, abort
from werkzeug.utils import secure_filename
from zipfile import ZipFile
from . import main
from .funcs import *
from flask_login import login_required, current_user, AnonymousUserMixin
from .models import User
from appp import db

def getuserpath():
    if (current_user.viewAs is None) or (current_user.viewAs == ''):
        userpath = Path(current_app.WORKDIR,current_user.email)
    else:
        userpath = Path(current_app.WORKDIR,current_user.viewAs)
    if not userpath.exists():
        userpath.mkdir(parents=True)
    return userpath

def getcurrentproject(sessionpath):
    if "CurrentProject" not in session.keys():
        session["CurrentProject"] = ""    
    if session["CurrentProject"] != "":
        if not (sessionpath / session["CurrentProject"]).exists():
            session["CurrentProject"] = ""
    return session["CurrentProject"]    

@main.route('/')
def entrance():
    if current_user.is_authenticated:
        return redirect(url_for('main.sendfiles')) 
    else:
        return redirect(url_for('auth.login'))

@main.route('/files')
@login_required
def sendfiles():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))
    sessionpath = getuserpath() 
    cproj = getcurrentproject(sessionpath)        
    if cproj == "":
        aux = getdirlist(sessionpath)
        projectnames = [x.stem for x in aux]
        aux = getvhdfilelist(sessionpath) + list(sessionpath.glob("*.map"))
        if len(aux) > 0:
            oldfilespath = sessionpath / "_OldFiles"
            if not oldfilespath.exists():
                oldfilespath.mkdir()
                projectnames = ["_OldFiles"] + projectnames
            for ff in aux:
                fnameaux = (oldfilespath / ff.name)
                if fnameaux.exists():
                    if fnameaux.is_dir():
                        fnameaux.rmdir()
                    else:
                        fnameaux.unlink()
                if not ff.is_dir():
                    shutil.move(ff,oldfilespath)
                else:
                    ff.rmdir()
    else: 
        projectnames = []
        sessionpath = sessionpath / cproj
    aux = getvhdfilelist(sessionpath) #list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))  
    filenames = [x.stem for x in aux]
    if (current_user.topLevelEntity is None):
        if len(filenames) > 0:
            current_user.topLevelEntity = ((cproj + "/") if (cproj != "") else "") + filenames[0]
        else:    
            current_user.topLevelEntity = "usertop"
        db.session.commit()
    else:
        if not current_user.topLevelEntity.startswith(cproj):
            if len(filenames) > 0:
                current_user.topLevelEntity = ((cproj + "/") if (cproj != "") else "") + filenames[0]
            else: 
                current_user.topLevelEntity =  ((cproj + "/") if (cproj != "") else "") + "usertop"
            db.session.commit()    
    return render_template('files.html',username=current_user.email,toplevel=current_user.topLevelEntity,
                            filenames=filenames,projectnames=projectnames, currentproject=cproj,
                            socketiofile=getsocketiofile()) # current_app.send_static_file('main.html')        

@main.route("/openproject/<pname>") 
@login_required
def openproject(pname):
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))
    if pname == "":
        abort(404)
    sessionpath = getuserpath()
    pdir = sessionpath / pname
    if not isTraversalSecure(pdir, sessionpath):
        abort(404)
    if pdir.exists() and pdir.is_dir():
        session["CurrentProject"] = pname
        configfile = pdir / ".config"
        if configfile.exists():
            with open(configfile,"r") as cfile:
                aux = cfile.read()
                current_user.topLevelEntity = pname + "/" + aux
                db.session.commit()
    else:
        abort(404)
    return  redirect(url_for('main.sendfiles'))

@main.route("/closeproject") 
@login_required
def closeproject():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))
    projpath = (getuserpath() / session["CurrentProject"])
    cfgpath = projpath / ".config"
    with open(cfgpath,"w") as cfile:
        cfile.write(Path(current_user.topLevelEntity).name)
    session["CurrentProject"] = ""
    return  redirect(url_for('main.sendfiles'))

@main.route('/settoplevel',methods=['POST'])
@login_required
def settoplevel():
    sessionpath = getuserpath()
    toplevelfile = request.form.get('toplevelfile')
    if not isTraversalSecure(sessionpath / toplevelfile, sessionpath):
        abort(404)
    if current_user.topLevelEntity != toplevelfile:
        current_user.topLevelEntity = toplevelfile
        db.session.commit()        
        cfgpath =  (sessionpath / getcurrentproject(sessionpath)) / ".config"
        with open(cfgpath,"w") as cfile:
            cfile.write(Path(toplevelfile).name)
        fpgatestpath = Path(getuserpath(),'fpgatest')
        if fpgatestpath.exists():
            fpgatestpath.unlink()
    return toplevelfile

    
@main.route('/help')
@login_required
def hhelp():
    return render_template('help.html')

@main.route('/about')
@login_required
def aabout():
    return render_template('about.html')

@main.route('/emulation')
@login_required
def emular():
    userpath = getuserpath()
    return render_template('emulation.html',username=current_user.email,socketiofile=getsocketiofile())

@main.route('/simulation')
@login_required
def simular():
    sessionpath = getuserpath()
    cproj = getcurrentproject(sessionpath)
    if cproj != "":
        aux = getvhdfilelist(sessionpath / cproj,recursive=False)
    else:
        aux = getvhdfilelist(sessionpath,recursive=True)
    filenames = [str(x.relative_to(sessionpath)) for x in aux]
    tentity = f"{current_user.testEntity}.vhd"
    if tentity not in filenames:
        tentity = "usertest.vhd"
    return render_template('simulation.html',username=current_user.email,
                    socketiofile=getsocketiofile(),filenames=filenames,testentity=tentity)

@main.route('/editor')
@login_required
def editor():       
    sessionpath = getuserpath()
    aux = getdirlist(sessionpath)
    projectnames = [x.stem for x in aux] 
    curproject = getcurrentproject(sessionpath)
    if curproject == "":
        aux = getvhdfilelist(sessionpath,recursive=True)
    else:
        aux = getvhdfilelist(sessionpath / curproject)
    filenames = [x.relative_to(sessionpath) for x in aux]
    return render_template('editor.html',username=current_user.email,filenames=filenames,socketiofile=getsocketiofile(),
                            toplevel=current_user.topLevelEntity,projectnames=projectnames,currentproject=curproject)

@main.route('/mapper')
@login_required
def mapper():       
    sessionpath = getuserpath()
    curproject = getcurrentproject(sessionpath)
    if curproject == "":
        aux = getvhdfilelist(sessionpath,recursive=True)
    else:
        aux = getvhdfilelist(sessionpath / curproject)
    # aux = getvhdfilelist(sessionpath,recursive=True)  # list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    filenames = [x.relative_to(sessionpath) for x in aux]
    return render_template('mapper.html',username=current_user.email,filenames=filenames,socketiofile=getsocketiofile())

@main.route("/downloadproject/<pname>")
@login_required
def downloadproject(pname):
    temppath = Path(current_app.MAINPATH,'temp',current_user.email)
    if not temppath.exists():
        temppath.mkdir(parents=True,exist_ok=True)
    pzip = temppath / f'{pname}.zip'
    if not isTraversalSecure(pzip, temppath):
        return abort(404)
    if not pzip.exists():
        return abort(404)
    return send_from_directory(temppath, f'{pname}.zip', as_attachment=True, cache_timeout=-1)

@main.route("/downloadfile")
@login_required
def downloadfile():
    sessionpath = getuserpath()
    aux = getvhdfilelist(sessionpath,recursive=True)  # list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    # filenames = [x.name for x in aux]
    zipname = Path(sessionpath,'VHDLFiles.zip')
    if zipname.exists(): 
        zipname.unlink()
    zipobj = ZipFile(zipname, 'w')
    for f in aux:
        zipobj.write(f,f.relative_to(sessionpath))    
    zipobj.close()
    return send_from_directory(sessionpath, 'VHDLFiles.zip', as_attachment=True, cache_timeout=-1)

@main.route("/downloadafile", methods=['GET', 'POST']) 
@login_required
def downloadafile():
    fname = request.args.get('file')
    sessionpath = getuserpath()
    fpath = Path(sessionpath,fname)
    if not isTraversalSecure(fpath, sessionpath):
        abort(404)
    if not fpath.exists():
        abort(404)
    if fpath.is_dir():
        temppath = Path(current_app.MAINPATH,'temp',current_user.email)
        if not temppath.exists():
            temppath.mkdir(parents=True,exist_ok=True)
        zipname = Path(temppath,f'{fname}.zip')
        if zipname.exists(): 
            zipname.unlink()
        zipobj = ZipFile(zipname, 'w')
        aux = list(fpath.glob("*.vhd"))
        for f in aux:
            zipobj.write(f,f.relative_to(fpath))    
        zipobj.close()
        return send_from_directory(temppath, f'{fname}.zip', as_attachment=True, cache_timeout=-1)
    elif fpath.suffix == ".vhd":
        return send_from_directory(sessionpath, fname, as_attachment=True, cache_timeout=-1)
    else:
        abort(404)


@main.route("/downloadsimfile")
@login_required
def downloadsimfile():
    temppath = Path(current_app.MAINPATH,'temp',current_user.email)
    return send_from_directory(temppath, 'output.ghw', as_attachment=True, cache_timeout=-1)

@main.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if (current_user.viewAs != '') and (current_user.viewAs != current_user.email):
            # emit("error","Not allowed while viewing as a different user.")
            return "Fail! Not allowed while viewing as a different user."
        sessionpath = getuserpath()
        if not sessionpath.exists():
            sessionpath.mkdir(parents=True,exist_ok=True)
        f = request.files.getlist("fileToUpload")
        cproj = request.form.get('currentproject') 
        for ff in f:
            thefile = Path(sessionpath, cproj, secure_filename(ff.filename))            
            if thefile.exists():
                thefile.unlink()
            themap = Path(sessionpath, cproj, secure_filename(ff.filename)+".map")
            if themap.exists():
                themap.unlink()
            ff.save(thefile)
        return "Done!"
    else:
        return "Fail..."

@main.route('/compilar', methods=['GET', 'POST'])
@login_required
def compilar():
    if request.headers.get('accept') == 'text/event-stream':
        if proc is not None:
            proc = Popen("date", stdout=PIPE) 
        def events():
            rline = proc.stdout.readline()
            while rline != b'':
                yield "LINE="
                rline = proc.stdout.readline()
        return Response(events(), content_type='text/event-stream')
    return "Error: Event stream not accepted."

@main.route('/plottest') 
def plottest():
    return render_template('plottest.html',socketiofile=getsocketiofile(),currentproject=getcurrentproject(getuserpath()))
