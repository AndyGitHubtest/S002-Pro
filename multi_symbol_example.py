"""
S002 Multi-Symbol Backtest Example (v2.5)
展示如何同时回测多个币种
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from datetime import datetime
from core.strategy import S002Engine
from core.signals import SignalGenerator

def generate_mock_data(symbol: str, days: int = 365, trend: str = "bull"):
    """生成模拟数据用于演示多币种回测"""
    start_date = datetime(2023, 1, 1)
    freq = '5min'
    periods = days * 24 * 12
    dates = pd.date_range(start=start_date, periods=periods, freq=freq)
    
    # 基于币种设置不同的起始价格
    base_price = {'BTC/USDT': 100.0, 'ETH/USDT': 50.0, 'SOL/USDT': 20.0}.get(symbol, 100.0)
    
    data = {'open': [], 'high': [], 'low': [], 'close': [], 'volume': []}
    price = base_price
    
    for i in range(periods):
        # 根据趋势调整漂移
        if trend == "bull":
            drift = 0.0002  # 小上涨趋势
        elif trend == "bear":
            drift = -0.0001
        else:
            drift = 0
            
        noise = np.random.normal(drift, 0.002)
        price = price * (1 + noise)
        
        # 偶尔添加突破
        if i > 1000 and i % 2000 == 0:
            price *= 1.03  # 3% 突破
        
        data['open'].append(price * 0.999)
        data['close'].append(price)
        data['high'].append(price * 1.002)
        data['low'].append(price * 0.998)
        data['volume'].append(int(1000000))
    
    df = pd.DataFrame(data, index=dates)
    df['symbol'] = symbol
    return df

def run_multi_symbol_backtest():
    """运行多币种回测"""
    
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    trends = ['bull', 'bull', 'bull']  # 每个币种的趋势
    
    config = {
        'risk_per_trade': 0.02,
        'max_hold_bars_unprofitable': 144,
        'trailing_atr_mult': 4.0,
        'max_concurrent_positions': 3,
        'taker_fee': 0.0005,
        'maker_fee': 0.0002
    }
    
    all_results = []
    
    for symbol, trend in zip(symbols, trends):
        print(f"\n{'='*50}")
        print(f"Backtesting {symbol} ({trend} trend)")
        print(f"{'='*50}")
        
        # 生成数据
        df = generate_mock_data(symbol, days=180, trend=trend)
        df['SMA200'] = df['close'].rolling(window=200).mean()
        
        # 创建引擎和信号生成器
        engine = S002Engine(config)
        
        class FilteredSignalGenerator(SignalGenerator):
            def check_signal(self, idx: int) -> dict | None:
                signal = super().check_signal(idx)
                if signal is None:
                    return None
                
                # 趋势过滤
                if idx < 200:
                    return None
                if self.df.loc[self.df.index[idx], 'SMA200'] > signal['entry_price']:
                    return None
                
                return signal
        
        sig_gen = FilteredSignalGenerator(df, config, symbol=symbol)
        
        # 运行回测
        engine.run(df, signal_generator=sig_gen, symbol=symbol)
        
        # 统计结果
        total_pnl = engine.balance - engine.initial_balance
        exit_trades = [t for t in engine.trades_log if t['type'] in ['EXIT', 'TP']]
        wins = [t for t in exit_trades if t.get('pnl', 0) > 0]
        losses = [t for t in exit_trades if t.get('pnl', 0) < 0]
        
        result = {
            'symbol': symbol,
            'final_balance': engine.balance,
            'net_pnl': total_pnl,
            'return_pct': (total_pnl / engine.initial_balance) * 100,
            'total_trades': len(exit_trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(exit_trades) if exit_trades else 0
        }
        all_results.append(result)
        
        print(f"Final Balance: {engine.balance:,.2f}")
        print(f"Net PnL: {total_pnl:,.2f} ({result['return_pct']:.2f}%)")
        print(f"Trades: {result['total_trades']} (W:{result['wins']}/L:{result['losses']})")
        print(f"Win Rate: {result['win_rate']:.2%}")
    
    # 汇总
    print(f"\n{'='*50}")
    print("MULTI-SYMBOL SUMMARY")
    print(f"{'='*50}")
    
    total_pnl_all = sum(r['net_pnl'] for r in all_results)
    total_trades = sum(r['total_trades'] for r in all_results)
    
    for r in all_results:
        print(f"{r['symbol']}: {r['net_pnl']:+,.2f} ({r['return_pct']:+.2f}%) | "
              f"WR: {r['win_rate']:.1%} | Trades: {r['total_trades']}")
    
    print(f"\nCombined PnL: {total_pnl_all:+,.2f}")
    print(f"Total Trades: {total_trades}")

if __name__ == "__main__":
    run_multi_symbol_backtest()
