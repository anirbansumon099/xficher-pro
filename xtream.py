#!/usr/bin/env python3
# xtream_pro_fix.py
# Pro Termux Xtream Manager (Fixed & Robust)
# Requires: requests (and optionally cloudscraper for Cloudflare bypass)

import os
import json
import time
import requests
from getpass import getpass

# Try optional cloudscraper for CF bypass
try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except Exception:
    HAS_CLOUDSCRAPER = False

# --------- Config / Paths ----------
DATA_DIR = "xtream_data"
SERVERS_FILE = os.path.join(DATA_DIR, "servers.json")
OUTPUT_DIR = os.path.join(DATA_DIR, "output")
DEBUG_DIR = os.path.join(DATA_DIR, "debug")

# --------- Terminal Colors ----------
class C:
    B = '\033[1m'
    R = '\033[91m'
    G = '\033[92m'
    Y = '\033[93m'
    C = '\033[96m'
    RESET = '\033[0m'

def clear():
    os.system("clear" if os.name != "nt" else "cls")

def hr():
    print(C.C + "─" * 60 + C.RESET)

# --------- Utilities ----------
def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DEBUG_DIR, exist_ok=True)
    if not os.path.exists(SERVERS_FILE):
        with open(SERVERS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)

def load_servers():
    ensure_dirs()
    with open(SERVERS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return []

def save_servers(servers):
    ensure_dirs()
    with open(SERVERS_FILE, "w", encoding="utf-8") as f:
        json.dump(servers, f, indent=2, ensure_ascii=False)

def timestamp_to_str(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts)))
    except:
        return str(ts)

def prompt_server_index(servers, purpose="select"):
    if not servers:
        print(C.R + "⚠️ No Saved File" + C.RESET)
        return None
    for i, s in enumerate(servers, 1):
        name = s.get("name") or f"{s.get('server_url')}"
        last = s.get("last_check") and timestamp_to_str(s.get("last_check")) or "Never"
        status = s.get("user_info", {}).get("status") or "-"
        print(f" {i}. {C.Y}{name}{C.RESET} — status: {status} — last_check: {last}")
    try:
        idx = int(input(f"\n👉 {purpose} Select Server Id: ").strip())
        if 1 <= idx <= len(servers):
            return idx - 1
    except:
        pass
    print(C.R + "⚠️ Wrong Input!" + C.RESET)
    return None

# --------- Networking helpers (robust) ----------
DEFAULT_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114 Safari/537.36"

# Generate candidate endpoints to try
def generate_endpoints(base_server):
    """
    base_server may be with or without scheme and port.
    This function returns a list of full base URLs to try (without trailing slash).
    """
    s = base_server.strip()
    # remove trailing slashes
    s = s.rstrip('/')
    candidates = []

    # If scheme included
    if s.startswith("http://") or s.startswith("https://"):
        # try given, plus alternative ports and alternate scheme
        proto, rest = s.split("://", 1)
        host = rest
        schemes = [proto]
        schemes.append("https" if proto == "http" else "http")
    else:
        host = s
        schemes = ["http", "https"]

    # common ports to attempt (explicit)
    common_ports = ["", ":80", ":8080", ":8000", ":8081", ":8443", ":443"]
    # if host already contains a port, use as-is and don't append extra ports
    if ":" in host and not host.startswith("["):  # simple port detection
        # host likely has port already
        common_ports = [""]

    for scheme in schemes:
        for p in common_ports:
            url = f"{scheme}://{host}{p}"
            # normalize double :443 if already had scheme with port - it's okay; requests will try
            candidates.append(url.rstrip('/'))
    # ensure uniqueness while preserving order
    seen = set()
    uniq = []
    for u in candidates:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq

def save_debug_response(server_name, endpoint, response_text):
    ensure_dirs()
    fname = f"{int(time.time())}_{server_name}_debug.txt".replace(" ", "_")
    path = os.path.join(DEBUG_DIR, fname)
    try:
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(f"Endpoint: {endpoint}\n\n")
            f.write(response_text[:500000])  # cap to avoid huge files
    except Exception as e:
        print(C.R + f"Failed to write debug file: {e}" + C.RESET)
        return None
    return path

def request_with_client(endpoint, timeout=DEFAULT_TIMEOUT):
    """
    Use cloudscraper if available (Cloudflare bypass), else requests.
    Returns tuple (response_obj_or_exception, used_client_name)
    """
    headers = {"User-Agent": USER_AGENT}
    if HAS_CLOUDSCRAPER:
        try:
            scr = cloudscraper.create_scraper(browser={'custom': USER_AGENT})
            r = scr.get(endpoint, timeout=timeout, headers=headers)
            return (r, "cloudscraper")
        except Exception as e:
            # fallback to requests
            pass
    try:
        r = requests.get(endpoint, timeout=timeout, headers=headers, allow_redirects=True)
        return (r, "requests")
    except Exception as e:
        return (e, "requests")

# Robust fetch player_api with multiple endpoints
def fetch_player_api_robust(server_url, username, password, timeout=DEFAULT_TIMEOUT, verbose=True):
    endpoints = generate_endpoints(server_url)
    tried = []
    for base in endpoints:
        api_url = f"{base}/player_api.php?username={username}&password={password}"
        if verbose:
            print(C.Y + "Trying endpoint:" + C.RESET, api_url)
        resp, client = request_with_client(api_url, timeout=timeout)
        tried.append((api_url, resp, client))
        # if exception returned
        if isinstance(resp, Exception):
            if verbose:
                print(C.R + f"  Error ({client}): {resp}" + C.RESET)
            continue
        # if response got but non-200
        status = getattr(resp, "status_code", None)
        if status != 200:
            if verbose:
                print(C.R + f"  HTTP status {status} from {client}" + C.RESET)
            # save snippet for debugging
            try:
                snippet = resp.text[:1000]
                path = save_debug_response("player_api_non200", api_url, resp.text)
                if verbose and path:
                    print(C.C + f"  Saved debug to: {path}" + C.RESET)
            except:
                pass
            continue
        # status 200 -> try parse JSON
        text = resp.text or ""
        try:
            data = resp.json()
            # good JSON; return
            return {"ok": True, "endpoint": api_url, "client": client, "data": data}
        except Exception as e:
            # save raw response for debugging
            path = save_debug_response("player_api_badjson", api_url, text)
            if verbose:
                print(C.R + f"  JSON parse failed: {e}. Saved raw to: {path}" + C.RESET)
            # still continue to next endpoint
            continue
    # if reached here, nothing succeeded
    return {"ok": False, "tried": tried}

# Robust playlist fetch (m3u)
def fetch_playlist_robust(server_url, username, password, m3u_type="m3u_plus", timeout=DEFAULT_TIMEOUT, verbose=True):
    endpoints = generate_endpoints(server_url)
    for base in endpoints:
        pl_url = f"{base}/get.php?username={username}&password={password}&type={m3u_type}"
        if verbose:
            print(C.Y + "Trying playlist endpoint:" + C.RESET, pl_url)
        resp, client = request_with_client(pl_url, timeout=timeout)
        if isinstance(resp, Exception):
            if verbose:
                print(C.R + f"  Error ({client}): {resp}" + C.RESET)
            continue
        if getattr(resp, "status_code", None) != 200:
            if verbose:
                print(C.R + f"  HTTP status {resp.status_code}" + C.RESET)
            continue
        text = resp.text or ""
        # M3U often begins with #EXTM3U
        if "#EXTM3U" in text.upper():
            return {"ok": True, "endpoint": pl_url, "client": client, "text": text}
        else:
            # not a valid M3U but still save to debug
            path = save_debug_response("playlist_nonm3u", pl_url, text)
            if verbose:
                print(C.Y + "  Response not M3U. Saved raw for debugging:", path)
            # still consider returning raw? For now treat as failure
            continue
    return {"ok": False}

# --------- Core Features (same interface as before) ----------
def add_server():
    clear()
    print(C.B + C.C + "➕ Add a  new Server" + C.RESET)
    name = input("Name (label): ").strip()
    server_url = input("Server URL (e.g., example.com or http://example.com:8080): ").strip()
    username = input("Username: ").strip()
    password = getpass("Password (hidden): ").strip()
    server = {
        "name": name or server_url,
        "server_url": server_url,
        "username": username,
        "password": password,
        "created_at": int(time.time()),
        "last_check": None,
        "last_endpoint": None,
        "last_client": None,
        "user_info": {},
        "server_info": {}
    }
    servers = load_servers()
    servers.append(server)
    save_servers(servers)
    print(C.G + "✅  Server has been Saved" + C.RESET)
    input("Press ENTER ...")

def view_servers():
    clear()
    print(C.B + C.C + "📁 Saved Servers" + C.RESET)
    servers = load_servers()
    if not servers:
        print(C.Y + "No servers saved yet." + C.RESET)
        input("Press ENTER ...")
        return
    for i, s in enumerate(servers, 1):
        name = s.get("name")
        url = s.get("server_url")
        last = s.get("last_check") and timestamp_to_str(s.get("last_check")) or "Never"
        status = s.get("user_info", {}).get("status") or "-"
        print(f"{i}. {C.Y}{name}{C.RESET} — {url}\n    status: {status}    last_check: {last}")
    hr()
    print("Options: [v]iew details  [e]dit  [d]elete  [b]ack")
    opt = input("Choose: ").strip().lower()
    if opt == "v":
        idx = prompt_server_index(servers, "view")
        if idx is not None:
            show_server_details(idx)
    elif opt == "e":
        idx = prompt_server_index(servers, "edit")
        if idx is not None:
            edit_server(idx)
    elif opt == "d":
        idx = prompt_server_index(servers, "delete")
        if idx is not None:
            delete_server(idx)
    input("Press ENTER ...")

def show_server_details(idx):
    servers = load_servers()
    s = servers[idx]
    clear()
    print(C.B + C.C + f"🔎 Details — {s.get('name')}" + C.RESET)
    print(f"URL: {s.get('server_url')}")
    print(f"Username: {s.get('username')}")
    print(f"Created: {timestamp_to_str(s.get('created_at'))}")
    print(f"Last check: {s.get('last_check') and timestamp_to_str(s.get('last_check')) or 'Never'}")
    if s.get("last_endpoint"):
        print(f"Last endpoint used: {s.get('last_endpoint')} (client: {s.get('last_client')})")
    hr()
    ui = s.get("user_info", {})
    si = s.get("server_info", {})
    if ui:
        print(C.G + "User Info:" + C.RESET)
        print(f"  username: {ui.get('username')}")
        print(f"  status: {ui.get('status')}")
        exp = ui.get('exp_date')
        if exp:
            try:
                print(f"  expire: {timestamp_to_str(int(exp))}")
            except:
                print(f"  expire: {exp}")
        print(f"  active_cons: {ui.get('active_cons')}")
        print(f"  max_connections: {ui.get('max_connections')}")
        print()
    else:
        print(C.Y + "No user_info fetched yet." + C.RESET)
    if si:
        print(C.G + "Server Info:" + C.RESET)
        for k,v in si.items():
            print(f"  {k}: {v}")
    else:
        print(C.Y + "No server_info fetched yet." + C.RESET)
    hr()
    print("Actions: [r]efresh info   [p]laylist fetch   [d]ebug view   [b]ack")
    act = input("choose: ").strip().lower()
    if act == "r":
        refresh_server(idx)
    elif act == "p":
        fetch_and_save_playlist(idx)
    elif act == "d":
        show_debug_files()
    # else back to menu

def edit_server(idx):
    servers = load_servers()
    s = servers[idx]
    clear()
    print(C.B + C.C + f"✏️ Edit — {s.get('name')}" + C.RESET)
    name = input(f"Name [{s.get('name')}]: ").strip() or s.get('name')
    server_url = input(f"Server URL [{s.get('server_url')}]: ").strip() or s.get('server_url')
    username = input(f"Username [{s.get('username')}]: ").strip() or s.get('username')
    pwd_prompt = input("Change password? (y/N): ").strip().lower()
    if pwd_prompt == "y":
        password = getpass("New Password: ").strip() or s.get('password')
    else:
        password = s.get('password')
    s.update({
        "name": name, "server_url": server_url, "username": username, "password": password
    })
    servers[idx] = s
    save_servers(servers)
    print(C.G + "✅ Updated." + C.RESET)

def delete_server(idx):
    servers = load_servers()
    s = servers[idx]
    confirm = input(C.R + f"Are you sure delete '{s.get('name')}'? (y/N): " + C.RESET).strip().lower()
    if confirm == "y":
        servers.pop(idx)
        save_servers(servers)
        print(C.G + "Deleted." + C.RESET)
    else:
        print("Cancelled.")

def refresh_server(idx):
    servers = load_servers()
    s = servers[idx]
    clear()
    print(C.B + C.C + f"🔁 Refreshing — {s.get('name')}" + C.RESET)
    res = fetch_player_api_robust(s.get("server_url"), s.get("username"), s.get("password"), timeout=DEFAULT_TIMEOUT, verbose=True)
    if not res.get("ok"):
        print(C.R + "❌ No valid player_api response found. See debug files." + C.RESET)
        # save tried endpoints for reference
        s["last_endpoint"] = None
        s["last_client"] = None
        s["last_check"] = int(time.time())
        servers[idx] = s
        save_servers(servers)
        input("Press ENTER ...")
        return
    data = res.get("data")
    s["user_info"] = data.get("user_info", {}) or {}
    s["server_info"] = data.get("server_info", {}) or {}
    s["last_endpoint"] = res.get("endpoint")
    s["last_client"] = res.get("client")
    s["last_check"] = int(time.time())
    servers[idx] = s
    save_servers(servers)
    print(C.G + "✅ Refreshed & saved." + C.RESET)
    input("Press ENTER ...")

def fetch_and_save_playlist(idx):
    servers = load_servers()
    s = servers[idx]
    clear()
    print(C.B + C.C + f"🎵 Fetch Playlist — {s.get('name')}" + C.RESET)
    res = fetch_playlist_robust(s.get("server_url"), s.get("username"), s.get("password"), verbose=True)
    if not res.get("ok"):
        print(C.R + "❌ Failed to fetch a valid M3U playlist. Check debug files." + C.RESET)
        input("Press ENTER ...")
        return
    text = res.get("text", "")
    safe_name = s.get('name', 'server').replace(" ", "_")
    fname = f"{safe_name}_{s.get('username')}_playlist.m3u"
    path = os.path.join(OUTPUT_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    # update last_check and last_endpoint
    s["last_check"] = int(time.time())
    s["last_endpoint"] = res.get("endpoint")
    s["last_client"] = res.get("client")
    servers[idx] = s
    save_servers(servers)
    print(C.G + f"✅ Playlist saved: {path}" + C.RESET)
    input("Press ENTER ...")

def refresh_all_servers():
    servers = load_servers()
    if not servers:
        print(C.Y + "No servers to refresh." + C.RESET)
        input("Press ENTER ...")
        return
    clear()
    print(C.B + C.C + "🔄 Refreshing all saved servers..." + C.RESET)
    for i, s in enumerate(servers):
        print(f"\n{i+1}. {s.get('name')} — {s.get('server_url')}")
        res = fetch_player_api_robust(s.get("server_url"), s.get("username"), s.get("password"), timeout=DEFAULT_TIMEOUT, verbose=False)
        if not res.get("ok"):
            print(C.R + "  Failed." + C.RESET)
            s["last_endpoint"] = None
            s["last_client"] = None
            s["last_check"] = int(time.time())
            servers[i] = s
            continue
        data = res.get("data")
        s["user_info"] = data.get("user_info", {}) or {}
        s["server_info"] = data.get("server_info", {}) or {}
        s["last_endpoint"] = res.get("endpoint")
        s["last_client"] = res.get("client")
        s["last_check"] = int(time.time())
        servers[i] = s
        print(C.G + "  OK" + C.RESET)
    save_servers(servers)
    print(C.G + "\n✅ All done." + C.RESET)
    input("Press ENTER ...")

# debug viewing
def list_debug_files():
    ensure_dirs()
    files = sorted(os.listdir(DEBUG_DIR), reverse=True)
    return files

def show_debug_files():
    files = list_debug_files()
    if not files:
        print(C.Y + "No debug files." + C.RESET)
        return
    print(C.C + "\nDebug files:\n" + C.RESET)
    for i, f in enumerate(files, 1):
        print(f" {i}. {f}")
    try:
        choice = int(input("\nOpen file number (0 to cancel): ").strip())
        if choice == 0:
            return
        file = files[choice-1]
        path = os.path.join(DEBUG_DIR, file)
        clear()
        print(C.B + C.C + f"--- DEBUG: {file} ---" + C.RESET)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
            print(content)
        print(C.C + "\n--- end ---" + C.RESET)
    except Exception as e:
        print(C.R + f"Invalid choice or error: {e}" + C.RESET)

# --------- Main Menu ----------
def main_menu():
    ensure_dirs()
    while True:
        clear()
        print(C.B + C.C + "╔════════════════════════════════════════╗" + C.RESET)
        print(C.B + C.C + "║      Xfitcher PRO - Xtream Manager     ║"+C.RESET)
        print(C.B+C.C+"║           Anirbansumon                 ║" + C.RESET)
        print(C.B + C.C + "╚════════════════════════════════════════╝" + C.RESET)
        hr()
        print(C.G + "[1]" + C.RESET + " Add New Server")
        print(C.G + "[2]" + C.RESET + " View Saved Servers")
        print(C.G + "[3]" + C.RESET + " Refresh Server Info (single)")
        print(C.G + "[4]" + C.RESET + " Fetch Playlist for a Server")
        print(C.G + "[5]" + C.RESET + " Refresh All Servers")
        print(C.G + "[6]" + C.RESET + " View Debug Files")
        print(C.G + "[7]" + C.RESET + " Exit")
        hr()
        choice = input("Select option: ").strip()
        if choice == "1":
            add_server()
        elif choice == "2":
            view_servers()
        elif choice == "3":
            servers = load_servers()
            idx = prompt_server_index(servers, "refresh")
            if idx is not None:
                refresh_server(idx)
                input("Press ENTER ...")
        elif choice == "4":
            servers = load_servers()
            idx = prompt_server_index(servers, "fetch playlist for")
            if idx is not None:
                fetch_and_save_playlist(idx)
        elif choice == "5":
            refresh_all_servers()
        elif choice == "6":
            show_debug_files()
            input("Press ENTER ...")
        elif choice == "7":
            print(C.G + "Goodbye 👋" + C.RESET)
            break
        else:
            print(C.R + "Invalid choice." + C.RESET)
            time.sleep(1)

if __name__ == "__main__":
    if HAS_CLOUDSCRAPER:
        print(C.G + "cloudscraper available — Cloudflare-protected servers may be handled." + C.RESET)
    else:
        print(C.Y + "cloudscraper not installed. For Cloudflare-protected servers install it: pip install cloudscraper" + C.RESET)
    time.sleep(0.8)
    main_menu()
