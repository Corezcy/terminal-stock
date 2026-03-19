# -*- coding: utf-8 -*- 

import time
import os
import platform
import sys
import csv
from pathlib import Path
import requests

mystock = {}
stock_codes = []
stocks = ''
url = "https://qt.gtimg.cn/q="
previous_data = {}  # Store previous stock data for comparison
first_run = True


class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    WHITE = '\033[97m'
    ENDC = '\033[0m'

    def disable(self):
        self.HEADER = ''
        self.OKBLUE = ''
        self.GREEN = ''
        self.YELLOW = ''
        self.RED = ''
        self.ENDC = ''


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


def highOrLow(a, b):
    return bcolors.RED if a >= b else bcolors.GREEN


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
    global previous_data, first_run
    
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
                name = stock_data['name'][:8]  # Limit name length for display
                latest_price = float(stock_data['latest_price'])
                prev_close = float(stock_data['prev_close'])
                open_price = float(stock_data['open_price'])
                high_price = float(stock_data['high_price'])
                low_price = float(stock_data['low_price'])
                change_pct = stock_data['change_pct']
                
                # Handle suspended trading
                if latest_price == 0:
                    change_pct = "停牌"
                    latest_price = prev_close
                else:
                    # Format change percentage
                    try:
                        change_val = float(change_pct)
                        change_pct = f"{change_val:+.2f}%"
                    except:
                        change_pct = "N/A"
                
                # Color coding based on price movement
                latest_color = highOrLow(latest_price, prev_close)
                open_color = highOrLow(open_price, prev_close)
                high_color = highOrLow(high_price, prev_close)
                low_color = highOrLow(low_price, prev_close)
                change_color = bcolors.RED if latest_price >= prev_close else bcolors.GREEN
                
                # Create formatted line
                stock_line = (
                    f"{bcolors.WHITE}{code:<12}{bcolors.ENDC} "
                    f"{bcolors.WHITE}{name:<12}{bcolors.ENDC} "
                    # f"{bcolors.WHITE}{prev_close:>10.2f}{bcolors.ENDC} "
                    # f"{open_color}{open_price:>10.2f}{bcolors.ENDC} "
                    # f"{high_color}{high_price:>10.2f}{bcolors.ENDC} "
                    # f"{low_color}{low_price:>10.2f}{bcolors.ENDC} "
                    f"{latest_color}{latest_price:>10.2f}{bcolors.ENDC} "
                    f"{change_color}{change_pct:>10s}{bcolors.ENDC}"
                )
                
                current_data[code] = stock_line
                
            except (ValueError, KeyError) as e:
                print(f"Error processing stock {stock_data.get('code', 'unknown')}: {e}")
                continue
        
        # Move cursor to top instead of clearing screen
        if not first_run:
            move_cursor_to_top()
        
        # Print header and time
        time_str = bcolors.YELLOW + getTime() + bcolors.ENDC
        header = bcolors.WHITE + "CODE         NAME                 LATEST      CHANGE" + bcolors.ENDC
        separator = bcolors.WHITE + "=" * 55 + bcolors.ENDC
        
        print(f"{time_str:<120}")  # Fixed width to overwrite previous time
        print(f"{header:<120}")
        print(f"{separator:<120}")
        
        # Print stock data
        for code in stock_codes:
            stock_line = current_data.get(code)
            if not stock_line:
                continue
            # Add padding to ensure line is fully overwritten
            padded_line = f"{stock_line:<120}"
            print(padded_line)
        
        # Clear any remaining lines from previous output
        if not first_run:
            # Print empty lines to clear any leftover content
            for _ in range(3):
                print(" " * 120)
        
        previous_data = current_data
        first_run = False
        
    except requests.RequestException as e:
        error_msg = f"{bcolors.RED}Network error: {e}{bcolors.ENDC}"
        print(f"{error_msg:<120}")
    except Exception as e:
        error_msg = f"{bcolors.RED}Unexpected error: {e}{bcolors.ENDC}"
        print(f"{error_msg:<120}")


if __name__ == '__main__':
    try:
        clear_screen()  # Clear screen only once at startup
        hide_cursor()   # Hide cursor to reduce flicker
        
        while True:
            printStock()
            time.sleep(1)  # Slightly longer interval for smoother updates
            
    except KeyboardInterrupt:
        show_cursor()  # Show cursor before exit
        print(f"\n{bcolors.YELLOW}程序已退出{bcolors.ENDC}")
        sys.exit(0)
    except Exception as e:
        show_cursor()
        print(f"\n{bcolors.RED}程序错误: {e}{bcolors.ENDC}")
        sys.exit(1)
