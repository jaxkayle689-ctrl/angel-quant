"""Single odd-candle sequence statistics; no inferred Prediction fills."""
import json
from pathlib import Path
import pandas as pd


def statistics(frame):
    if frame.empty or not frame.time.is_monotonic_increasing or not frame.time.diff().dropna().eq(pd.Timedelta(minutes=5)).all():
        raise ValueError('Contiguous sorted five-minute data required')
    # K1 is the first UTC candle of each sample; do not reset parity each day.
    rows=frame.iloc[::2]
    colours=['UP' if c>o else 'DOWN' if c<o else 'TIE' for o,c in zip(rows.open,rows.close)]
    result={}
    for length in [1,3,4,5]:
        by_side={}
        for side in ['UP','DOWN']:
            indices=[i for i in range(length,len(colours)) if colours[i-length:i]==[side]*length]
            n=len(indices)
            wins=sum(colours[i]==side for i in indices)
            by_side[side]={'signals':n,'same':wins,'opposite':sum(colours[i] not in [side,'TIE'] for i in indices),'tie':sum(colours[i]=='TIE' for i in indices),'continuation_probability':wins/n if n else None}
        result[str(length)]=by_side
    return {'kind':'SPOT_COLOUR_PROXY_NOT_PREDICTION','anchor':str(frame.time.iloc[0]),'candles':len(frame),'selected_candles':len(rows),'conditional_consecutive_selected_colours':result,'actual_limit_fill_rate':'unavailable','actual_fees':'unavailable','actual_pnl':'unavailable'}


def main():
    root=Path('experiments/prediction_btc5m')
    out={}
    for month in ['2026-06','2026-07','2026-08']:
        raw=pd.read_csv(root/f'BTCUSDT-5m-{month}.csv',header=None)
        f=pd.DataFrame({'time':pd.to_datetime(raw[0],unit='us',utc=True),'open':raw[1],'close':raw[4]})
        out[month]=statistics(f)
    (root/'stride_single_statistics.json').write_text(json.dumps(out,indent=2)+'\n')
    for m,r in out.items(): print(m,r['conditional_consecutive_selected_colours']['3'])

if __name__=='__main__': main()
