import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from datetime import datetime
from core.strategy import S002Engine
from core.signals import SignalGenerator
from utils.math_utils import calculate_atr

def generate_synthetic_data(days=30):
    """
    Generate synthetic OHLCV data with a known breakout pattern.
    """
    start_date = datetime(2023, 1, 1)
    freq = '5min'
    periods = days * 24 * 12
    dates = pd.date_range(start=start_date, periods=periods, freq=freq)
    
    data = {'open': [], 'high': [], 'low': [], 'close': [], 'volume': []}
    
    price = 100.0
    phase = 'compression'
    
    for i, date in enumerate(dates):
        noise = np.random.normal(0, 0.05)
        
        if i < 1440: # 5 days compression
            price = 100.0 + noise
            phase = 'compression'
        elif i == 1440 + 10: # Breakout
            price = 105.0 
            phase = 'breakout'
        elif i == 1440 + 20: # Pullback
            price = 103.5
            phase = 'pullback'
        else:
            # Trend up
            price += 0.01 + noise * 0.1
            phase = 'trend'
            
        if phase == 'compression':
            data['open'].append(price)
            data['high'].append(price + 0.1)
            data['low'].append(price - 0.1)
            data['close'].append(price)
        elif phase == 'breakout':
            data['open'].append(100.0)
            data['high'].append(105.5)
            data['low'].append(100.0)
            data['close'].append(105.0)
            price = 105.0
        elif phase == 'pullback':
            data['open'].append(105.0)
            data['high'].append(105.0)
            data['low'].append(103.0)
            data['close'].append(103.5)
            price = 103.5
        else:
            data['open'].append(price)
            data['high'].append(price + 0.3)
            data['low'].append(price - 0.1)
            data['close'].append(price + 0.2)
            price += 0.2
            
        data['volume'].append(100000)
        
    return pd.DataFrame(data, index=dates)

def run_backtest():
    print("Starting v2.1 Backtest (Expert Fixes)...")
    print("-" * 50)
    
    df = generate_synthetic_data(days=30)
    
    config = {
        'risk_per_trade': 0.02,
        'max_hold_bars_unprofitable': 144, # 12 hours
        'trailing_atr_mult': 2.0,
        'max_concurrent_positions': 3
    }
    
    engine = S002Engine(config)
    sig_gen = SignalGenerator(df, config)
    
    engine.run(df, signal_generator=sig_gen)
    
    print("\n" + "=" * 50)
    print(f"FINAL PnL: {engine.balance - 10000.0:.2f}")
    print(f"Final Balance: {engine.balance:.2f}")
    
    print("\nTrade Details (Wins only):")
    for t in engine.trades_log:
        if t['pnl'] > 0:
            sign = "+"
            print(f"  {t['type']} ({t.get('level', '?')}) @ {t['price']:.2f} | PnL: {sign}{t['pnl']:.2f}")

if __name__ == "__main__":
    run_backtest()
