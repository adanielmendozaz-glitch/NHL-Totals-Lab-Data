#!/usr/bin/env python3
import csv, io, json, urllib.parse, urllib.request, datetime, pathlib, sys, os

MP_BASE='https://moneypuck.com/moneypuck/playerData/seasonSummary'
MP_GAMES='https://moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv'
NHL_STATS='https://api.nhle.com/stats/rest/en'
NHL_WEB='https://api-web.nhle.com/v1'
ROOT=pathlib.Path(__file__).resolve().parent
OUT=ROOT/'data'/'nhl_feed.json'
HEADERS={
    'User-Agent':'Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/140 Safari/537.36 NHL-Totals-Lab/0.2.0',
    'Referer':'https://moneypuck.com/data.htm',
    'Accept':'text/csv,application/json,*/*;q=0.8'
}
TEAM_REMAP={'L.A':'LAK','N.J':'NJD','S.J':'SJS','T.B':'TBL','TB':'TBL','LA':'LAK','NJ':'NJD','SJ':'SJS','ARI':'UTA','PHX':'UTA'}
CURRENT_TEAMS=['ANA','BOS','BUF','CAR','CBJ','CGY','CHI','COL','DAL','DET','EDM','FLA','LAK','MIN','MTL','NJD','NSH','NYI','NYR','OTT','PHI','PIT','SEA','SJS','STL','TBL','TOR','UTA','VAN','VGK','WPG','WSH']

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



def nhl_name(obj):
    if isinstance(obj, dict):
        return str(obj.get('default') or obj.get('en') or next(iter(obj.values()), '') or '').strip()
    return str(obj or '').strip()

def compact_roster_player(p):
    firstn=nhl_name(p.get('firstName'))
    lastn=nhl_name(p.get('lastName'))
    name=(' '.join(x for x in (firstn,lastn) if x)).strip() or nhl_name(p.get('name'))
    return {
        'id':p.get('id') or p.get('playerId'),
        'name':name,
        'position':p.get('positionCode') or p.get('position') or '',
        'number':p.get('sweaterNumber'),
    }

def fetch_current_rosters():
    out={}; errs={}
    for code in CURRENT_TEAMS:
        try:
            b=fetch_json(f'{NHL_WEB}/roster/{code}/current',25)
            out[code]={
                'forwards':[compact_roster_player(x) for x in (b.get('forwards') or [])],
                'defensemen':[compact_roster_player(x) for x in (b.get('defensemen') or [])],
                'goalies':[compact_roster_player(x) for x in (b.get('goalies') or [])],
            }
        except Exception as e:
            errs[code]=str(e)
    return out,errs

def score_games_for_date(day):
    b=fetch_json(f'{NHL_WEB}/score/{day}',30)
    out=[]
    for g in b.get('games') or []:
        aid=(g.get('awayTeam') or {}).get('abbrev') or ''
        hid=(g.get('homeTeam') or {}).get('abbrev') or ''
        out.append({
            'id':str(g.get('id') or ''),
            'gameDate':g.get('gameDate') or day,
            'startTimeUTC':g.get('startTimeUTC') or '',
            'gameState':g.get('gameState') or '',
            'gameType':g.get('gameType'),
            'away':normalize_code(aid),
            'home':normalize_code(hid),
            'awayScore':(g.get('awayTeam') or {}).get('score'),
            'homeScore':(g.get('homeTeam') or {}).get('score'),
            'venue':nhl_name(g.get('venue')),
        })
    return [x for x in out if x['id'] and x['away'] and x['home']]

def fetch_schedule_window(today=None):
    today=today or datetime.datetime.now(datetime.timezone.utc).date()
    out=[]; errs={}
    for delta in range(-7,4):
        day=(today+datetime.timedelta(days=delta)).isoformat()
        try:
            out.extend(score_games_for_date(day))
        except Exception as e:
            errs[day]=str(e)
    seen=set(); uniq=[]
    for x in out:
        if x['id'] in seen: continue
        seen.add(x['id']); uniq.append(x)
    return uniq,errs

def compact_box_side(group):
    group=group or {}
    def plist(key):
        out=[]
        for p in group.get(key) or []:
            nm=nhl_name(p.get('name'))
            out.append({'id':p.get('playerId') or p.get('id'),'name':nm,'starter':bool(p.get('starter')),'toi':p.get('toi') or ''})
        return out
    gl=plist('goalies')
    starter=next((x for x in gl if x.get('starter')),None)
    return {
        'forwards':plist('forwards'),
        'defense':plist('defense'),
        'goalies':gl,
        'scratches':plist('scratches'),
        'starter':starter,
    }

def fetch_game_contexts(schedule,today=None):
    today=today or datetime.datetime.now(datetime.timezone.utc).date()
    allowed={(today+datetime.timedelta(days=d)).isoformat() for d in (-1,0,1)}
    out={}; errs={}
    for g in schedule:
        if str(g.get('gameDate'))[:10] not in allowed: continue
        gid=str(g.get('id') or '')
        try:
            b=fetch_json(f'{NHL_WEB}/gamecenter/{gid}/boxscore',20)
            pbs=b.get('playerByGameStats') or {}
            out[gid]={
                'gameState':b.get('gameState') or g.get('gameState') or '',
                'updatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'away':compact_box_side(pbs.get('awayTeam')),
                'home':compact_box_side(pbs.get('homeTeam')),
            }
        except Exception as e:
            errs[gid]=str(e)
    return out,errs

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



def compact_skaters(year):
    """Compact MoneyPuck skater season summary for lineup impact.
    Keeps only totals/rates required by LINEUP_IMPACT_V1 and keys by stable playerId when possible.
    """
    txt=fetch_text(f'{MP_BASE}/{year}/regular/skaters.csv',120)
    out={}
    for r in csv.DictReader(io.StringIO(txt)):
        sit=str(r.get('situation') or '').lower()
        if sit not in ('all','5on5','5on4'): continue
        name=str(first(r,'name','playerName','player') or '').strip()
        if not name: continue
        pid=first(r,'playerId','playerID','player_id')
        key=('id:'+str(pid)) if pid not in (None,'') else ('nm:'+name.lower())
        code=normalize_code(first(r,'team','playerTeam','teamAbbrev','teamCode'))
        z=out.setdefault(key,{'id':pid,'name':name,'team':code,'position':str(first(r,'position','positionCode') or '')})
        d={
            'gp':fnum(first(r,'games_played','gamesPlayed','games')),
            'ice':fnum(first(r,'icetime','iceTime')),
            'ixg':fnum(first(r,'I_F_xGoals','individualExpectedGoals','xGoals')),
            'goals':fnum(first(r,'I_F_goals','goals')),
            'p1a':fnum(first(r,'I_F_primaryAssists','primaryAssists')),
            'p2a':fnum(first(r,'I_F_secondaryAssists','secondaryAssists')),
            'onXGF':fnum(first(r,'OnIce_F_xGoals','onIceExpectedGoalsFor','xGoalsFor')),
            'onXGA':fnum(first(r,'OnIce_A_xGoals','onIceExpectedGoalsAgainst','xGoalsAgainst')),
        }
        z[sit]=d
    return out

def main():
    season=season_start(); prev=season-1
    files={}; errors={}; special={}; rolling={}; skaters={}; official={'protocol':'NHL_OFFICIAL_FEED_V1'}
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
    try:
        for yr in (season,prev):
            skaters[str(yr)]=compact_skaters(yr)
            print('OK',yr,'skaters compact',len(skaters[str(yr)]))
    except Exception as e:
        errors['skaters']=str(e); print('WARN skaters',e,file=sys.stderr)
    if os.environ.get('GITHUB_ACTIONS'):
        try:
            rolling[str(season)]=recent_team_form(season)
            print('OK',season,'rolling',len(rolling[str(season)]))
        except Exception as e:
            errors[f'{season}/rolling']=str(e); print('WARN rolling',e,file=sys.stderr)
    try:
        rosters,rerr=fetch_current_rosters(); official['rosters']=rosters
        for k,v in rerr.items(): errors[f'official/roster/{k}']=v
        print('OK official rosters',len(rosters))
    except Exception as e:
        errors['official/rosters']=str(e); official['rosters']={}
    try:
        sched,serr=fetch_schedule_window(); official['schedule']=sched
        for k,v in serr.items(): errors[f'official/schedule/{k}']=v
        print('OK official schedule',len(sched))
    except Exception as e:
        errors['official/schedule']=str(e); official['schedule']=[]
    try:
        contexts,cerr=fetch_game_contexts(official.get('schedule') or []); official['contexts']=contexts
        for k,v in cerr.items(): errors[f'official/context/{k}']=v
        print('OK official contexts',len(contexts))
    except Exception as e:
        errors['official/contexts']=str(e); official['contexts']={}
    official['updatedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    if f'{prev}/teams.csv' not in files:
        raise SystemExit('No se pudo obtener el prior MoneyPuck de equipos; no se sobrescribe el feed.')
    payload={
        'schema':5,
        'source':'MoneyPuck.com + NHL Stats/Web API · Player/Lineup + Schedule Intelligence',
        'credit':'Data courtesy of MoneyPuck.com; official schedule/rosters/game context from NHL Web API; special teams from NHL Stats API',
        'updatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'season':season,'previous':prev,'files':files,'specialTeams':special,'rolling':rolling,'skaters':skaters,'official':official,'errors':errors,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    tmp.replace(OUT)
    print('WROTE',OUT,OUT.stat().st_size)

if __name__=='__main__': main()
