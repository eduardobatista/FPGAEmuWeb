from pathlib import Path
from flask import session, redirect, url_for, render_template, request, current_app, send_from_directory, flash
from werkzeug.utils import secure_filename
from zipfile import ZipFile
from . import main
from .funcs import *
from flask_login import login_required, current_user, AnonymousUserMixin
from .models import User
from appp import db

def getuserpath():
    if (current_user.viewAs is None) or (current_user.viewAs == ''):
        userpath = Path(current_app.MAINPATH,'work',current_user.email)
    else:
        userpath = Path(current_app.MAINPATH,'work',current_user.viewAs)
    if not userpath.exists():
        userpath.mkdir(parents=True)
    return userpath
    

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
    aux = getvhdfilelist(sessionpath) #list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    filenames = [x.stem for x in aux]    
    if (current_user.topLevelEntity is None) or (current_user.topLevelEntity not in filenames):
        if len(filenames) == 1:
            current_user.topLevelEntity = filenames[0]
        else:    
            current_user.topLevelEntity = "usertop"
        db.session.commit()
    return render_template('sendfiles.html',username=current_user.email,toplevel=current_user.topLevelEntity,filenames=filenames,socketiofile=getsocketiofile()) # current_app.send_static_file('main.html')        

@main.route('/settoplevel',methods=['POST'])
@login_required
def settoplevel():
    toplevelfile = request.form.get('toplevelfile')
    if current_user.topLevelEntity != toplevelfile:
        current_user.topLevelEntity = toplevelfile        
        db.session.commit()
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
    aux = getvhdfilelist(sessionpath)
    filenames = [x.name for x in aux]
    tentity = f"{current_user.testEntity}.vhd"
    if tentity not in filenames:
        tentity = "usertest.vhd"
    return render_template('simulation.html',username=current_user.email,
                    socketiofile=getsocketiofile(),filenames=filenames,selectedfile=tentity)

@main.route('/editor')
@login_required
def editor():       
    sessionpath = getuserpath()
    aux = getvhdfilelist(sessionpath) # list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    filenames = [x.name for x in aux]
    return render_template('editor.html',username=current_user.email,filenames=filenames,socketiofile=getsocketiofile(),toplevel=current_user.topLevelEntity)

@main.route('/mapper')
@login_required
def mapper():       
    sessionpath = getuserpath()
    aux = getvhdfilelist(sessionpath)  # list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    filenames = [x.name for x in aux]
    return render_template('mapper.html',username=current_user.email,filenames=filenames,socketiofile=getsocketiofile())

@main.route("/downloadfile")
@login_required
def downloadfile():
    sessionpath = getuserpath()
    aux = getvhdfilelist(sessionpath)  # list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    # filenames = [x.name for x in aux]
    zipname = Path(sessionpath,'VHDLFiles.zip')
    if zipname.exists(): 
        zipname.unlink()
    zipobj = ZipFile(zipname, 'w')
    for f in aux:
        zipobj.write(f,f.name)    
    zipobj.close()
    return send_from_directory(sessionpath, 'VHDLFiles.zip', as_attachment=True)

@main.route("/downloadafile/<fname>") 
@login_required
def downloadafile(fname):
    if not fname.endswith("vhd"):
        abort(404)
    sessionpath = getuserpath()
    tfile = sessionpath / fname
    if not tfile.exists():
        abort(404)
    return send_from_directory(sessionpath, fname, as_attachment=True)


@main.route("/downloadsimfile")
@login_required
def downloadsimfile():
    sessionpath = getuserpath()
    return send_from_directory(sessionpath, 'output.ghw', as_attachment=True, cache_timeout=-1)

@main.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        sessionpath = getuserpath()
        if not sessionpath.exists():
            sessionpath.mkdir(parents=True,exist_ok=True)
        f = request.files.getlist("fileToUpload")
        for ff in f:
            thefile = Path(sessionpath, secure_filename(ff.filename))            
            if thefile.exists():
                thefile.unlink()
            themap = Path(sessionpath, secure_filename(ff.filename)+".map")
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
    return render_template('plottest.html',socketiofile=getsocketiofile())
