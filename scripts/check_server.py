import requests

base='http://127.0.0.1:5000'
try:
    r=requests.get(base+'/api/settings/screenshot-storage', timeout=5)
    print('GET storage', r.status_code, r.text)
    r2=requests.post(base+'/api/settings/pairs', json={'name':'EURUSD'}, timeout=5)
    print('POST pair', r2.status_code, r2.text)
except Exception as e:
    print('ERR', e)
