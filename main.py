import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from datetime import datetime
from core.strategy import S002Engine
from core.signals import SignalGenerator

def generate_step_trend_data(days=365):
    """
    生成“阶梯式上涨”数据。
    模拟：长时间横盘震荡（蓄势） -> 突然暴涨（突破） -> 横盘。
    这是动量策略最容易赚钱的形态。
    """
    start_date = datetime(2023, 1, 1)
    freq = '5min'
    periods = days * 24 * 12
    dates = pd.date_range(start=start_date, periods=periods, freq=freq)
    
    data = {'open': [], 'high': [], 'low': [], 'close': [], 'volume': []}
    
    price = 100.0
    jump_interval = 2000  # 每 2000 根 K 线 (约 7 天) 发生一次突破
    jump_size = 0.15      # 每次突破涨幅 15%
    
    print("Generating step-trend data...")
    for i in range(periods):
        # 1. 基础震荡 (噪音)
        noise = np.random.normal(0, 0.002) # 0.2% 噪音
        price = price * (1 + noise)
        
        # 2. 突破逻辑 (每 2000 根 K 线)
        if i > 1000 and (i % jump_interval == 0):
            # 触发突破：连续 5 根 K 线大涨
            for j in range(5):
                jump_ret = (jump_size / 5) + np.random.normal(0, 0.005)
                price = price * (1 + jump_ret)
                data['open'].append(price * 0.99)
                data['close'].append(price)
                data['high'].append(price * 1.01)
                data['low'].append(price * 0.98)
                data['volume'].append(int(5000000)) # 爆量
                i += 1 # Skip main loop increment? No, just fill buffer.
        
        # 正常填充
        if len(data['close']) < periods: # Ensure we don't overflow if loop logic was complex, but here simple append
             # Re-implementing loop structure to be safe
             pass 

    # Let's rewrite the loop cleanly
    data = {'open': [], 'high': [], 'low': [], 'close': [], 'volume': []}
    price = 100.0
    current_idx = 0
    
    while current_idx < periods:
        # Check if it's jump time
        if current_idx > 500 and (current_idx % jump_interval < 5):
            # Breakout phase
            jump_ret = 0.03 # 3% per candle
            price = price * (1 + jump_ret)
            
            data['open'].append(price * 0.995)
            data['close'].append(price)
            data['high'].append(price * 1.005)
            data['low'].append(price * 0.99)
            data['volume'].append(int(2000000))
        else:
            # Consolidation phase
            noise = np.random.normal(0, 0.001)
            price = price * (1 + noise)
            
            data['open'].append(price)
            data['close'].append(price + np.random.normal(0, 0.05))
            data['high'].append(max(data['open'][-1], data['close'][-1]) + 0.1)
            data['low'].append(min(data['open'][-1], data['close'][-1]) - 0.1)
            data['volume'].append(int(100000))
            
        current_idx += 1
        if len(data['close']) >= periods: break

    return pd.DataFrame(data, index=dates[:periods])

def run_backtest():
    print("Starting v2.6 Step-Trend Test (Verification)...")
    print("-" * 50)
    
    # 生成数据
    df = generate_step_trend_data(days=365)
    print(f"Data Generated: {len(df)} bars")
    print(f"Start Price: {df['close'].iloc[0]:.2f} -> End Price: {df['close'].iloc[-1]:.2f}")
    
    # 计算 SMA200 用于趋势过滤
    df['SMA200'] = df['close'].rolling(window=200).mean()
    
    config = {
        'risk_per_trade': 0.02,
        'max_hold_bars_unprofitable': 144, # 12 hours
        'trailing_atr_mult': 4.0,
        'max_concurrent_positions': 3,
        'taker_fee': 0.0005,  # 0.05% for market orders
        'maker_fee': 0.0002   # 0.02% for limit orders
    }
    
    engine = S002Engine(config)
    
    # 注入 Trend Filter
    class FilteredSignalGenerator(SignalGenerator):
        def check_signal(self, idx: int) -> dict | None:
            signal = super().check_signal(idx)
            if signal is None: return None
            
            # 1. 趋势过滤
            if idx < 200: return None
            if self.df.loc[self.df.index[idx], 'SMA200'] > signal['entry_price']:
                return None 
            
            # 2. 修正止损 (ATR based)
            row = self.df.iloc[idx]
            atr = row['atr']
            
            # 宽止损：3.0 ATR (因为是阶梯数据，波动可能不大，给足空间)
            new_sl = signal['entry_price'] - (atr * 3.0)
            
            signal['sl_price'] = new_sl
            signal['risk_distance'] = signal['entry_price'] - new_sl
            signal['limit_price'] = signal['entry_price'] - (atr * 1.0)
            
            return signal

    sig_gen = FilteredSignalGenerator(df, config)
    
    start_time = time.time()
    engine.run(df, signal_generator=sig_gen)
    elapsed = time.time() - start_time
    
    print(f"\n" + "=" * 50)
    print(f"EXECUTION TIME: {elapsed:.3f} seconds")
    print(f"INIT BALANCE: {engine.initial_balance:,.2f}")
    print(f"FINAL BALANCE: {engine.balance:,.2f}")
    
    total_pnl = engine.balance - engine.initial_balance
    total_return = (total_pnl / engine.initial_balance) * 100
    print(f"NET PROFIT: {total_pnl:,.2f} ({total_return:.2f}%)")
    
    # Fee summary
    total_fees = sum(t.get('fee', 0) for t in engine.trades_log)
    print(f"TOTAL FEES: {total_fees:,.2f}")
    
    # Trade stats
    exit_trades = [t for t in engine.trades_log if t['type'] in ['EXIT', 'TP']]
    wins = [t for t in exit_trades if t.get('pnl', 0) > 0]
    losses = [t for t in exit_trades if t.get('pnl', 0) < 0]
    
    print(f"\nTRADE STATS:")
    print(f"Total Exits: {len(exit_trades)}")
    if exit_trades:
        print(f"WINS: {len(wins)} | LOSSES: {len(losses)}")
        win_rate = len(wins) / len(exit_trades)
        print(f"WIN RATE: {win_rate:.2%}")
        if wins:
            avg_win = np.mean([t['pnl'] for t in wins])
            print(f"AVG WIN: {avg_win:.2f}")
        if losses:
            avg_loss = np.mean([t['pnl'] for t in losses])
            print(f"AVG LOSS: {avg_loss:.2f}")
            
        # Gross vs Net
        gross_profit = sum(t.get('gross_pnl', 0) for t in wins)
        gross_loss = sum(t.get('gross_pnl', 0) for t in losses)
        print(f"\nGROSS PROFIT: {gross_profit:,.2f}")
        print(f"GROSS LOSS: {gross_loss:,.2f}")
        print(f"NET PnL (excl. fees): {gross_profit + gross_loss:,.2f}")
        print(f"NET PnL (incl. fees): {total_pnl:,.2f}")

if __name__ == "__main__":
    run_backtest()
