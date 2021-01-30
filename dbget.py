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
    raise BaseException("Cloud DB configuration file not found.")
else:
    engcloud = create_engine(clouddbconf)

englocal = create_engine('sqlite:///db.sqlite')

with engcloud.connect() as conncloud:
    with englocal.connect() as connlocal:
        metadata1 = MetaData()        
        table1 = Table('user', metadata1, autoload=True, autoload_with=engcloud)
        clouddata = conncloud.execute(table1.select())

        metadata2 = MetaData()
        table2 = Table('user', metadata2, autoload=True, autoload_with=englocal)
        localdata = connlocal.execute(table2.select())
        userslocal = [row['email'] for row in localdata]

        for row in clouddata:
            print(row['email'])
            if row['email'] not in userslocal:
                connlocal.execute(table2.insert(), row)
                print(f'{row["email"]} included in local database.')

print('Finished...')
