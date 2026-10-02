#!/usr/bin/env python3
import json, urllib.request, datetime, pathlib, sys

BASE='https://moneypuck.com/moneypuck/playerData/seasonSummary'
ROOT=pathlib.Path(__file__).resolve().parent
OUT=ROOT/'data'/'nhl_feed.json'
HEADERS={
    'User-Agent':'Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/140 Safari/537.36 NHL-Totals-Lab/0.1.2',
    'Referer':'https://moneypuck.com/data.htm',
    'Accept':'text/csv,*/*;q=0.8'
}

def season_start(today=None):
    today=today or datetime.datetime.now(datetime.timezone.utc).date()
    return today.year if today.month>=9 else today.year-1

def fetch(url):
    req=urllib.request.Request(url,headers=HEADERS)
    with urllib.request.urlopen(req,timeout=45) as r:
        if getattr(r,'status',200)!=200:
            raise RuntimeError(f'HTTP {r.status}: {url}')
        return r.read().decode('utf-8-sig')

def main():
    season=season_start(); prev=season-1
    files={}; errors={}
    for yr in (season,prev):
        for name in ('teams.csv','goalies.csv'):
            key=f'{yr}/{name}'; url=f'{BASE}/{yr}/regular/{name}'
            try:
                txt=fetch(url)
                if not txt.strip() or ',' not in txt.splitlines()[0]:
                    raise RuntimeError('respuesta no CSV')
                files[key]=txt
                print('OK',key,len(txt))
            except Exception as e:
                errors[key]=str(e)
                print('WARN',key,e,file=sys.stderr)
    # Previous season teams are mandatory so the app always has a stable prior.
    if f'{prev}/teams.csv' not in files:
        raise SystemExit('No se pudo obtener el prior MoneyPuck de equipos; no se sobrescribe el feed.')
    payload={
        'schema':1,
        'source':'MoneyPuck.com',
        'credit':'Data courtesy of MoneyPuck.com',
        'updatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'season':season,
        'previous':prev,
        'files':files,
        'errors':errors,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    tmp.replace(OUT)
    print('WROTE',OUT,OUT.stat().st_size)

if __name__=='__main__':
    main()
