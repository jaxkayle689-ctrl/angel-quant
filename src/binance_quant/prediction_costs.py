"""Prospective published-fee sensitivity; not actual historical execution."""
import json
from decimal import Decimal as D
from pathlib import Path
import pandas as pd
from .prediction_month import run_month


def main():
    root=Path('experiments/prediction_btc5m')
    raw=pd.read_csv(root/'BTCUSDT-5m-2026-08.csv',header=None)
    frame=pd.DataFrame({'time':pd.to_datetime(raw[0],unit='us',utc=True),'open':raw[1],'close':raw[4]})
    results={}
    for name,price,fee in [('baseline','.50','0'),('official_taker_fee_only','.50','.02'),('fee_and_half_cent_slippage','.505','.02'),('fee_and_one_cent_slippage','.51','.02')]:
        price=D(price)
        rate=D(fee)*min(price,1-price)/price
        r=run_month(frame,recycle_only=True,ask=price,buy_fee_rate=rate)
        r['scenario_label']='HYPOTHETICAL: minimum order ignored; current fee schedule applied prospectively, not verified August account rate; adverse prices are assumptions'
        results[name]=r
    (root/'cost_sensitivity.json').write_text(json.dumps(results,indent=2)+'\n')
    # Preflight, not a claimed historical rejection or a submitted order.
    limits={'base_bet':.5,'provider_documented_minimum':1,'binance_market_approx_minimum':1.5,
        'status':'BLOCKED_BY_DOCUMENTED_MINIMUM','orders_submitted':0,'actual_execution':'unavailable',
        'note':'Do not round up the user stake without changing the strategy. LIMIT exemption from 1.5 does not establish exemption from provider minimum.'}
    (root/'cost_execution_preflight.json').write_text(json.dumps(limits,indent=2)+'\n')

if __name__=='__main__': main()
