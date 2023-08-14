import os
from pathlib import Path
from sqlalchemy import create_engine,Table,MetaData

MAINPATH = Path(os.path.dirname(os.path.abspath(__file__)))
clouddbfile = (MAINPATH / 'work') / 'clouddb.conf';

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
        table1 = Table('user', metadata1, autoload_with=engcloud)

        tableloc = Table('user', MetaData(), autoload_with=englocal)

        # d = table1.delete().where(table1.c.email == 'emailgoeshere')
        # conncloud.execute(d)
        
        clouddata = conncloud.execute(table1.select()).mappings().all()
        userscloud = [row['email'] for row in clouddata]
        # print(userscloud)
        print(len(userscloud))

        localdata = connlocal.execute(tableloc.select())

        for row in localdata.mappings().all():
            print(row)
            if row['email'] in userscloud:
                print(f"{row['email']} already in cloud.")
            else:     
                ndict = dict(row)
                del ndict['id']           
                conncloud.execute(table1.insert().values(ndict))
                conncloud.commit()
                print(f'{row["email"]} included in cloud database.')

print('Finished...')
