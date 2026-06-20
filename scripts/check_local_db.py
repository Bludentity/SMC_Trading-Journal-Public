import os,sqlite3
p=os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'SMC_Journal','smc_backtest.db')
print('path',p,'exists',os.path.exists(p))
if os.path.exists(p):
    con=sqlite3.connect(p)
    cur=con.cursor()
    try:
        cur.execute('select id,module_name from entry_modules order by id')
        print('modules',cur.fetchall())
    except Exception as e:
        print('modules err',e)
    try:
        cur.execute('select id,level_name from reversal_levels order by id')
        print('levels',cur.fetchall())
    except Exception as e:
        print('levels err',e)
    con.close()
