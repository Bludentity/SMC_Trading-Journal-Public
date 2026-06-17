"""Database layer: SQLAlchemy Core, dual DB routing (Postgres if DATABASE_URL, else local SQLite).

- Loads .env automatically via python-dotenv
- Ensures sslmode=require appended for Postgres if missing
- Uses SQLAlchemy Core to avoid param marker differences
"""
import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv
import pytz

from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, String, Text, Float, select, insert, update, delete
)
from sqlalchemy.exc import OperationalError, IntegrityError

# Load local .env if present
load_dotenv()

EAT = pytz.timezone("Africa/Nairobi")

DEFAULT_PAIRS = ["XAUUSD", "EURUSD"]
DEFAULT_TIMEFRAMES = ["1D", "4H", "30M", "15M"]
DEFAULT_MODULES = [
    "[Bullish] Inducement Sweep (Liquidity Taken Below)",
    "[Bearish] Inducement Sweep (Liquidity Taken Above)",
    "[Bullish] Engineering Liquidity Sweep (Lows)",
    "[Bearish] Engineering Liquidity Sweep (Highs)",
    "Decisional Order Block (OB) Mitigation",
    "Decisional Order Flow (OF) Mitigation",
    "Extreme Order Block (OB) Mitigation",
    "Extreme Order Flow (OF) Mitigation",
    "Origin Order Block (OB) Mitigation",
    "Bullish Fair Value Gap (bFVG)",
    "Bearish Fair Value Gap (bFVG)",
    "Fibonacci Optimal Entry Zone (0.5 - 0.62)",
]
DEFAULT_LEVELS = [
    "Upper Limit",
    "Lower Limit",
    "Mean Threshold / Middle Limit",
    "0.5 Fibonacci Level",
    "0.62 Fibonacci Level",
    "Fib Mid-Threshold",
]

_METADATA = MetaData()
_ENGINE = None


def _append_sslmode_if_needed(url: str) -> str:
    if not url:
        return url
    low = url.lower()
    if ("postgres" in low or "postgresql" in low) and "sslmode" not in low:
        return url + ("&sslmode=require" if "?" in url else "?sslmode=require")
    return url


def _get_engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE

    db_url = os.environ.get("DATABASE_URL")
    # If running as a frozen exe, allow .env next to exe
    if getattr(sys, 'frozen', False):
        dot = os.path.join(os.path.dirname(sys.executable), '.env')
        if os.path.exists(dot):
            load_dotenv(dot)
            db_url = os.environ.get('DATABASE_URL')

    try:
        if db_url:
            db_url = _append_sslmode_if_needed(db_url)
            eng = create_engine(db_url, pool_pre_ping=True)
            # quick smoke test
            with eng.connect() as c:
                pass
            _ENGINE = eng
            return _ENGINE
    except OperationalError:
        # connection failed; fall back to sqlite
        pass

    # Local sqlite fallback (in cwd or next to exe when frozen)
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.getcwd()
    sqlite_path = os.path.join(base, 'smc_backtest.db')
    eng = create_engine(f"sqlite:///{sqlite_path}", connect_args={"check_same_thread": False})
    _ENGINE = eng
    return _ENGINE


# Table definitions
pairs = Table('pairs', _METADATA, Column('pair_name', String, primary_key=True))

timeframes = Table('timeframes', _METADATA, Column('tf_name', String, primary_key=True))

entry_modules = Table('entry_modules', _METADATA,
                      Column('id', Integer, primary_key=True, autoincrement=True),
                      Column('module_name', String, unique=True, nullable=False))

reversal_levels = Table('reversal_levels', _METADATA,
                        Column('id', Integer, primary_key=True, autoincrement=True),
                        Column('level_name', String, unique=True, nullable=False))

trades = Table('trades', _METADATA,
               Column('id', Integer, primary_key=True, autoincrement=True),
               Column('pair', String, nullable=False),
               Column('timeframe', String, nullable=False),
               Column('direction', String, nullable=False),
               Column('session', String),
               Column('execution_time_eat', String, nullable=False),
               Column('entry_modules', Text, nullable=False),
               Column('dynamic_entry_zones', Text),
               Column('actual_reversal_zone', Text),
               Column('actual_reversal_custom', Text),
               Column('reversal_level', Text),
               Column('outcome', String, nullable=False),
               Column('exact_entry_price', Float),
               Column('exact_sl_price', Float),
               Column('exact_tp_price', Float),
               Column('planned_sl_pips', Float, nullable=False),
               Column('planned_tp_pips', Float, nullable=False),
               Column('planned_rr', Float, nullable=False),
               Column('net_r', Float, nullable=False),
               Column('actual_mae_pips', Float),
               Column('actual_mfe_pips', Float),
               Column('sl_placement_desc', Text),
               Column('tp_placement_desc', Text),
               Column('entry_reversal_notes', Text),
               Column('notes', Text),
               Column('created_at', String, nullable=False),
               )

webhook_queue = Table('webhook_queue', _METADATA,
                      Column('id', Integer, primary_key=True, autoincrement=True),
                      Column('payload', Text, nullable=False),
                      Column('received_at', String, nullable=False),
                      Column('status', String, nullable=False, default='pending'))


def init_db():
    eng = _get_engine()
    _METADATA.create_all(eng)

    # seeds
    with eng.connect() as conn:
        for p in DEFAULT_PAIRS:
            try:
                conn.execute(insert(pairs).values(pair_name=p))
            except IntegrityError:
                pass
        for t in DEFAULT_TIMEFRAMES:
            try:
                conn.execute(insert(timeframes).values(tf_name=t))
            except IntegrityError:
                pass
        for m in DEFAULT_MODULES:
            try:
                conn.execute(insert(entry_modules).values(module_name=m))
            except IntegrityError:
                pass
        for lv in DEFAULT_LEVELS:
            try:
                conn.execute(insert(reversal_levels).values(level_name=lv))
            except IntegrityError:
                pass


# Utility
def now_eat_str():
    return datetime.now(EAT).strftime("%Y-%m-%d %H:%M:%S")


def compute_net_r(outcome, planned_rr):
    try:
        planned_rr = float(planned_rr)
    except Exception:
        planned_rr = 0.0
    if outcome == 'Win':
        return float(planned_rr)
    if outcome == 'Loss':
        return -1.0
    return 0.0


# Settings: pairs/timeframes/modules/levels
def get_pairs():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(pairs.c.pair_name).order_by(pairs.c.pair_name)).fetchall()
        return [r[0] for r in rows]


def add_pair(name):
    name = name.strip().upper()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(pairs).values(pair_name=name))
        except IntegrityError:
            pass
    return name


def delete_pair(name):
    eng = _get_engine()
    with eng.begin() as conn:
        r = conn.execute(select(trades.c.id).where(trades.c.pair == name).limit(1)).fetchone()
        if r:
            return False, 'Pair is referenced by existing trades and cannot be deleted.'
        conn.execute(delete(pairs).where(pairs.c.pair_name == name))
    return True, None


def get_timeframes():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(timeframes.c.tf_name).order_by(timeframes.c.tf_name)).fetchall()
        return [r[0] for r in rows]


def add_timeframe(name):
    name = name.strip().upper()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(timeframes).values(tf_name=name))
        except IntegrityError:
            pass
    return name


def delete_timeframe(name):
    eng = _get_engine()
    with eng.begin() as conn:
        r = conn.execute(select(trades.c.id).where(trades.c.timeframe == name).limit(1)).fetchone()
        if r:
            return False, 'Timeframe is referenced by existing trades and cannot be deleted.'
        conn.execute(delete(timeframes).where(timeframes.c.tf_name == name))
    return True, None


def get_entry_modules():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(entry_modules.c.id, entry_modules.c.module_name).order_by(entry_modules.c.id)).fetchall()
        return [dict(id=r[0], module_name=r[1]) for r in rows]


def add_entry_module(name):
    name = name.strip()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(entry_modules).values(module_name=name))
        except IntegrityError:
            pass
    return name


def delete_entry_module(module_id):
    eng = _get_engine()
    with eng.begin() as conn:
        row = conn.execute(select(entry_modules.c.module_name).where(entry_modules.c.id == module_id)).fetchone()
        if not row:
            return False, 'Module not found.'
        modname = row[0]
        rows = conn.execute(select(trades.c.entry_modules)).fetchall()
        for t in rows:
            try:
                if modname in json.loads(t[0] or '[]'):
                    return False, 'Module is referenced by existing trades and cannot be deleted.'
            except Exception:
                pass
        conn.execute(delete(entry_modules).where(entry_modules.c.id == module_id))
    return True, None


def get_reversal_levels():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(reversal_levels.c.id, reversal_levels.c.level_name).order_by(reversal_levels.c.id)).fetchall()
        return [dict(id=r[0], level_name=r[1]) for r in rows]


def add_reversal_level(name):
    name = name.strip()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(reversal_levels).values(level_name=name))
        except IntegrityError:
            pass
    return name


def delete_reversal_level(level_id):
    eng = _get_engine()
    with eng.begin() as conn:
        row = conn.execute(select(reversal_levels.c.level_name).where(reversal_levels.c.id == level_id)).fetchone()
        if not row:
            return False, 'Level not found.'
        conn.execute(delete(reversal_levels).where(reversal_levels.c.id == level_id))
    return True, None


# Trades
def insert_trade(data):
    modules = json.dumps(data['entry_modules']) if isinstance(data['entry_modules'], list) else data['entry_modules']
    zones = json.dumps(data.get('dynamic_entry_zones')) if isinstance(data.get('dynamic_entry_zones'), dict) else (data.get('dynamic_entry_zones') or '{}')
    net_r = compute_net_r(data['outcome'], data['planned_rr'])
    eat_time = data.get('execution_time') or now_eat_str()

    def _f(key):
        v = data.get(key)
        try:
            return float(v) if v not in (None, '') else None
        except Exception:
            return None

    eng = _get_engine()
    with eng.begin() as conn:
        res = conn.execute(insert(trades).values(
            pair=data['pair'].upper(),
            timeframe=data['timeframe'],
            direction=data['direction'],
            session=data.get('session') or None,
            execution_time_eat=eat_time,
            entry_modules=modules,
            dynamic_entry_zones=zones,
            actual_reversal_zone=data.get('actual_reversal_zone') or None,
            actual_reversal_custom=data.get('actual_reversal_custom') or None,
            outcome=data['outcome'],
            exact_entry_price=_f('exact_entry_price'),
            exact_sl_price=_f('exact_sl_price'),
            exact_tp_price=_f('exact_tp_price'),
            planned_sl_pips=float(data['planned_sl_pips']),
            planned_tp_pips=float(data['planned_tp_pips']),
            planned_rr=float(data['planned_rr']),
            net_r=net_r,
            actual_mae_pips=_f('actual_mae_pips'),
            actual_mfe_pips=_f('actual_mfe_pips'),
            sl_placement_desc=data.get('sl_placement_desc') or None,
            tp_placement_desc=data.get('tp_placement_desc') or None,
            entry_reversal_notes=data.get('entry_reversal_notes') or None,
            notes=data.get('notes') or None,
            created_at=now_eat_str(),
        ))
        try:
            return int(res.inserted_primary_key[0])
        except Exception:
            return None


def get_all_trades():
    eng = _get_engine()
    with eng.connect() as conn:
        res = conn.execute(select(trades).order_by(trades.c.id.desc())).fetchall()
        out = []
        for r in res:
            out.append(dict(r._mapping))
        return out


def get_trade(trade_id):
    eng = _get_engine()
    with eng.connect() as conn:
        row = conn.execute(select(trades).where(trades.c.id == trade_id)).fetchone()
        return dict(row._mapping) if row else None


def delete_trade(trade_id):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(delete(trades).where(trades.c.id == trade_id))


# Webhook queue
def queue_webhook(payload_str):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(insert(webhook_queue).values(payload=payload_str, received_at=now_eat_str(), status='pending'))


def get_pending_webhooks():
    eng = _get_engine()
    with eng.connect() as conn:
        res = conn.execute(select(webhook_queue).where(webhook_queue.c.status == 'pending').order_by(webhook_queue.c.id.desc())).fetchall()
        return [dict(r._mapping) for r in res]


def dismiss_webhook(wid):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(update(webhook_queue).where(webhook_queue.c.id == wid).values(status='dismissed'))


# CSV import & AI export utilities
IMPORT_PLACEHOLDER_MODULE = "Imported (Pending SMC Review)"
IMPORT_PLACEHOLDER_LEVEL = "Imported (Pending SMC Review)"
IMPORT_PLACEHOLDER_SESSION = "London"
IMPORT_PLACEHOLDER_TF = "IMPORT"


def _clean(val):
    if val is None:
        return ""
    return val.strip().replace("\ufeff", "").strip()


def _clean_num(val):
    if val is None:
        return ""
    return str(val).strip().replace(",", "").replace("$", "").replace("%", "").replace("\ufeff", "").strip()


def _parse_float(val, default=0.0):
    try:
        return float(_clean_num(str(val)))
    except (ValueError, TypeError):
        return default


def _to_eat(dt_str):
    dt_str = _clean(dt_str)
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"]:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return pytz.utc.localize(dt).astimezone(EAT).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
    return now_eat_str()


def _get_col(row, key, default=""):
    key_low = key.strip().lower()
    for k, v in row.items():
        if k.strip().lower() == key_low:
            return v if v is not None else default
    return default


def _ensure_import_placeholders():
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(entry_modules).values(module_name=IMPORT_PLACEHOLDER_MODULE))
        except IntegrityError:
            pass
        try:
            conn.execute(insert(reversal_levels).values(level_name=IMPORT_PLACEHOLDER_LEVEL))
        except IntegrityError:
            pass
        try:
            conn.execute(insert(timeframes).values(tf_name=IMPORT_PLACEHOLDER_TF))
        except IntegrityError:
            pass


def _trade_exists(conn, pair, direction, eat_time):
    r = conn.execute(select(trades.c.id).where(
        (trades.c.pair == pair) & (trades.c.direction == direction) & (trades.c.execution_time_eat == eat_time)
    ).limit(1)).fetchone()
    return r is not None


def _detect_format(headers):
    h = [x.strip().lower() for x in headers]
    if any("trade #" in x or "trade#" in x for x in h):
        return "strategy"
    if "side" in h and "fill price" in h:
        return "replay"
    return "unknown"


def _parse_strategy(rows):
    groups = {}
    for row in rows:
        for k in row:
            if "trade" in k.lower() and ("#" in k or "num" in k.lower()):
                groups.setdefault(_clean(row[k]), []).append(row)
                break

    trades_out = []
    for num, group_rows in groups.items():
        entry_row = next((r for r in group_rows if "entry" in _get_col(r, "type", "").lower()), None)
        exit_row = next((r for r in group_rows if "exit" in _get_col(r, "type", "").lower()), None)
        if not entry_row:
            continue

        direction = "Bullish" if "long" in _get_col(entry_row, "type", "").lower() else "Bearish"
        pair = _get_col(entry_row, "symbol", "UNKNOWN").strip().split(".")[0].upper() or "UNKNOWN"
        eat_time = _to_eat(
            _get_col(entry_row, "date/time", "") or
            _get_col(entry_row, "datetime", "") or
            _get_col(entry_row, "time", "")
        )

        entry_px = _parse_float(_get_col(entry_row, "price", "0"))
        exit_px = _parse_float(_get_col(exit_row, "price", "0")) if exit_row else None
        contracts = _parse_float(_get_col(entry_row, "contracts", "1"), 1.0)

        mfe = abs(_parse_float(_get_col(exit_row or entry_row, "run-up", "0")))
        mae = abs(_parse_float(_get_col(exit_row or entry_row, "drawdown", "0")))

        profit = _parse_float(_get_col(exit_row or entry_row, "profit", "0"))
        prof_pct = _parse_float(
            _get_col(exit_row or entry_row, "profit %", None) or
            _get_col(exit_row or entry_row, "profit(%)", "0")
        )

        outcome = "Win" if profit > 0 else ("Loss" if profit < 0 else "Break-Even")
        planned_rr = round(abs(prof_pct) / 100, 4) if prof_pct != 0 else round(abs(profit), 2)
        net_r = compute_net_r(outcome, planned_rr)

        trades_out.append({
            "pair": pair, "direction": direction, "eat_time": eat_time,
            "entry_px": entry_px,
            "exact_sl_px": exit_px if outcome == "Loss" else None,
            "exact_tp_px": exit_px if outcome == "Win" else None,
            "outcome": outcome, "planned_rr": planned_rr, "net_r": net_r,
            "mae": mae if mae > 0 else None,
            "mfe": mfe if mfe > 0 else None,
            "notes": (
                f"TV Strategy Import | Entry: {entry_px} | Exit: {exit_px} | "
                f"Contracts: {contracts} | Profit: {profit} | Profit%: {prof_pct}"
            ),
        })
    return trades_out


def _parse_replay(rows):
    from collections import defaultdict
    open_positions = defaultdict(list)
    trades_out = []

    for row in rows:
        side = _clean(_get_col(row, "side", "")).lower()
        symbol = _get_col(row, "symbol", "UNKNOWN").strip().split(".")[0].upper()
        qty = _parse_float(_get_col(row, "qty", "1"), 1.0)
        price = _parse_float(_get_col(row, "fill price", "0"))
        pnl = _parse_float(_get_col(row, "p&l", None) or _get_col(row, "pnl", "0"))
        eat_t = _to_eat(_get_col(row, "time", "") or _get_col(row, "date/time", ""))

        if side in ("buy", "long"):
            open_positions[symbol].append({"price": price, "qty": qty, "time": eat_t})

        elif side in ("sell", "short") and open_positions[symbol]:
            entry = open_positions[symbol].pop(0)
            profit_pts = price - entry["price"]
            effective = pnl if pnl != 0 else profit_pts
            outcome = "Win" if effective > 0 else ("Loss" if effective < 0 else "Break-Even")
            rr = round(abs(profit_pts / max(entry["price"] * 0.001, 0.0001)), 4)

            trades_out.append({
                "pair": symbol, "direction": "Bullish",
                "eat_time": entry["time"],
                "entry_px": entry["price"],
                "exact_sl_px": price if outcome == "Loss" else None,
                "exact_tp_px": price if outcome == "Win" else None,
                "outcome": outcome, "planned_rr": rr, "net_r": compute_net_r(outcome, rr),
                "mae": None, "mfe": None,
                "notes": (
                    f"TV Replay Import | Entry: {entry['price']} | Exit: {price} | "
                    f"Qty: {qty} | P&L: {pnl}"
                ),
            })
    return trades_out


def import_tradingview_csv(content):
    import csv, io
    _ensure_import_placeholders()
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return 0, 0, ["CSV file is empty or unreadable."]

    fmt = _detect_format(reader.fieldnames or [])
    if fmt == "strategy":
        parsed = _parse_strategy(rows)
    elif fmt == "replay":
        parsed = _parse_replay(rows)
    else:
        return 0, 0, ["Unrecognised CSV format. Expected Strategy Tester or Replay Trading export."]

    inserted, skipped, errors = 0, 0, []
    eng = _get_engine()
    with eng.begin() as conn:
        for t in parsed:
            conn.execute(insert(pairs).values(pair_name=t['pair']))
            if _trade_exists(conn, t['pair'], t['direction'], t['eat_time']):
                skipped += 1
                continue
            try:
                conn.execute(insert(trades).values(
                    pair=t['pair'],
                    timeframe=IMPORT_PLACEHOLDER_TF,
                    direction=t['direction'],
                    session=IMPORT_PLACEHOLDER_SESSION,
                    execution_time_eat=t['eat_time'],
                    entry_modules=json.dumps([IMPORT_PLACEHOLDER_MODULE]),
                    dynamic_entry_zones='{}',
                    actual_reversal_zone=None,
                    actual_reversal_custom=None,
                    outcome=t['outcome'],
                    exact_entry_price=t.get('entry_px'),
                    exact_sl_price=t.get('exact_sl_px'),
                    exact_tp_price=t.get('exact_tp_px'),
                    planned_sl_pips=0.0,
                    planned_tp_pips=0.0,
                    planned_rr=t['planned_rr'],
                    net_r=t['net_r'],
                    actual_mae_pips=t.get('mae'),
                    actual_mfe_pips=t.get('mfe'),
                    sl_placement_desc=None,
                    tp_placement_desc=None,
                    entry_reversal_notes=None,
                    notes=t.get('notes'),
                    created_at=now_eat_str(),
                ))
                inserted += 1
            except Exception as e:
                errors.append(str(e))
    return inserted, skipped, errors


AI_DICT_HEADER = """[AI DATA DICTIONARY HEADER START]
This dataset contains advanced, professional backtesting trade execution logs utilizing Smart Money Concepts (SMC) and institutional order flow mechanics. Use this exact schema definition dictionary to parse, model, and analyze the data records below:

PRIMARY STRUCTURAL ENTITIES & FIELD LOGIC:
- 'Trade_ID': A unique, auto-incremented integer identifying the trade chronicle index.
- 'Asset_Pair': The financial asset ticker being backtested (e.g., XAUUSD, EURUSD), dynamic from settings configuration.
- 'Timeframe': The precise execution or directional bias chart timeframe (e.g., 4H, 15M, 1M).
- 'Direction': The order framework style. Restricted to 'BUY' (Long market positions) or 'SELL' (Short market positions).
- 'Trading_Session': The specific regional market liquidity block when entry was activated ('Asian', 'London', 'New York').
- 'Execution_Time_EAT': The explicit execution timestamp hardcoded and normalized to East African Time (EAT / UTC+3).
- 'SMC_Entry_Modules': A multi-selected array of mechanical execution criteria checked by the trader to justify entry validation (e.g., [Decisional OB, Inducement Sweep]).
- 'Dynamic_Entry_Zones': A breakdown mapping out exactly where the trader entered relative to each checked Entry Module (e.g., Entering at the 'Upper Limit' of the Decisional OB while simultaneously hitting the 'Mean Threshold' of the Extreme OF).
- 'Actual_Reversal_Zone': The true, physical structural landmark where the market exhausted its price expansion/drawdown and printed its real pivot point before moving toward targets. Compare this directly to 'Dynamic_Entry_Zones' to study structural front-running, drawdown overextensions, and zone failures.
- 'Exact_Entry_Price': The literal float execution entry rate digit. Used to cross-reference if the trade interacted with institutional whole numbers, key psychological round figures (.000, .500), or institutional quarters (.250, .750).
- 'Exact_Stop_Loss_Price': The exact protective invalidation price point.
- 'Exact_Take_Profit_Price': The exact planned objective target price point.
- 'Planned_SL_Pips': The total calculated mathematical pip distance from entry to stop loss.
- 'Planned_TP_Pips': The total calculated mathematical pip distance from entry to take profit.
- 'Planned_RR_Ratio': The raw calculated risk-to-reward ratio metric planned prior to execution (e.g., 1:4.5).
- 'Trade_Outcome': The definitive manual resolution of the position. Restricted to 'Win', 'Loss', or 'Break-Even'.
- 'Net_R_Gain_Loss': The automated statistical performance return value based strictly on outcome (A 'Loss' = -1.0R, 'Break-Even' = 0.0R, 'Win' = full positive Planned_RR value).
- 'Max_Adverse_Excursion_MAE': The maximum drawdown in pips experienced during the life of the trade. Mandatory for wins to evaluate entry optimization.
- 'Max_Favorable_Excursion_MFE': The maximum profit expansion in pips reached before invalidation. Mandatory for losses to analyze exit greed optimization.
- 'SL_Placement_Desc': Qualitative structural explanation outlining the logic of where the protective order was positioned.
- 'TP_Placement_Desc': Qualitative structural explanation outlining the logic of where the target objective was positioned.
- 'Entry_Reversal_Notes': Tape-reading observations made in real-time regarding candle signatures, reaction momentum, or zone mitigation nuances exactly during the entry window.
- 'Final_Outcome_Notes': Macro retrospective comments logging psychology, mistakes, or key takeaways after the trade fully resolved.

Analyze these records globally to extract edge patterns, structural performance anomalies, structural placement safety margins, and win-rate optimizations based on these descriptions.
[AI DATA DICTIONARY HEADER END]

---
[RAW DATA RECORDS FOLLOW]
"""


def generate_ai_export():
    trades_all = get_all_trades()
    if not trades_all:
        return "No trades recorded yet."

    records = []
    for t in reversed(trades_all):
        try:
            modules = json.loads(t.get('entry_modules') or '[]')
        except Exception:
            modules = []
        modules_str = ", ".join(modules) if modules else "N/A"

        try:
            zones_raw = json.loads(t.get('dynamic_entry_zones') or '{}')
            zones_str = "; ".join([f"{mod}: {lvl}" for mod, lvl in zones_raw.items() if lvl and lvl != 'N/A']) or 'N/A'
        except Exception:
            zones_str = 'N/A'

        reversal = t.get('actual_reversal_custom') or t.get('actual_reversal_zone') or 'N/A'

        eat_display = t.get('execution_time_eat') or 'N/A'
        if isinstance(eat_display, str) and len(eat_display) > 8:
            try:
                eat_display = datetime.strptime(eat_display, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M EAT")
            except Exception:
                pass

        def _v(key, default='N/A'):
            val = t.get(key)
            return str(val) if val is not None else default

        records.append(
            f"RECORD_{t['id']}: "
            f"ID: {t['id']} | Pair: {t['pair']} | TF: {t['timeframe']} | Dir: {t['direction']} | "
            f"Session: {t.get('session') or 'N/A'} | Time: {eat_display} | "
            f"Modules: [{modules_str}] | Entry_Zones: [{zones_str}] | "
            f"Reversal_Zone: {reversal} | "
            f"Entry_Px: {_v('exact_entry_price')} | SL_Px: {_v('exact_sl_price')} | TP_Px: {_v('exact_tp_price')} | "
            f"P_SL: {_v('planned_sl_pips')} | P_TP: {_v('planned_tp_pips')} | P_RR: {_v('planned_rr')} | "
            f"Outcome: {t['outcome']} | Net_R: {t['net_r']} | "
            f"MAE: {_v('actual_mae_pips')} | MFE: {_v('actual_mfe_pips')} | "
            f"SL_Desc: {_v('sl_placement_desc')} | TP_Desc: {_v('tp_placement_desc')} | "
            f"Entry_Notes: {_v('entry_reversal_notes')} | Final_Notes: {_v('notes')}"
        )

    return AI_DICT_HEADER + "\n".join(records) + "\n\n[DATASET RECORD END]\n---"
"""
SQLAlchemy-based database layer with dual-database routing.
- Uses DATABASE_URL (Postgres) when present; else falls back to local SQLite file.
- Automatically appends sslmode=require to Postgres URL if missing.
- Exposes functions used by the Flask app for CRUD and CSV import.
"""
import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv
import pytz

from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, String, Text, Float, select, insert, update, delete
)
from sqlalchemy.exc import OperationalError, IntegrityError


load_dotenv()

EAT = pytz.timezone("Africa/Nairobi")

# Seeds
DEFAULT_PAIRS = ["XAUUSD", "EURUSD"]
DEFAULT_TIMEFRAMES = ["1D", "4H", "30M", "15M"]
DEFAULT_MODULES = [
    "[Bullish] Inducement Sweep (Liquidity Taken Below)",
    "[Bearish] Inducement Sweep (Liquidity Taken Above)",
    "[Bullish] Engineering Liquidity Sweep (Lows)",
    "[Bearish] Engineering Liquidity Sweep (Highs)",
    "Decisional Order Block (OB) Mitigation",
    "Decisional Order Flow (OF) Mitigation",
    "Extreme Order Block (OB) Mitigation",
    "Extreme Order Flow (OF) Mitigation",
    "Origin Order Block (OB) Mitigation",
    "Bullish Fair Value Gap (bFVG)",
    "Bearish Fair Value Gap (bFVG)",
    "Fibonacci Optimal Entry Zone (0.5 - 0.62)",
]
DEFAULT_LEVELS = [
    "Upper Limit",
    "Lower Limit",
    "Mean Threshold / Middle Limit",
    "0.5 Fibonacci Level",
    "0.62 Fibonacci Level",
    "Fib Mid-Threshold",
]


_ENGINE = None
_META = MetaData()


def _ensure_postgres_ssl(url: str) -> str:
    low = url.lower()
    if ("postgres" in low or "postgresql" in low) and "sslmode" not in low:
        sep = '&' if '?' in url else '?'
        return url + sep + 'sslmode=require'
    return url


def _get_engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE

    db_url = os.environ.get('DATABASE_URL')
    # if an env file is placed next to a frozen exe, load it
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        env_path = os.path.join(exe_dir, '.env')
        if os.path.exists(env_path):
            load_dotenv(env_path)
            db_url = os.environ.get('DATABASE_URL')

    try:
        if db_url:
            db_url = _ensure_postgres_ssl(db_url)
            engine = create_engine(db_url, pool_pre_ping=True)
            # quick smoke test
            with engine.connect() as conn:
                pass
            _ENGINE = engine
            return _ENGINE
    except OperationalError:
        # fallback to sqlite
        pass

    # SQLite fallback: place DB in cwd (or next to exe when frozen)
    base = os.getcwd()
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    sqlite_path = os.path.join(base, 'smc_backtest.db')
    engine = create_engine(f'sqlite:///{sqlite_path}', connect_args={"check_same_thread": False})
    _ENGINE = engine
    return _ENGINE


# Table definitions
pairs = Table('pairs', _META,
              Column('pair_name', String, primary_key=True))

timeframes = Table('timeframes', _META,
                   Column('tf_name', String, primary_key=True))

entry_modules = Table('entry_modules', _META,
                      Column('id', Integer, primary_key=True, autoincrement=True),
                      Column('module_name', String, unique=True, nullable=False))

reversal_levels = Table('reversal_levels', _META,
                        Column('id', Integer, primary_key=True, autoincrement=True),
                        Column('level_name', String, unique=True, nullable=False))

trades = Table('trades', _META,
               Column('id', Integer, primary_key=True, autoincrement=True),
               Column('pair', String, nullable=False),
               Column('timeframe', String, nullable=False),
               Column('direction', String, nullable=False),
               Column('session', String),
               Column('execution_time_eat', String, nullable=False),
               Column('entry_modules', Text, nullable=False),
               Column('dynamic_entry_zones', Text),
               Column('actual_reversal_zone', Text),
               Column('actual_reversal_custom', Text),
               Column('reversal_level', Text),
               Column('outcome', String, nullable=False),
               Column('exact_entry_price', Float),
               Column('exact_sl_price', Float),
               Column('exact_tp_price', Float),
               Column('planned_sl_pips', Float, nullable=False),
               Column('planned_tp_pips', Float, nullable=False),
               Column('planned_rr', Float, nullable=False),
               Column('net_r', Float, nullable=False),
               Column('actual_mae_pips', Float),
               Column('actual_mfe_pips', Float),
               Column('sl_placement_desc', Text),
               Column('tp_placement_desc', Text),
               Column('entry_reversal_notes', Text),
               Column('notes', Text),
               Column('created_at', String, nullable=False)
               )

webhook_queue = Table('webhook_queue', _META,
                      Column('id', Integer, primary_key=True, autoincrement=True),
                      Column('payload', Text, nullable=False),
                      Column('received_at', String, nullable=False),
                      Column('status', String, nullable=False, default='pending'))


def init_db():
    eng = _get_engine()
    _META.create_all(eng)

    # seed
    with eng.begin() as conn:
        for p in DEFAULT_PAIRS:
            try:
                conn.execute(insert(pairs).values(pair_name=p))
            except IntegrityError:
                pass
        for t in DEFAULT_TIMEFRAMES:
            try:
                conn.execute(insert(timeframes).values(tf_name=t))
            except IntegrityError:
                pass
        for m in DEFAULT_MODULES:
            try:
                conn.execute(insert(entry_modules).values(module_name=m))
            except IntegrityError:
                pass
        for lv in DEFAULT_LEVELS:
            try:
                conn.execute(insert(reversal_levels).values(level_name=lv))
            except IntegrityError:
                pass


# Utility
def now_eat_str():
    return datetime.now(EAT).strftime('%Y-%m-%d %H:%M:%S')


def compute_net_r(outcome, planned_rr):
    try:
        rr = float(planned_rr)
    except Exception:
        rr = 0.0
    if outcome == 'Win':
        return rr
    if outcome == 'Loss':
        return -1.0
    return 0.0


# Settings: pairs
def get_pairs():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(pairs.c.pair_name).order_by(pairs.c.pair_name)).fetchall()
        return [r[0] for r in rows]


def add_pair(name):
    name = name.strip().upper()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(pairs).values(pair_name=name))
        except IntegrityError:
            pass
    return name


def delete_pair(name):
    eng = _get_engine()
    with eng.connect() as conn:
        r = conn.execute(select(trades.c.id).where(trades.c.pair == name).limit(1)).fetchone()
        if r:
            return False, 'Pair is referenced by existing trades and cannot be deleted.'
        conn.execute(delete(pairs).where(pairs.c.pair_name == name))
    return True, None


# Timeframes
def get_timeframes():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(timeframes.c.tf_name).order_by(timeframes.c.tf_name)).fetchall()
        return [r[0] for r in rows]


def add_timeframe(name):
    name = name.strip().upper()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(timeframes).values(tf_name=name))
        except IntegrityError:
            pass
    return name


def delete_timeframe(name):
    eng = _get_engine()
    with eng.connect() as conn:
        r = conn.execute(select(trades.c.id).where(trades.c.timeframe == name).limit(1)).fetchone()
        if r:
            return False, 'Timeframe is referenced by existing trades and cannot be deleted.'
        conn.execute(delete(timeframes).where(timeframes.c.tf_name == name))
    return True, None


# Entry modules
def get_entry_modules():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(entry_modules.c.id, entry_modules.c.module_name).order_by(entry_modules.c.id)).fetchall()
        return [dict(id=r[0], module_name=r[1]) for r in rows]


def add_entry_module(name):
    name = name.strip()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(entry_modules).values(module_name=name))
        except IntegrityError:
            pass
    return name


def delete_entry_module(module_id):
    eng = _get_engine()
    with eng.connect() as conn:
        row = conn.execute(select(entry_modules.c.module_name).where(entry_modules.c.id == module_id)).fetchone()
        if not row:
            return False, 'Module not found.'
        modname = row[0]
        rows = conn.execute(select(trades.c.entry_modules)).fetchall()
        for t in rows:
            try:
                if modname in json.loads(t[0] or '[]'):
                    return False, 'Module is referenced by existing trades and cannot be deleted.'
            except Exception:
                pass
        conn.execute(delete(entry_modules).where(entry_modules.c.id == module_id))
    return True, None


# Reversal levels
def get_reversal_levels():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(reversal_levels.c.id, reversal_levels.c.level_name).order_by(reversal_levels.c.id)).fetchall()
        return [dict(id=r[0], level_name=r[1]) for r in rows]


def add_reversal_level(name):
    name = name.strip()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(reversal_levels).values(level_name=name))
        except IntegrityError:
            pass
    return name


def delete_reversal_level(level_id):
    eng = _get_engine()
    with eng.connect() as conn:
        row = conn.execute(select(reversal_levels.c.level_name).where(reversal_levels.c.id == level_id)).fetchone()
        if not row:
            return False, 'Level not found.'
        conn.execute(delete(reversal_levels).where(reversal_levels.c.id == level_id))
    return True, None


# Trades
def insert_trade(data):
    modules = json.dumps(data['entry_modules']) if isinstance(data.get('entry_modules'), list) else data.get('entry_modules')
    zones = json.dumps(data.get('dynamic_entry_zones')) if isinstance(data.get('dynamic_entry_zones'), dict) else (data.get('dynamic_entry_zones') or '{}')
    net_r = compute_net_r(data.get('outcome'), data.get('planned_rr'))
    eat_time = data.get('execution_time') or now_eat_str()

    def _f(key):
        v = data.get(key)
        try:
            return float(v) if v not in (None, '') else None
        except Exception:
            return None

    eng = _get_engine()
    with eng.begin() as conn:
        r = conn.execute(insert(trades).values(
            pair=data.get('pair', '').upper(),
            timeframe=data.get('timeframe'),
            direction=data.get('direction'),
            session=data.get('session') or None,
            execution_time_eat=eat_time,
            entry_modules=modules,
            dynamic_entry_zones=zones,
            actual_reversal_zone=data.get('actual_reversal_zone') or None,
            actual_reversal_custom=data.get('actual_reversal_custom') or None,
            outcome=data.get('outcome'),
            exact_entry_price=_f('exact_entry_price'),
            exact_sl_price=_f('exact_sl_price'),
            exact_tp_price=_f('exact_tp_price'),
            planned_sl_pips=float(data.get('planned_sl_pips') or 0.0),
            planned_tp_pips=float(data.get('planned_tp_pips') or 0.0),
            planned_rr=float(data.get('planned_rr') or 0.0),
            net_r=net_r,
            actual_mae_pips=_f('actual_mae_pips'),
            actual_mfe_pips=_f('actual_mfe_pips'),
            sl_placement_desc=data.get('sl_placement_desc') or None,
            tp_placement_desc=data.get('tp_placement_desc') or None,
            entry_reversal_notes=data.get('entry_reversal_notes') or None,
            notes=data.get('notes') or None,
            created_at=now_eat_str(),
        ))
        pk = r.inserted_primary_key
        return int(pk[0]) if pk else None


def get_all_trades():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(trades).order_by(trades.c.id.desc())).fetchall()
        out = []
        for r in rows:
            out.append(dict(r._mapping))
        return out


def get_trade(trade_id):
    eng = _get_engine()
    with eng.connect() as conn:
        row = conn.execute(select(trades).where(trades.c.id == trade_id)).fetchone()
        return dict(row._mapping) if row else None


def delete_trade(trade_id):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(delete(trades).where(trades.c.id == trade_id))


# Webhook queue
def queue_webhook(payload_str):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(insert(webhook_queue).values(payload=payload_str, received_at=now_eat_str(), status='pending'))


def get_pending_webhooks():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(webhook_queue).where(webhook_queue.c.status == 'pending').order_by(webhook_queue.c.id.desc())).fetchall()
        return [dict(r._mapping) for r in rows]


def dismiss_webhook(wid):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(update(webhook_queue).where(webhook_queue.c.id == wid).values(status='dismissed'))


# CSV import helpers (keep earlier parsing logic but use SQLAlchemy for inserts)
IMPORT_PLACEHOLDER_MODULE = 'Imported (Pending SMC Review)'
IMPORT_PLACEHOLDER_LEVEL = 'Imported (Pending SMC Review)'
IMPORT_PLACEHOLDER_SESSION = 'London'
IMPORT_PLACEHOLDER_TF = 'IMPORT'


def _clean(val):
    if val is None:
        return ''
    return str(val).strip().replace('\ufeff', '').strip()


def _clean_num(val):
    if val is None:
        return ''
    return str(val).strip().replace(',', '').replace('$', '').replace('%', '').replace('\ufeff', '').strip()


def _parse_float(val, default=0.0):
    try:
        return float(_clean_num(str(val)))
    except (ValueError, TypeError):
        return default


def _to_eat(dt_str):
    dt_str = _clean(dt_str)
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"]:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return pytz.utc.localize(dt).astimezone(EAT).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
    return now_eat_str()


def _get_col(row, key, default=''):
    key_low = key.strip().lower()
    for k, v in row.items():
        if k.strip().lower() == key_low:
            return v if v is not None else default
    return default


def _ensure_import_placeholders():
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(entry_modules).values(module_name=IMPORT_PLACEHOLDER_MODULE))
        except IntegrityError:
            pass
        try:
            conn.execute(insert(reversal_levels).values(level_name=IMPORT_PLACEHOLDER_LEVEL))
        except IntegrityError:
            pass
        try:
            conn.execute(insert(timeframes).values(tf_name=IMPORT_PLACEHOLDER_TF))
        except IntegrityError:
            pass


def _trade_exists(conn, pair, direction, eat_time):
    r = conn.execute(select(trades.c.id).where(
        (trades.c.pair == pair) & (trades.c.direction == direction) & (trades.c.execution_time_eat == eat_time)
    ).limit(1)).fetchone()
    return r is not None


def _detect_format(headers):
    h = [x.strip().lower() for x in headers]
    if any('trade #' in x or 'trade#' in x for x in h):
        return 'strategy'
    if 'side' in h and 'fill price' in h:
        return 'replay'
    return 'unknown'


def _parse_strategy(rows):
    groups = {}
    for row in rows:
        for k in row:
            if 'trade' in k.lower() and ('#' in k or 'num' in k.lower()):
                groups.setdefault(_clean(row[k]), []).append(row)
                break

    trades_out = []
    for num, group_rows in groups.items():
        entry_row = next((r for r in group_rows if 'entry' in _get_col(r, 'type', '').lower()), None)
        exit_row = next((r for r in group_rows if 'exit' in _get_col(r, 'type', '').lower()), None)
        if not entry_row:
            continue
        direction = 'Bullish' if 'long' in _get_col(entry_row, 'type', '').lower() else 'Bearish'
        pair = _get_col(entry_row, 'symbol', 'UNKNOWN').strip().split('.')[0].upper() or 'UNKNOWN'
        eat_time = _to_eat(_get_col(entry_row, 'date/time', '') or _get_col(entry_row, 'datetime', '') or _get_col(entry_row, 'time', ''))
        entry_px = _parse_float(_get_col(entry_row, 'price', '0'))
        exit_px = _parse_float(_get_col(exit_row, 'price', '0')) if exit_row else None
        contracts = _parse_float(_get_col(entry_row, 'contracts', '1'), 1.0)
        mfe = abs(_parse_float(_get_col(exit_row or entry_row, 'run-up', '0')))
        mae = abs(_parse_float(_get_col(exit_row or entry_row, 'drawdown', '0')))
        profit = _parse_float(_get_col(exit_row or entry_row, 'profit', '0'))
        prof_pct = _parse_float(_get_col(exit_row or entry_row, 'profit %', None) or _get_col(exit_row or entry_row, 'profit(%)', '0'))
        outcome = 'Win' if profit > 0 else ('Loss' if profit < 0 else 'Break-Even')
        planned_rr = round(abs(prof_pct) / 100, 4) if prof_pct != 0 else round(abs(profit), 2)
        net_r = compute_net_r(outcome, planned_rr)
        trades_out.append({
            'pair': pair, 'direction': direction, 'eat_time': eat_time,
            'entry_px': entry_px,
            'exact_sl_px': exit_px if outcome == 'Loss' else None,
            'exact_tp_px': exit_px if outcome == 'Win' else None,
            'outcome': outcome, 'planned_rr': planned_rr, 'net_r': net_r,
            'mae': mae if mae > 0 else None,
            'mfe': mfe if mfe > 0 else None,
            'notes': f"TV Strategy Import | Entry: {entry_px} | Exit: {exit_px} | Contracts: {contracts} | Profit: {profit}"
        })
    return trades_out


def _parse_replay(rows):
    from collections import defaultdict
    open_positions = defaultdict(list)
    trades_out = []
    for row in rows:
        side = _clean(_get_col(row, 'side', '')).lower()
        symbol = _get_col(row, 'symbol', 'UNKNOWN').strip().split('.')[0].upper()
        qty = _parse_float(_get_col(row, 'qty', '1'), 1.0)
        price = _parse_float(_get_col(row, 'fill price', '0'))
        pnl = _parse_float(_get_col(row, 'p&l', None) or _get_col(row, 'pnl', '0'))
        eat_t = _to_eat(_get_col(row, 'time', '') or _get_col(row, 'date/time', ''))
        if side in ('buy', 'long'):
            open_positions[symbol].append({'price': price, 'qty': qty, 'time': eat_t})
        elif side in ('sell', 'short') and open_positions[symbol]:
            entry = open_positions[symbol].pop(0)
            profit_pts = price - entry['price']
            effective = pnl if pnl != 0 else profit_pts
            outcome = 'Win' if effective > 0 else ('Loss' if effective < 0 else 'Break-Even')
            rr = round(abs(profit_pts / max(entry['price'] * 0.001, 0.0001)), 4)
            trades_out.append({
                'pair': symbol, 'direction': 'Bullish',
                'eat_time': entry['time'],
                'entry_px': entry['price'],
                'exact_sl_px': price if outcome == 'Loss' else None,
                'exact_tp_px': price if outcome == 'Win' else None,
                'outcome': outcome, 'planned_rr': rr, 'net_r': compute_net_r(outcome, rr),
                'mae': None, 'mfe': None,
                'notes': f"TV Replay Import | Entry: {entry['price']} | Exit: {price} | Qty: {qty} | P&L: {pnl}"
            })
    return trades_out


def import_tradingview_csv(content):
    import csv, io
    _ensure_import_placeholders()
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return 0, 0, ['CSV file is empty or unreadable.']
    fmt = _detect_format(reader.fieldnames or [])
    if fmt == 'strategy':
        parsed = _parse_strategy(rows)
    elif fmt == 'replay':
        parsed = _parse_replay(rows)
    else:
        return 0, 0, ['Unrecognised CSV format. Expected Strategy Tester or Replay Trading export.']

    inserted = 0
    skipped = 0
    errors = []
    eng = _get_engine()
    with eng.begin() as conn:
        for t in parsed:
            try:
                conn.execute(insert(pairs).values(pair_name=t['pair']))
            except IntegrityError:
                pass
            if _trade_exists(conn, t['pair'], t['direction'], t['eat_time']):
                skipped += 1
                continue
            try:
                conn.execute(insert(trades).values(
                    pair=t['pair'], timeframe=IMPORT_PLACEHOLDER_TF, direction=t['direction'],
                    session=IMPORT_PLACEHOLDER_SESSION, execution_time_eat=t['eat_time'],
                    entry_modules=json.dumps([IMPORT_PLACEHOLDER_MODULE]), dynamic_entry_zones='{}',
                    actual_reversal_zone=None, actual_reversal_custom=None,
                    outcome=t['outcome'], exact_entry_price=t.get('entry_px'),
                    exact_sl_price=t.get('exact_sl_px'), exact_tp_price=t.get('exact_tp_px'),
                    planned_sl_pips=0.0, planned_tp_pips=0.0, planned_rr=t['planned_rr'], net_r=t['net_r'],
                    actual_mae_pips=t.get('mae'), actual_mfe_pips=t.get('mfe'),
                    sl_placement_desc=None, tp_placement_desc=None, entry_reversal_notes=None,
                    notes=t.get('notes'), created_at=now_eat_str()
                ))
                inserted += 1
            except Exception as e:
                errors.append(str(e))
    return inserted, skipped, errors


# AI export
AI_DICT_HEADER = """[AI DATA DICTIONARY HEADER START]\nThis dataset contains advanced, professional backtesting trade execution logs utilizing Smart Money Concepts (SMC) and institutional order flow mechanics. Use this exact schema definition dictionary to parse, model, and analyze the data records below:\n\nPRIMARY STRUCTURAL ENTITIES & FIELD LOGIC:\n- 'Trade_ID': A unique, auto-incremented integer identifying the trade chronicle index.\n- 'Asset_Pair': The financial asset ticker being backtested (e.g., XAUUSD, EURUSD), dynamic from settings configuration.\n- 'Timeframe': The precise execution or directional bias chart timeframe (e.g., 4H, 15M, 1M).\n- 'Direction': The order framework style. Restricted to 'BUY' (Long market positions) or 'SELL' (Short market positions).\n- 'Trading_Session': The specific regional market liquidity block when entry was activated ('Asian', 'London', 'New York').\n- 'Execution_Time_EAT': The explicit execution timestamp hardcoded and normalized to East African Time (EAT / UTC+3).\n- 'SMC_Entry_Modules': A multi-selected array of mechanical execution criteria checked by the trader to justify entry validation (e.g., [Decisional OB, Inducement Sweep]).\n- 'Dynamic_Entry_Zones': A breakdown mapping out exactly where the trader entered relative to each checked Entry Module (e.g., Entering at the 'Upper Limit' of the Decisional OB while simultaneously hitting the 'Mean Threshold' of the Extreme OF).\n- 'Actual_Reversal_Zone': The true, physical structural landmark where the market exhausted its price expansion/drawdown and printed its real pivot point before moving toward targets. Compare this directly to 'Dynamic_Entry_Zones' to study structural front-running, drawdown overextensions, and zone failures.\n- 'Exact_Entry_Price': The literal float execution entry rate digit. Used to cross-reference if the trade interacted with institutional whole numbers, key psychological round figures (.000, .500), or institutional quarters (.250, .750).\n- 'Exact_Stop_Loss_Price': The exact protective invalidation price point.\n- 'Exact_Take_Profit_Price': The exact planned objective target price point.\n- 'Planned_SL_Pips': The total calculated mathematical pip distance from entry to stop loss.\n- 'Planned_TP_Pips': The total calculated mathematical pip distance from entry to take profit.\n- 'Planned_RR_Ratio': The raw calculated risk-to-reward ratio metric planned prior to execution (e.g., 1:4.5).\n- 'Trade_Outcome': The definitive manual resolution of the position. Restricted to 'Win', 'Loss', or 'Break-Even'.\n- 'Net_R_Gain_Loss': The automated statistical performance return value based strictly on outcome (A 'Loss' = -1.0R, 'Break-Even' = 0.0R, 'Win' = full positive Planned_RR value).\n- 'Max_Adverse_Excursion_MAE': The maximum drawdown in pips experienced during the life of the trade. Mandatory for wins to evaluate entry optimization.\n- 'Max_Favorable_Excursion_MFE': The maximum profit expansion in pips reached before invalidation. Mandatory for losses to analyze exit greed optimization.\n- 'SL_Placement_Desc': Qualitative structural explanation outlining the logic of where the protective order was positioned.\n- 'TP_Placement_Desc': Qualitative structural explanation outlining the logic of where the target objective was positioned.\n- 'Entry_Reversal_Notes': Tape-reading observations made in real-time regarding candle signatures, reaction momentum, or zone mitigation nuances exactly during the entry window.\n- 'Final_Outcome_Notes': Macro retrospective comments logging psychology, mistakes, or key takeaways after the trade fully resolved.\n\nAnalyze these records globally to extract edge patterns, structural performance anomalies, structural placement safety margins, and win-rate optimizations based on these descriptions.\n[AI DATA DICTIONARY HEADER END]\n\n---\n[RAW DATA RECORDS FOLLOW]\n"""


def generate_ai_export():
    trades_list = get_all_trades()
    if not trades_list:
        return 'No trades recorded yet.'

    records = []
    for t in reversed(trades_list):
        try:
            modules = json.loads(t.get('entry_modules') or '[]') if isinstance(t.get('entry_modules'), str) else t.get('entry_modules')
        except Exception:
            modules = []
        modules_str = ', '.join(modules) if modules else 'N/A'
        try:
            zones_raw = json.loads(t.get('dynamic_entry_zones') or '{}')
            zones_str = '; '.join([f"{mod}: {lvl}" for mod, lvl in zones_raw.items() if lvl and lvl != 'N/A']) or 'N/A'
        except Exception:
            zones_str = 'N/A'
        reversal = t.get('actual_reversal_custom') or t.get('actual_reversal_zone') or 'N/A'
        eat_display = t.get('execution_time_eat') or 'N/A'
        if len(str(eat_display)) > 8:
            try:
                eat_display = datetime.strptime(eat_display, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M EAT')
            except Exception:
                pass

        def _v(key, default='N/A'):
            val = t.get(key)
            return str(val) if val is not None else default

        records.append(
            f"RECORD_{t['id']}: "
            f"ID: {t['id']} | Pair: {t['pair']} | TF: {t['timeframe']} | Dir: {t['direction']} | "
            f"Session: {t.get('session') or 'N/A'} | Time: {eat_display} | "
            f"Modules: [{modules_str}] | Entry_Zones: [{zones_str}] | "
            f"Reversal_Zone: {reversal} | "
            f"Entry_Px: {_v('exact_entry_price')} | SL_Px: {_v('exact_sl_price')} | TP_Px: {_v('exact_tp_price')} | "
            f"P_SL: {_v('planned_sl_pips')} | P_TP: {_v('planned_tp_pips')} | P_RR: {_v('planned_rr')} | "
            f"Outcome: {t['outcome']} | Net_R: {t['net_r']} | "
            f"MAE: {_v('actual_mae_pips')} | MFE: {_v('actual_mfe_pips')} | "
            f"SL_Desc: {_v('sl_placement_desc')} | TP_Desc: {_v('tp_placement_desc')} | "
            f"Entry_Notes: {_v('entry_reversal_notes')} | Final_Notes: {_v('notes')}"
        )

    return AI_DICT_HEADER + "\n".join(records) + "\n\n[DATASET RECORD END]\n---"
