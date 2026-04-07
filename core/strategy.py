import pandas as pd
import numpy as np
import uuid

class S002Position:
    """
    Represents a single open position in S002.
    v2.1 Updates: 25/25/50 TP structure, 12h time lock.
    """
    def __init__(self, symbol: str, entry_price: float, stop_price: float, 
                 quantity: float, risk_distance: float, entry_time: pd.Timestamp,
                 tp_levels: dict, config: dict):
        self.id = str(uuid.uuid4())
        self.symbol = symbol
        self.entry_price = entry_price
        self.stop_price = stop_price
        self.quantity = quantity  # Target quantity
        self.remaining_qty = quantity  # Filled quantity
        self.entry_time = entry_time
        self.risk_distance = risk_distance
        
        # Config
        self.config = config
        self.max_hold_bars_unprofitable = config.get('max_hold_bars_unprofitable', 144) # 12h
        
        # TP Levels
        self.tp_levels = tp_levels
        self.tp_statuses = {k: False for k in tp_levels.keys()}
        
        # State
        self.tp1_triggered = False
        self.highest_price = entry_price
        self.hold_bars = 0
        self.trailing_stop_price = stop_price
        self.trailing_atr_mult = config.get('trailing_atr_mult', 2.0)

    def update(self, bar: pd.Series, current_atr: float):
        """Update position state. Returns list of executed trades."""
        trades = []
        self.hold_bars += 1
        self.highest_price = max(self.highest_price, bar['high'])
        
        # 1. Check Stop Loss (Hard Stop) - Uses Low for safety
        if bar['low'] <= self.stop_price:
            return self.close_position(self.stop_price, 'STOP_LOSS', self.remaining_qty, trades)

        # 2. Check Time Limit (Only if not profitable/TP1 not hit)
        if not self.tp1_triggered and self.hold_bars > self.max_hold_bars_unprofitable:
            return self.close_position(bar['close'], 'TIME_STOP', self.remaining_qty, trades)

        # 3. Check Trailing Stop (TP6) - Only tightens after TP1
        if self.tp1_triggered:
            new_trailing = self.highest_price - (current_atr * self.trailing_atr_mult)
            if new_trailing > self.trailing_stop_price:
                self.trailing_stop_price = new_trailing
            
            # If trailing stop hit
            if bar['low'] <= self.trailing_stop_price:
                return self.close_position(self.trailing_stop_price, 'TRAILING_STOP', self.remaining_qty, trades)

        # 4. Check Take Profits (TP1 - TP2)
        # v2.1: 25% @ TP1, 25% @ TP2, 50% Trailing (TP6 handled above)
        tp_ratio_map = {
            'TP1': 0.25, 
            'TP2': 0.25
        }

        for tp_name in ['TP1', 'TP2']:
            tp_price = self.tp_levels.get(tp_name)
            
            if tp_price and not self.tp_statuses[tp_name]:
                # Check if High reached TP
                if bar['high'] >= tp_price:
                    close_qty = self.quantity * tp_ratio_map[tp_name]
                    close_qty = min(close_qty, self.remaining_qty)
                    
                    if close_qty > 0.0001:
                        self.tp_statuses[tp_name] = True
                        trades.append({
                            'symbol': self.symbol,
                            'type': 'TP',
                            'level': tp_name,
                            'price': tp_price,
                            'qty': close_qty,
                            'pnl': (tp_price - self.entry_price) * close_qty
                        })
                        self.remaining_qty -= close_qty
                        
                        # Iron Rule: TP1 triggers Breakeven & Unlocks Time Limit
                        if tp_name == 'TP1':
                            self.tp1_triggered = True
                            be_price = self.entry_price * 1.0005 
                            if be_price > self.stop_price:
                                self.stop_price = be_price
                                self.trailing_stop_price = be_price
                        
                        if self.remaining_qty <= 0.0001:
                            return trades

        return trades

    def close_position(self, price: float, reason: str, qty: float, trades: list):
        pnl = (price - self.entry_price) * qty
        trades.append({
            'symbol': self.symbol,
            'type': 'EXIT',
            'level': reason,
            'price': price,
            'qty': qty,
            'pnl': pnl
        })
        self.remaining_qty = 0
        return trades


class S002Engine:
    """
    Main Backtest Engine v2.1.
    """
    def __init__(self, config: dict):
        self.config = config
        self.positions: list[S002Position] = []
        self.pending_orders = [] 
        self.balance = 10000.0
        self.trades_log = []
        self.max_concurrent_positions = config.get('max_concurrent_positions', 3)
        
    def run(self, df: pd.DataFrame, signal_generator=None):
        for i in range(100, len(df)):
            bar = df.iloc[i]
            current_atr = df['atr'].iloc[i]
            
            # 1. Check Pending Orders
            filled_orders = []
            expired_orders = []
            for order in self.pending_orders:
                order['age'] += 1
                
                # Timeout Check (v2.1: 12 bars / 1 hour)
                if order['age'] > 12:
                    expired_orders.append(order)
                    continue

                # Fill Check
                if bar['low'] <= order['limit_price']:
                    print(f"[{df.index[i]}] Limit Order FILLED @ {order['limit_price']}")
                    pos = next((p for p in self.positions if p.id == order['pos_id']), None)
                    if pos:
                        pos.remaining_qty += order['unfilled_qty']
                        self.trades_log.append({
                            'symbol': pos.symbol, 'type': 'LIMIT_FILL',
                            'price': order['limit_price'], 'qty': order['unfilled_qty'], 'pnl': 0
                        })
                    filled_orders.append(order)
            
            for o in filled_orders + expired_orders:
                if o in self.pending_orders:
                    self.pending_orders.remove(o)

            # 2. Update existing positions & Balance
            open_pos = []
            for pos in self.positions:
                if pos.remaining_qty > 0:
                    trades = pos.update(bar, current_atr)
                    for t in trades:
                        if t['type'] == 'EXIT' or t['type'] == 'LIMIT_FILL': # Limit fill doesn't affect balance PnL
                             if t['type'] == 'EXIT':
                                self.balance += t['pnl']
                    self.trades_log.extend(trades)
                    
                    if pos.remaining_qty > 0:
                        open_pos.append(pos)
            self.positions = open_pos
            
            # 3. Check for New Signals
            if signal_generator:
                # Check max positions
                if len(self.positions) < self.max_concurrent_positions:
                    signal = signal_generator.check_signal(i)
                    if signal:
                        self.open_hybrid_position(signal, df.index[i])

        return self.trades_log

    def open_hybrid_position(self, signal: dict, entry_time: pd.Timestamp):
        symbol = "BTC/USDT" 
        entry_price = signal['entry_price']
        
        # Risk calc
        total_qty = (self.balance * self.config['risk_per_trade']) / signal['risk_distance']
        
        # v2.1: 50/50 Split
        instant_qty = total_qty * 0.50
        limit_qty = total_qty * 0.50
        
        # Create Position
        pos = S002Position(
            symbol=symbol, entry_price=entry_price, stop_price=signal['sl_price'],
            quantity=total_qty, risk_distance=signal['risk_distance'], entry_time=entry_time,
            tp_levels=signal['tp_levels'], config=self.config
        )
        
        # Initial fill
        pos.remaining_qty = instant_qty
        self.positions.append(pos)
        
        self.trades_log.append({
            'symbol': symbol, 'type': 'MARKET_FILL',
            'price': entry_price, 'qty': instant_qty, 'pnl': 0
        })
        
        # Place Pending Limit Order
        self.pending_orders.append({
            'pos_id': pos.id, 'limit_price': signal['limit_price'],
            'unfilled_qty': limit_qty, 'age': 0
        })
        
        print(f"[{entry_time}] SIGNAL: Entry @ {entry_price:.2f}, SL @ {signal['sl_price']:.2f}")
        print(f"           Instant 50% ({instant_qty:.2f}), Limit 50% @ {signal['limit_price']:.2f}")
