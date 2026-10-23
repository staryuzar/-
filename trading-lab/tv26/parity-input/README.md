# TradingView CSV input files

Place these five exported CSV files in this directory:

- TV26_M1.csv
- TV26_M5.csv
- TV26_M15.csv
- TV26_M30.csv
- TV26_H1.csv

Export them from the Pine indicator at `trading-lab/tv26/TradingView_Parity_Components_1TF.pine`. Select the matching chart timeframe and export chart data with indicator values included. Required columns include TV26.bar_open_time, TV26.open/high/low/close, TV26.total/ma/osc, and all 26 TV26 component vote columns.

The cloud workflow retrieves the MT5 audit CSV itself from a successful GitHub Actions audit run. Do not upload broker credentials, MT5 login files, account passwords, or tester .ini files here.

A direct parity report is only meaningful when TradingView and MT5 bars represent the same instrument/feed and the broker UTC offset is correct.