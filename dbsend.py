import os
from pathlib import Path
from sqlalchemy import create_engine,Table,MetaData

MAINPATH = Path(os.path.dirname(os.path.abspath(__file__)))
clouddbfile = MAINPATH / 'clouddb.conf';

clouddbconf = None
if clouddbfile.exists():
    with open(clouddbfile,'r') as cfile:
        clouddbconf = cfile.read();

if clouddbconf is None:
    raise "Cloud DB configuration file not found."
else:
    engcloud = create_engine(clouddbconf)

englocal = create_engine('sqlite:///db.sqlite')

with engcloud.connect() as conncloud:
    with englocal.connect() as connlocal:
        # clouddata = conncloud.execute("select * from public.user")
        metadata1 = MetaData()        
        table1 = Table('user', metadata1, autoload=True, autoload_with=engcloud)

        # d = table1.delete().where(table1.c.email == 'teste@ufsc.br')
        # conncloud.execute(d)

        clouddata = conncloud.execute(table1.select())
        userscloud = [row['email'] for row in clouddata]

        localdata = connlocal.execute("select * from user")

        for row in localdata:
            ndict = dict(zip(row.keys(),list(row)))
            del ndict['id']
            if row['email'] not in userscloud:
                conncloud.execute(table1.insert(), ndict)
                print(f'{row["email"]} included in cloud database.')

print('Finished...')
