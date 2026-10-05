#!/usr/bin/env python3
import csv, io, json, urllib.parse, urllib.request, datetime, pathlib, sys, os

MP_BASE='https://moneypuck.com/moneypuck/playerData/seasonSummary'
MP_GAMES='https://moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv'
NHL_STATS='https://api.nhle.com/stats/rest/en'
ROOT=pathlib.Path(__file__).resolve().parent
OUT=ROOT/'data'/'nhl_feed.json'
HEADERS={
    'User-Agent':'Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/140 Safari/537.36 NHL-Totals-Lab/0.2.0',
    'Referer':'https://moneypuck.com/data.htm',
    'Accept':'text/csv,application/json,*/*;q=0.8'
}
TEAM_REMAP={'L.A':'LAK','N.J':'NJD','S.J':'SJS','T.B':'TBL','ARI':'UTA','PHX':'UTA'}

def season_start(today=None):
    today=today or datetime.datetime.now(datetime.timezone.utc).date()
    return today.year if today.month>=9 else today.year-1

def fetch_bytes(url, timeout=60):
    req=urllib.request.Request(url,headers=HEADERS)
    with urllib.request.urlopen(req,timeout=timeout) as r:
        if getattr(r,'status',200)!=200:
            raise RuntimeError(f'HTTP {r.status}: {url}')
        return r.read()

def fetch_text(url, timeout=60):
    return fetch_bytes(url,timeout).decode('utf-8-sig')

def fetch_json(url, timeout=45):
    return json.loads(fetch_bytes(url,timeout).decode('utf-8'))

def first(row,*keys):
    for k in keys:
        v=row.get(k)
        if v not in (None,''):
            return v
    return None

def fnum(v):
    try: return float(v)
    except Exception: return None

def pct(v):
    x=fnum(v)
    if x is None: return None
    return x*100 if x<=1.5 else x

def normalize_code(x):
    x=str(x or '').strip().upper()
    return TEAM_REMAP.get(x,x)

def nhl_team_map():
    try:
        rows=fetch_json(f'{NHL_STATS}/team?limit=-1').get('data',[])
    except Exception:
        return {},{}
    by_id={}; by_name={}
    for r in rows:
        code=normalize_code(first(r,'triCode','rawTricode','teamAbbrev','teamAbbrevs'))
        if not code: continue
        if r.get('id') is not None: by_id[str(r['id'])]=code
        nm=str(first(r,'fullName','teamFullName','name') or '').strip().lower()
        if nm: by_name[nm]=code
    return by_id,by_name

def row_code(r,by_id,by_name):
    code=normalize_code(first(r,'teamAbbrev','teamAbbrevs','triCode','rawTricode'))
    if len(code) in (3,4): return code
    tid=first(r,'teamId','teamID','id')
    if tid is not None and str(tid) in by_id: return by_id[str(tid)]
    nm=str(first(r,'teamFullName','teamName','name') or '').strip().lower()
    return by_name.get(nm,'')

def fetch_special_teams(year):
    sid=f'{year}{year+1}'
    by_id,by_name=nhl_team_map()
    out={}
    for report in ('powerplay','penaltykill'):
        q=urllib.parse.quote(f'seasonId={sid} and gameTypeId=2',safe='=')
        url=f'{NHL_STATS}/team/{report}?limit=-1&cayenneExp={q}'
        rows=fetch_json(url).get('data',[])
        for r in rows:
            code=row_code(r,by_id,by_name)
            if not code: continue
            d=out.setdefault(code,{})
            if report=='powerplay':
                v=pct(first(r,'ppPct','powerPlayPct','powerPlayPercentage'))
                if v is not None: d['pp']=round(v,4)
                opp=fnum(first(r,'ppOpportunities','powerPlayOpportunities','ppOpportunitiesPerGame'))
                gp=fnum(first(r,'gamesPlayed','games'))
                if opp is not None: d['ppOpp']=round(opp/gp,4) if gp and opp>8 else round(opp,4)
            else:
                v=pct(first(r,'pkPct','penaltyKillPct','penaltyKillPercentage'))
                if v is not None: d['pk']=round(v,4)
                opp=fnum(first(r,'timesShorthanded','pkOpportunities','penaltyKillOpportunities','timesShorthandedPerGame'))
                gp=fnum(first(r,'gamesPlayed','games'))
                if opp is not None: d['pkOpp']=round(opp/gp,4) if gp and opp>8 else round(opp,4)
    return out

def recent_team_form(year):
    """Compact current-season L5/L10 MoneyPuck team-game xG trends.
    This bulk download runs only in GitHub Actions, not on the user's phone.
    """
    txt=fetch_text(MP_GAMES,120)
    teams={}
    for r in csv.DictReader(io.StringIO(txt)):
        try: sy=int(float(r.get('season','0') or 0))
        except Exception: continue
        if sy!=year or str(r.get('situation','')).lower()!='all': continue
        code=normalize_code(first(r,'team','playerTeam','name'))
        if not code: continue
        date=str(r.get('gameDate',''))
        item={
            'date':date,
            'xgf':fnum(r.get('xGoalsFor')),
            'xga':fnum(r.get('xGoalsAgainst')),
            'gf':fnum(r.get('goalsFor')),
            'ga':fnum(r.get('goalsAgainst')),
            'sf':fnum(r.get('shotsOnGoalFor')),
            'sa':fnum(r.get('shotsOnGoalAgainst')),
        }
        teams.setdefault(code,[]).append(item)
    out={}
    for code,rows in teams.items():
        rows=sorted(rows,key=lambda x:x['date'],reverse=True)
        d={'games':len(rows)}
        for n in (5,10,20):
            rr=rows[:n]
            if not rr: continue
            z={}
            for k in ('xgf','xga','gf','ga','sf','sa'):
                vals=[x[k] for x in rr if x[k] is not None]
                if vals: z[k]=round(sum(vals)/len(vals),5)
            z['n']=len(rr); d[f'l{n}']=z
        out[code]=d
    return out

def main():
    season=season_start(); prev=season-1
    files={}; errors={}; special={}; rolling={}
    for yr in (season,prev):
        for name in ('teams.csv','goalies.csv','goalies_10.csv','goalies_20.csv'):
            key=f'{yr}/{name}'; url=f'{MP_BASE}/{yr}/regular/{name}'
            try:
                txt=fetch_text(url)
                if not txt.strip() or ',' not in txt.splitlines()[0]:
                    raise RuntimeError('respuesta no CSV')
                files[key]=txt
                print('OK',key,len(txt))
            except Exception as e:
                errors[key]=str(e); print('WARN',key,e,file=sys.stderr)
        try:
            special[str(yr)]=fetch_special_teams(yr)
            print('OK',yr,'specialTeams',len(special[str(yr)]))
        except Exception as e:
            errors[f'{yr}/specialTeams']=str(e); print('WARN specialTeams',yr,e,file=sys.stderr)
    if os.environ.get('GITHUB_ACTIONS'):
        try:
            rolling[str(season)]=recent_team_form(season)
            print('OK',season,'rolling',len(rolling[str(season)]))
        except Exception as e:
            errors[f'{season}/rolling']=str(e); print('WARN rolling',e,file=sys.stderr)
    if f'{prev}/teams.csv' not in files:
        raise SystemExit('No se pudo obtener el prior MoneyPuck de equipos; no se sobrescribe el feed.')
    payload={
        'schema':3,
        'source':'MoneyPuck.com + NHL Stats API · Goalie Intelligence 2.0',
        'credit':'Data courtesy of MoneyPuck.com; team special-teams data from NHL Stats API; goalie L10/L20 windows from MoneyPuck',
        'updatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'season':season,'previous':prev,'files':files,'specialTeams':special,'rolling':rolling,'errors':errors,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    tmp.replace(OUT)
    print('WROTE',OUT,OUT.stat().st_size)

if __name__=='__main__': main()
