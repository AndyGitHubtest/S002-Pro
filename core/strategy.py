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
            return self.close_position(self.stop_price, 'STOP_LOSS', self.remaining_qty, trades, fee_rate=0.0005)

        # 2. Check Time Limit (Only if not profitable/TP1 not hit)
        if not self.tp1_triggered and self.hold_bars > self.max_hold_bars_unprofitable:
            return self.close_position(bar['close'], 'TIME_STOP', self.remaining_qty, trades, fee_rate=0.0005)

        # 3. Check Take Profits (TP1 - TP2) FIRST (before trailing stop)
        # v2.2: 25% @ TP1, 25% @ TP2, 50% Trailing (TP6 handled after)
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
                        gross_pnl = (tp_price - self.entry_price) * close_qty
                        notional = tp_price * close_qty
                        fee = notional * 0.0002  # Maker fee for TP
                        net_pnl = gross_pnl - fee
                        
                        trades.append({
                            'symbol': self.symbol,
                            'type': 'TP',
                            'level': tp_name,
                            'price': tp_price,
                            'qty': close_qty,
                            'gross_pnl': gross_pnl,
                            'fee': fee,
                            'pnl': net_pnl
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

        # 4. Check Trailing Stop (TP6) - AFTER TP checks
        if self.tp1_triggered and self.remaining_qty > 0.0001:
            new_trailing = self.highest_price - (current_atr * self.trailing_atr_mult)
            if new_trailing > self.trailing_stop_price:
                self.trailing_stop_price = new_trailing
            
            # If trailing stop hit
            if bar['low'] <= self.trailing_stop_price:
                return self.close_position(self.trailing_stop_price, 'TRAILING_STOP', self.remaining_qty, trades, fee_rate=0.0005)

        return trades

    def close_position(self, price: float, reason: str, qty: float, trades: list, fee_rate: float = 0.0005):
        """Close position, calculate PnL and fee. Returns trades list."""
        gross_pnl = (price - self.entry_price) * qty
        notional = price * qty
        fee = notional * fee_rate
        net_pnl = gross_pnl - fee
        
        trades.append({
            'symbol': self.symbol,
            'type': 'EXIT',
            'level': reason,
            'price': price,
            'qty': qty,
            'gross_pnl': gross_pnl,
            'fee': fee,
            'pnl': net_pnl
        })
        self.remaining_qty = 0
        return trades


class S002Engine:
    """
    Main Backtest Engine v2.2.
    Fixes: Balance tracking, Fee model, TP/Trailing order.
    """
    def __init__(self, config: dict):
        self.config = config
        self.positions: list[S002Position] = []
        self.pending_orders = [] 
        self.balance = 10000.0
        self.initial_balance = 10000.0
        self.trades_log = []
        self.max_concurrent_positions = config.get('max_concurrent_positions', 3)
        
        # Fee model: taker 0.05%, maker 0.02%
        self.taker_fee = config.get('taker_fee', 0.0005)
        self.maker_fee = config.get('maker_fee', 0.0002)
        
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
                if pos.remaining_qty > 0 and not pd.isna(pos.remaining_qty):
                    trades = pos.update(bar, current_atr)
                    for t in trades:
                        if pd.isna(t.get('qty')) or pd.isna(t.get('price')):
                            continue
                        if t['type'] == 'EXIT' or t['type'] == 'TP':
                            # EXIT/TP: add proceeds back to balance (PnL is just stats)
                            # Net proceeds = qty * exit_price - fee
                            proceeds = t['qty'] * t['price']
                            fee = t.get('fee', 0)
                            if not pd.isna(proceeds) and not pd.isna(fee):
                                self.balance += (proceeds - fee)
                        elif t['type'] == 'LIMIT_FILL':
                            # Limit fill: deduct cost from balance
                            fill_cost = t['qty'] * t['price']
                            if not pd.isna(fill_cost):
                                self.balance -= fill_cost  # Fee already deducted in close_position
                    self.trades_log.extend(trades)
                    
                    if pos.remaining_qty > 0.0001 and not pd.isna(pos.remaining_qty):
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

    def open_hybrid_position(self, signal: dict, entry_time: pd.Timestamp, symbol: str = "BTC/USDT"):
        entry_price = signal['entry_price']
        
        # Validate balance
        if pd.isna(self.balance) or self.balance <= 0:
            print(f"[{entry_time}] ERROR: Invalid balance {self.balance}, skipping signal")
            return
        
        # Risk calc based on CURRENT balance (updates as trades close)
        risk_amount = self.balance * self.config['risk_per_trade']
        risk_distance = signal['risk_distance']
        
        # Validate risk distance
        if risk_distance <= 0 or pd.isna(risk_distance):
            print(f"[{entry_time}] ERROR: Invalid risk_distance {risk_distance}")
            return
        
        total_qty = risk_amount / risk_distance
        
        # Sanity check on position size - use absolute dollar limit
        max_position_value = self.balance * 1.0  # Max 1x balance per position
        position_value = total_qty * entry_price
        
        if total_qty <= 0 or pd.isna(total_qty) or position_value > max_position_value:
            # Skip if position too large
            return
        
        # Also check risk_distance is reasonable (at least 0.5% of price)
        min_risk_distance = entry_price * 0.005
        if risk_distance < min_risk_distance:
            return
        
        # v2.2: 50/50 Split
        instant_qty = total_qty * 0.50
        limit_qty = total_qty * 0.50
        
        # Deduct initial margin from balance (fee is separate)
        initial_cost = instant_qty * entry_price
        self.balance -= initial_cost
        
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
            'price': entry_price, 'qty': instant_qty, 'pnl': 0,
            'fee': instant_qty * entry_price * self.taker_fee
        })
        
        # Place Pending Limit Order
        self.pending_orders.append({
            'pos_id': pos.id, 'limit_price': signal['limit_price'],
            'unfilled_qty': limit_qty, 'age': 0
        })
        
        entry_fee = instant_qty * entry_price * self.taker_fee
        print(f"[{entry_time}] SIGNAL: Entry @ {entry_price:.2f}, SL @ {signal['sl_price']:.2f}")
        print(f"           Instant 50% ({instant_qty:.4f}), Limit 50% @ {signal['limit_price']:.2f}")
        print(f"           Balance after entry: {self.balance:.2f} (fee: {entry_fee:.2f})")
