import os
from pathlib import Path
from sqlalchemy import create_engine,Table,MetaData
from werkzeug.security import generate_password_hash

MAINPATH = Path(os.path.dirname(os.path.abspath(__file__)))
clouddbfile = MAINPATH / 'work/clouddb.conf';

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

        # d = table1.delete().where(table1.c.email == 'emailgoeshere')
        # conncloud.execute(d)
        
        # clouddata = conncloud.execute(table1.select())
        # print(clouddata.all())
        email = "eduardo.batista@ufsc.br"
        newpass = generate_password_hash("testepass", method='sha256', )
        print(newpass)

        # clouddata = conncloud.execute(table1.select().where(table1.c.email==email))
        # usercloud = clouddata.first()
        # print(usercloud)

        stmt = table1.update().where(table1.c.email==email).values(password=newpass)
        print(stmt)
        rett = conncloud.execute(stmt)
        print(rett)
        conncloud.commit()

        # userscloud = [row['email'] for row in clouddata]
        # print(userscloud)
        # print(len(userscloud))

        # localdata = connlocal.execute("select * from user")

        # for row in localdata:
        #     # print(row)
        #     ndict = dict(zip(row.keys(),list(row)))
        #     del ndict['id']
        #     if row['email'] not in userscloud:
        #         conncloud.execute(table1.insert(), ndict)
        #         print(f'{row["email"]} included in cloud database.')

print('Finished...')
