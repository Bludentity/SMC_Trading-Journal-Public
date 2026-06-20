import sqlite3,os
DB='smc_backtest.db'
print('db path', os.path.abspath(DB),'exists', os.path.exists(DB))
con=sqlite3.connect(DB)
cur=con.cursor()
for tbl in ('entry_modules','reversal_levels'):
    try:
        cur.execute(f'select id, module_name from {tbl}' if tbl=='entry_modules' else f'select id, level_name from {tbl}')
        rows=cur.fetchall()
        print('\n',tbl, 'rows count', len(rows))
        for r in rows:
            print(r)
    except Exception as e:
        print('err reading',tbl, e)
con.close()
