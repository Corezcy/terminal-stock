# -*- coding: utf-8 -*- 

import time
import os
import platform
import sys
import csv
import re
import unicodedata
from pathlib import Path
import requests

mystock = {}
stock_codes = []
stocks = ''
url = "https://qt.gtimg.cn/q="
previous_data = {}  # Store previous stock data for comparison
first_run = True
previous_display_rows = 0

ANSI_BOLD = '\033[1m'
ANSI_RESET = '\033[0m'
ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')


def normalize_stock_code(code):
    """Normalize stock code to formats like sh600000 / sz000001 / bj430047."""
    raw = str(code).strip().lower()
    if not raw:
        return ""

    if raw.startswith(("sh", "sz", "bj")):
        prefix = raw[:2]
        digits = raw[2:]
        if digits.isdigit():
            return f"{prefix}{digits.zfill(6)}"
        return raw

    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return raw

    digits = digits.zfill(6)
    if digits.startswith(("6", "9")):
        return f"sh{digits}"
    if digits.startswith(("0", "2", "3")):
        return f"sz{digits}"
    if digits.startswith(("4", "8")):
        return f"bj{digits}"
    return digits


def get_today_focus_csv_path():
    today = time.strftime("%Y%m%d", time.localtime())
    relative_path = Path(f"stock_changes_{today}") / f"stock_changes_summary_{today}_focus.csv"

    current_dir = Path(__file__).resolve().parent
    project_dir = current_dir.parent
    candidates = [
        current_dir / relative_path,
        project_dir / relative_path,
        project_dir / "AKShare" / relative_path,
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_my_stock_codes(stock_file_path):
    my_codes = []
    seen_codes = set()
    mystock.clear()

    with open(stock_file_path, 'r', encoding='utf-8') as f:
        stock_list = f.read().split('\n')

    for item in stock_list:
        if item.startswith('#'):
            continue
        if item.strip() == '':
            continue

        item_list = item.split()
        if len(item_list) < 1:
            continue

        code = normalize_stock_code(item_list[0])
        if not code or code in seen_codes:
            continue

        seen_codes.add(code)
        my_codes.append(code)
        mystock[code] = (item_list[1], item_list[2]) if len(item_list) == 3 else None

    return my_codes


def load_focus_stock_codes():
    focus_codes = []
    seen_codes = set()
    focus_path = get_today_focus_csv_path()
    if not focus_path:
        return focus_codes

    with open(focus_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = normalize_stock_code(row.get("代码", ""))
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            focus_codes.append(code)

    return focus_codes


def readData():
    global stocks, stock_codes

    current_dir = Path(__file__).resolve().parent
    stock_file_path = current_dir / 'my_stock.dat'

    try:
        my_codes = load_my_stock_codes(stock_file_path)
        focus_codes = load_focus_stock_codes()

        merged_codes = []
        seen_codes = set()

        # my_stock.dat 永远优先，focus 文件只补充未出现的代码
        for code in my_codes + focus_codes:
            if code and code not in seen_codes:
                seen_codes.add(code)
                merged_codes.append(code)

        stock_codes = merged_codes
        stocks = ",".join(stock_codes)

        if not stocks:
            print("未加载到任何股票代码，请检查 my_stock.dat 或当日 focus CSV")

    except FileNotFoundError:
        print(f"文件未找到: {stock_file_path}")
        print(f"当前工作目录: {os.getcwd()}")
    except Exception as e:
        print(f"读取文件时出错: {e}")


def getTime():
    return time.strftime('%Y-%m-%d %A %p %X', time.localtime(time.time()))


def text_display_width(text):
    width = 0
    for ch in str(text):
        width += 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
    return width


def strip_ansi(text):
    return ANSI_ESCAPE_RE.sub('', text)


def fit_text(text, width):
    result = []
    current = 0
    for ch in str(text):
        ch_width = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
        if current + ch_width > width:
            break
        result.append(ch)
        current += ch_width
    return ''.join(result)


def align_text(text, width, align='left'):
    clipped = fit_text(text, width)
    pad = width - text_display_width(clipped)
    if pad <= 0:
        return clipped
    if align == 'right':
        return (' ' * pad) + clipped
    return clipped + (' ' * pad)


def pad_display_line(line, width):
    visible_width = text_display_width(strip_ansi(line))
    if visible_width >= width:
        return line
    return line + (' ' * (width - visible_width))


def parseQtData(data_line):
    """
    Parse qt.gtimg.cn API response data
    Format: v_sh000001="field1~field2~field3~..."
    Returns: dict with parsed fields
    """
    try:
        # Split by '=' to get the data part
        parts = data_line.split('=', 1)
        if len(parts) < 2:
            return None
            
        # Extract the data between quotes
        data_part = parts[1].strip().strip('"').strip(';')
        fields = data_part.split('~')
        
        if len(fields) < 36:  # Need at least 36 fields for our required data
            return None
            
        return {
            'code': parts[0].replace('v_', ''),  # Extract code from v_sh000001
            'name': fields[1],          # 合约名称 - field 2
            'contract_id': fields[2],   # 合约ID - field 3  
            'latest_price': fields[3],  # 最新价 - field 4
            'prev_close': fields[4],    # 昨收 - field 5
            'open_price': fields[5],    # 开盘价 - field 6
            'change_pct': fields[32],   # 涨跌幅 - field 33
            'high_price': fields[33],   # 最高价 - field 34
            'low_price': fields[34],    # 最低价 - field 35
        }
    except (IndexError, ValueError) as e:
        print(f"Error parsing data line: {e}")
        return None


def clear_screen():
    """Clear screen only once at startup"""
    sysstr = platform.system()
    if sysstr == 'Darwin' or sysstr == "Linux":
        os.system("clear")
    elif sysstr == 'Windows':
        os.system("cls")


def move_cursor_to_top():
    """Move cursor to top of terminal without clearing"""
    sys.stdout.write('\033[H')  # Move cursor to home position
    sys.stdout.flush()


def hide_cursor():
    """Hide cursor to reduce flicker"""
    sys.stdout.write('\033[?25l')
    sys.stdout.flush()


def show_cursor():
    """Show cursor"""
    sys.stdout.write('\033[?25h')
    sys.stdout.flush()


def printStock():
    global previous_data, first_run, previous_display_rows
    
    try:
        # 每次刷新都重新读取：my_stock.dat + 当日 focus.csv
        readData()
        if not stocks:
            return

        ctx = requests.get(url + stocks, timeout=10)
        ctx.encoding = "gb2312"
        data = ctx.text
        
        # Split by semicolon and newline
        lines = data.replace(';', '\n').split('\n')
        
        current_data = {}
        
        # Parse all stock data first
        for line in lines:
            if not line.strip() or not line.startswith('v_'):
                continue
                
            stock_data = parseQtData(line.strip())
            if not stock_data:
                continue
                
            try:
                code = stock_data['code']
                name = stock_data['name']
                latest_price = float(stock_data['latest_price'])
                prev_close = float(stock_data['prev_close'])
                open_price = float(stock_data['open_price'])
                high_price = float(stock_data['high_price'])
                low_price = float(stock_data['low_price'])
                change_pct_raw = stock_data['change_pct']
                
                # Handle suspended trading
                if latest_price == 0:
                    change_pct = "停牌"
                    latest_price = prev_close
                else:
                    try:
                        change_val = float(change_pct_raw)
                        change_pct = f"{change_val:+.2f}%"
                    except ValueError:
                        change_pct = "N/A"
                
                stock_line = (
                    f"{align_text(code, 10)} | "
                    f"{align_text(name, 12)} | "
                    f"{align_text(f'{latest_price:.2f}', 10, 'right')} | "
                    f"{align_text(change_pct, 9, 'right')} | "
                    f"{align_text(f'{open_price:.2f}', 10, 'right')} | "
                    f"{align_text(f'{high_price:.2f}', 10, 'right')} | "
                    f"{align_text(f'{low_price:.2f}', 10, 'right')}"
                )

                if latest_price > prev_close:
                    stock_line = f"{ANSI_BOLD}{stock_line}{ANSI_RESET}"
                
                current_data[code] = stock_line
                
            except (ValueError, KeyError) as e:
                print(f"Error processing stock {stock_data.get('code', 'unknown')}: {e}")
                continue
        
        # Move cursor to top instead of clearing screen
        if not first_run:
            move_cursor_to_top()
        
        # Print header and time
        header = (
            f"{align_text('CODE', 10)} | "
            f"{align_text('NAME', 12)} | "
            f"{align_text('LATEST', 10, 'right')} | "
            f"{align_text('CHANGE', 9, 'right')} | "
            f"{align_text('OPEN', 10, 'right')} | "
            f"{align_text('HIGH', 10, 'right')} | "
            f"{align_text('LOW', 10, 'right')}"
        )
        separator = "-+-".join(['-' * 10, '-' * 12, '-' * 10, '-' * 9, '-' * 10, '-' * 10, '-' * 10])
        time_line = f"Time: {getTime()} | Total: {len(stock_codes)}"
        table_width = max(text_display_width(header), text_display_width(separator), text_display_width(time_line))
        
        print(pad_display_line(time_line, table_width))
        print(pad_display_line(header, table_width))
        print(pad_display_line(separator, table_width))
        
        # Print stock data
        rendered_rows = 0
        for code in stock_codes:
            stock_line = current_data.get(code)
            if not stock_line:
                continue
            print(pad_display_line(stock_line, table_width))
            rendered_rows += 1
        
        if not first_run and previous_display_rows > rendered_rows:
            for _ in range(previous_display_rows - rendered_rows):
                print(" " * table_width)
        
        previous_display_rows = rendered_rows
        previous_data = current_data
        first_run = False
        
    except requests.RequestException as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == '__main__':
    try:
        clear_screen()  # Clear screen only once at startup
        hide_cursor()   # Hide cursor to reduce flicker
        
        while True:
            printStock()
            time.sleep(1)  # Slightly longer interval for smoother updates
            
    except KeyboardInterrupt:
        show_cursor()  # Show cursor before exit
        print("\n程序已退出")
        sys.exit(0)
    except Exception as e:
        show_cursor()
        print(f"\n程序错误: {e}")
        sys.exit(1)
