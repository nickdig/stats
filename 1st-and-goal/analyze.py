"""First 1st-and-goal per drive, nflverse 1999–2025 (REG + POST).
Run: pip install pandas pyarrow matplotlib requests; python analyze.py
Raw data downloaded only when absent. Results are drive-level, not play-level.
"""
from pathlib import Path
import json
import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
COLUMNS = ['season','season_type','game_id','play_id','game_seconds_remaining','drive','fixed_drive',
           'fixed_drive_result','down','goal_to_go','yardline_100','play_type',
           'penalty','posteam','td_team','touchdown','return_touchdown','desc']
all_first=[]
audit=[]
for season in range(1999,2026):
    path=DATA/f'play_by_play_{season}.parquet'
    if not path.exists():
        url=f'https://github.com/nflverse/nflverse-data/releases/download/pbp/{path.name}'
        r=requests.get(url,timeout=180); r.raise_for_status(); path.write_bytes(r.content)
    d=pd.read_parquet(path,columns=COLUMNS)
    d=d[d.season_type.isin(['REG','POST'])].sort_values(['game_id','game_seconds_remaining','play_id'], ascending=[True,False,True])
    # nflverse fixed_drive reconciles the occasional possession labeling error.
    d['drive_key']=d.fixed_drive.fillna(d.drive)
    keys=['game_id','drive_key']
    candidate=(d.down.eq(1)&d.goal_to_go.eq(1)&d.yardline_100.notna()
               &(d.play_type.isin(['run','pass']) | (d.play_type.eq('no_play')&d.penalty.eq(1)))
               &d.posteam.notna()&d.drive_key.notna())
    first=d[candidate].drop_duplicates(keys,keep='first').copy()
    # Actual, non-nullified TD credited to possession team, not a defensive return.
    d['offensive_td']=(d.touchdown.eq(1)&d.td_team.eq(d.posteam)
                       &d.play_type.ne('no_play')&~d.return_touchdown.eq(1))
    flags=d.groupby(keys).offensive_td.any().rename('offensive_td_flag')
    first=first.join(flags,on=keys)
    first['td']=first.fixed_drive_result.eq('Touchdown')
    mismatch=first[first.td.ne(first.offensive_td_flag)]
    for _,r in mismatch.iterrows():
        audit.append(r.to_dict())
    all_first.append(first)
    print(season,len(first),'TD',int(first.td.sum()),'mismatches',len(mismatch),flush=True)
f=pd.concat(all_first,ignore_index=True)
f.to_csv(ROOT/'first_goal_drives.csv',index=False)
pd.DataFrame(audit).to_csv(ROOT/'scoring_audit.csv',index=False)

def summarize(x,name):
    x=x.copy()
    x['yard_line']=x.yardline_100.astype(int).map(lambda v: str(v) if v<20 else '20+')
    out=x.groupby('yard_line').td.agg(drives='size',touchdowns='sum').reset_index()
    out['sort']=out.yard_line.map(lambda v:20 if v=='20+' else int(v))
    out=out.sort_values('sort').drop(columns='sort')
    out['td_pct']=100*out.touchdowns/out.drives
    n=out.drives; p=out.touchdowns/n; z=1.959963984540054
    center=(p+z*z/(2*n))/(1+z*z/n)
    half=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    out['ci95_low_pct']=100*(center-half);out['ci95_high_pct']=100*(center+half)
    out.to_csv(ROOT/f'{name}.csv',index=False,float_format='%.4f')
    print('\n'+name+'\n'+out.to_string(index=False))
    print('OVERALL',len(x),int(x.td.sum()),100*x.td.mean())
    return out
out=summarize(f,'td_by_starting_yard')
summarize(f[f.season.ge(2015)],'td_by_starting_yard_2015_2025')
fig,ax=plt.subplots(figsize=(11,6))
x=np.arange(len(out)); y=out.td_pct
ax.errorbar(x,y,yerr=[y-out.ci95_low_pct,out.ci95_high_pct-y],fmt='o-',color='#16658b',capsize=3,lw=1.6)
for i,r in enumerate(out.itertuples()):
    ax.annotate(f'n={r.drives:,}',(i,r.td_pct),xytext=(0,12),textcoords='offset points',ha='center',fontsize=7)
ax.set(xticks=x,xticklabels=out.yard_line,ylim=(0,103),xlabel='Yards from opponent’s goal line at first 1st-and-goal',ylabel='Drive ends in offensive touchdown (%)',title='NFL: touchdown conversion after first 1st-and-goal')
ax.grid(axis='y',alpha=.2);ax.spines[['top','right']].set_visible(False)
fig.text(.08,.015,'nflverse play-by-play • 1999–2025 regular + postseason • one observation per drive • 95% Wilson intervals',fontsize=9,color='#555555')
fig.tight_layout(rect=(0,.04,1,1));fig.savefig(ROOT/'td_success.png',dpi=180);plt.close(fig)
meta={'seasons':[1999,2025],'season_types':['REG','POST'],'in_progress_2026_included':False,'drives':len(f),'touchdowns':int(f.td.sum()),'td_pct':100*f.td.mean(),'scoring_flag_mismatches':len(audit),'yardline_min':float(f.yardline_100.min()),'yardline_max':float(f.yardline_100.max()),'source':'https://github.com/nflverse/nflverse-data/releases/tag/pbp'}
(ROOT/'summary.json').write_text(json.dumps(meta,indent=2))
print(json.dumps(meta,indent=2))
