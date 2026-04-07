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
    Pattern:
    - Days 1-5: Sideways (Compression) at 100.0
    - Day 6: Breakout (Jump to 105.0)
    - Days 7-8: Pullback (Dip to 103.5, testing support)
    - Days 9+: Strong Trend Up to 130.0
    """
    start_date = datetime(2023, 1, 1)
    freq = '5min'
    periods = days * 24 * 12  # 5m candles
    dates = pd.date_range(start=start_date, periods=periods, freq=freq)
    
    data = {'open': [], 'high': [], 'low': [], 'close': [], 'volume': []}
    
    price = 100.0
    phase = 'compression'
    
    for i, date in enumerate(dates):
        noise = np.random.normal(0, 0.05) # Small noise
        
        if i < 1440: # 5 days
            price = 100.0 + noise
            phase = 'compression'
        elif i == 1440 + 10: # Breakout candle
            price = 105.0 
            phase = 'breakout'
        elif i == 1440 + 20: # Pullback candle
            price = 103.5 # Test support (Above SL 102.0)
            phase = 'pullback'
        else:
            # Trend up
            price += 0.01 + noise * 0.1
            phase = 'trend'
            
        # OHLC generation based on phase
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
            data['low'].append(103.0) # Deep pullback
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
    print("Starting Full Logic Backtest (v2.0)...")
    print("-" * 50)
    
    # 1. Load Data
    df = generate_synthetic_data(days=30)
    print(f"Generated {len(df)} bars of synthetic data.")
    
    # 2. Config
    config = {
        'risk_per_trade': 0.02,
        'max_hold_bars_unprofitable': 144, # 12 hours
        'trailing_atr_mult': 2.0,
        'stop_loss_atr_mult': 1.5
    }
    
    engine = S002Engine(config)
    sig_gen = SignalGenerator(df, config)
    
    # 3. Run
    engine.run(df, signal_generator=sig_gen)
    
    # 4. Report
    print("\n" + "=" * 50)
    print("FINAL REPORT")
    print("=" * 50)
    print(f"Total Trades (Events): {len(engine.trades_log)}")
    total_pnl = sum(t['pnl'] for t in engine.trades_log)
    print(f"Total Net PnL: {total_pnl:.2f}")
    
    win_trades = [t for t in engine.trades_log if t['pnl'] > 0]
    loss_trades = [t for t in engine.trades_log if t['pnl'] < 0]
    print(f"Winning Trades: {len(win_trades)}")
    print(f"Losing Trades: {len(loss_trades)}")

    print("\nTrade Details:")
    for t in engine.trades_log:
        if t['pnl'] != 0:
            sign = "+" if t['pnl'] > 0 else ""
            print(f"  {t['type']} ({t.get('level', '?')}) @ {t['price']:.2f} | PnL: {sign}{t['pnl']:.2f}")

if __name__ == "__main__":
    run_backtest()
