from pathlib import Path
from flask import session, redirect, url_for, render_template, request, current_app, send_from_directory
from werkzeug.utils import secure_filename
from zipfile import ZipFile
from . import main
from .funcs import *

@main.route('/')
def sendfiles():   
    basepath = Path(current_app.MAINPATH,'work')
    if 'username' not in session:               
        session['username'] = createnewuser(basepath)
    basepath = Path(current_app.MAINPATH,'work')
    sessionpath = Path(basepath, session['username'])
    aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    filenames = [x.stem for x in aux]
    return render_template('sendfiles.html',username=session['username'],filenames=filenames) # current_app.send_static_file('main.html')

@main.route('/help')
def hhelp():
    return render_template('help.html')

@main.route('/about')
def aabout():
    return render_template('about.html')

@main.route('/emulation')
def emular():
    basepath = Path(current_app.MAINPATH,'work')
    if 'username' not in session:               
        session['username'] = createnewuser(basepath)
    return render_template('emulation.html',username=session['username'])

@main.route('/simulation')
def simular():
    basepath = Path(current_app.MAINPATH,'work')
    if 'username' not in session:               
        session['username'] = createnewuser(basepath)
    return render_template('simulation.html',username=session['username'])

@main.route('/editor')
def editor():    
    basepath = Path(current_app.MAINPATH,'work')
    if 'username' not in session:               
        session['username'] = createnewuser(basepath)    
    sessionpath = Path(basepath, session['username'])
    aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    filenames = [x.name for x in aux]
    return render_template('editor.html',username=session['username'],filenames=filenames)

@main.route("/downloadfile")
def downloadfile():
    basepath = Path(current_app.MAINPATH,'work')
    sessionpath = Path(basepath, session['username'])
    aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    filenames = [x.name for x in aux]
    zipname = Path(sessionpath,'VHDLFiles.zip')
    if zipname.exists(): 
        zipname.unlink()
    zipobj = ZipFile(zipname, 'w')
    for f in aux:
        zipobj.write(f,f.name)    
    zipobj.close()
    return send_from_directory(sessionpath, 'VHDLFiles.zip', as_attachment=True)

@main.route("/downloadsimfile")
def downloadsimfile():
    basepath = Path(current_app.MAINPATH,'work')
    sessionpath = Path(basepath, session['username'])
    # aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    # filenames = [x.name for x in aux]
    # zipname = Path(sessionpath,'VHDLFiles.zip')
    # if zipname.exists(): 
    #     zipname.unlink()
    # zipobj = ZipFile(zipname, 'w')
    # for f in aux:
    #     zipobj.write(f,f.name)    
    # zipobj.close()
    return send_from_directory(sessionpath, 'output.ghw', as_attachment=True)

@main.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        basepath = Path(current_app.MAINPATH,'work')
        sessionpath = Path(basepath, session['username'])
        if not sessionpath.exists():
            sessionpath.mkdir(parents=True,exist_ok=True)
        f = request.files.getlist("fileToUpload")
        for ff in f:
            ff.save(Path(sessionpath, secure_filename(ff.filename)))
        return "Done!"
    else:
        return "Fail..."

@main.route('/compilar', methods=['GET', 'POST'])
def compilar():
    if request.headers.get('accept') == 'text/event-stream':
        if proc is not None:
            print("Rodando!")
            proc = Popen("date", stdout=PIPE)        
        def events():
            rline = proc.stdout.readline()
            while rline != b'':
                yield "LINE="
                rline = proc.stdout.readline()
        return Response(events(), content_type='text/event-stream')
    return "Error: Event stream not accepted."
    # return "END!"
    #now = f.read()
    #return "Today is " + str(now)s