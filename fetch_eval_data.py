#!/usr/bin/env python3
import json, datetime, yfinance as yf, os

today = datetime.date.today()
start = today - datetime.timedelta(days=5*365)
syms = ['NVDA','AAPL','MSFT','GOOGL','META','AMZN','AMD','AVGO','TSM','PLTR','SPY','QQQ']
d = {}
for s in syms:
    hi = yf.Ticker(s).history(start=start.isoformat(), end=today.isoformat(), interval='1d')
    d[s] = [(round(float(r['Close']),2), str(idx.date())) for idx,r in hi.iterrows() if float(r['Close'])>0]
    print(f'{s}: {len(d[s])}d {d[s][0][1]}~{d[s][-1][1]}')
# Save to a file without leading dot
fpath = os.path.join(os.getcwd(), 'eval_data.json')
json.dump(d, open(fpath,'w'))
print(f'SAVED ({os.path.getsize(fpath)} bytes)')