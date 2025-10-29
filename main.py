#!/usr/bin/env python3
# xtream_pro_fix.py
# Pro Termux Xtream Manager (Fixed & Robust)
# Requires: requests (and optionally cloudscraper for Cloudflare bypass)
# Added: nicer progress bars for download, parsing, JSON save and M3U build (no external deps)

import os
import json
import time
import requests
import sys
import re
from getpass import getpass

# Try optional cloudscraper for CF bypass
try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except Exception:
    HAS_CLOUDSCRAPER = False

# --------- Config / Paths ----------
DATA_DIR = "xtream_data32"
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

# --------- Small progress helper (no external deps) ----------
def is_tty():
    try:
        return sys.stdout.isatty()
    except:
        return False

def print_progress_bar(count, total, prefix='', suffix='', length=40, fill='█'):
    """
    Simple progress bar that works in most terminals.
    count: current progress (int)
    total: total steps (int). If total is 0 or None, prints bytes / unknown progress.
    """
    if total and total > 0:
        proportion = max(0.0, min(1.0, float(count) / float(total)))
        filled_length = int(length * proportion)
        bar = fill * filled_length + '-' * (length - filled_length)
        pct = proportion * 100
        sys.stdout.write(f"\r{prefix} |{bar}| {pct:6.2f}% {suffix}")
        sys.stdout.flush()
        if count >= total:
            sys.stdout.write("\n")
            sys.stdout.flush()
    else:
        # Unknown total: show bytes downloaded count with a simple spinner
        spinner = ['-', '\\', '|', '/']
        s = spinner[count % len(spinner)]
        sys.stdout.write(f"\r{prefix} {s} {count} bytes {suffix}")
        sys.stdout.flush()

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

def request_with_client(endpoint, timeout=DEFAULT_TIMEOUT, stream=False):
    """
    Use cloudscraper if available (Cloudflare bypass), else requests.
    Returns tuple (response_obj_or_exception, used_client_name)
    stream: if True, request with stream=True to allow iter_content
    """
    headers = {"User-Agent": USER_AGENT}
    if HAS_CLOUDSCRAPER:
        try:
            scr = cloudscraper.create_scraper(browser={'custom': USER_AGENT})
            r = scr.get(endpoint, timeout=timeout, headers=headers, allow_redirects=True, stream=stream)
            return (r, "cloudscraper")
        except Exception:
            # fallback to requests
            pass
    try:
        r = requests.get(endpoint, timeout=timeout, headers=headers, allow_redirects=True, stream=stream)
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

# Robust playlist fetch (m3u) with progress (uses print_progress_bar)
def fetch_playlist_robust(server_url, username, password, m3u_type="m3u_plus", timeout=DEFAULT_TIMEOUT, verbose=True):
    endpoints = generate_endpoints(server_url)
    for base in endpoints:
        pl_url = f"{base}/get.php?username={username}&password={password}&type={m3u_type}"
        if verbose:
            print(C.Y + "Trying playlist endpoint:" + C.RESET, pl_url)
        resp, client = request_with_client(pl_url, timeout=timeout, stream=True)
        # handle exceptions
        if isinstance(resp, Exception):
            if verbose:
                print(C.R + f"  Error ({client}): {resp}" + C.RESET)
            continue
        status = getattr(resp, "status_code", None)
        if status != 200:
            if verbose:
                print(C.R + f"  HTTP status {status}" + C.RESET)
            try:
                text_snip = resp.text
                save_debug_response("playlist_non200", pl_url, text_snip)
            except:
                pass
            try:
                resp.close()
            except:
                pass
            continue

        # Stream the response and show progress
        try:
            total = 0
            try:
                total = int(resp.headers.get('Content-Length') or 0)
            except:
                total = 0
            downloaded = 0
            chunks = []
            if verbose:
                if total:
                    print(C.C + f"  Content-Length: {total} bytes. Starting download..." + C.RESET)
                else:
                    print(C.C + "  Content-Length unknown. Starting download..." + C.RESET)
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                chunks.append(chunk)
                downloaded += len(chunk)
                if verbose:
                    if total:
                        print_progress_bar(downloaded, total, prefix="  Downloading", length=40)
                    else:
                        print_progress_bar(downloaded, None, prefix="  Downloading", length=20)
            if verbose and total:
                # ensure finished bar printed
                print_progress_bar(downloaded, total, prefix="  Downloading", length=40)
            if verbose and not total:
                sys.stdout.write("\n")
                sys.stdout.flush()
            # join and decode using response encoding
            raw = b"".join(chunks)
            encoding = getattr(resp, "encoding", None) or "utf-8"
            try:
                text = raw.decode(encoding, errors="replace")
            except:
                text = raw.decode("utf-8", errors="replace")
            # close response
            try:
                resp.close()
            except:
                pass

            # Validate M3U signature
            if "#EXTM3U" in text.upper():
                return {"ok": True, "endpoint": pl_url, "client": client, "text": text}
            else:
                # not a valid M3U but still save to debug
                path = save_debug_response("playlist_nonm3u", pl_url, text)
                if verbose:
                    print(C.Y + "  Response not M3U. Saved raw for debugging:", path)
                continue
        except Exception as e:
            # save debugging info
            try:
                resp_text = resp.text if hasattr(resp, "text") else ""
                path = save_debug_response("playlist_error", pl_url, resp_text or str(e))
                if verbose:
                    print(C.R + f"  Error while streaming: {e}. Saved debug: {path}" + C.RESET)
            except Exception:
                if verbose:
                    print(C.R + f"  Error while streaming: {e}" + C.RESET)
            try:
                resp.close()
            except:
                pass
            continue
    return {"ok": False}

# --------- M3U parsing / JSON / Filter / Rebuild ----------
def parse_m3u_to_json(m3u_text, verbose=False):
    """
    Parse an M3U (EXTM3U) playlist into a list of channel dicts.
    Each channel dict contains:
      - title
      - duration
      - attrs: dict of attributes (tvg-id, tvg-name, tvg-logo, group-title, etc.)
      - url
      - raw_extinf (original extinf line)
    If verbose=True, shows a simple progress indicator while collecting channels.
    """
    lines = [ln.rstrip("\n") for ln in m3u_text.splitlines()]
    channels = []
    i = 0
    estimated_total_lines = len(lines) or 1
    processed = 0
    while i < len(lines):
        ln = lines[i].strip()
        processed += 1
        if verbose and (processed % 50 == 0 or processed == estimated_total_lines):
            # update a rough progress by lines processed (not exact channels yet)
            print_progress_bar(processed, estimated_total_lines, prefix="  Parsing lines", length=30)
        if not ln:
            i += 1
            continue
        if ln.upper().startswith("#EXTINF"):
            raw_extinf = ln
            # try to extract duration and attributes and title
            parts = ln.split(",", 1)
            if len(parts) == 2:
                header, title = parts[0], parts[1].strip()
            else:
                header, title = parts[0], ""
            dur_match = re.match(r'#EXTINF:([-0-9]+)', header, re.IGNORECASE)
            duration = dur_match.group(1) if dur_match else ""
            attrs = dict(re.findall(r'([a-zA-Z0-9\-_]+?)="(.*?)"', header))
            # Next non-empty non-comment line should be URL
            url = ""
            j = i + 1
            while j < len(lines):
                candidate = lines[j].strip()
                if candidate == "" or candidate.startswith("#"):
                    j += 1
                    continue
                url = candidate
                break
            channel = {
                "title": title,
                "duration": duration,
                "attrs": attrs,
                "url": url,
                "raw_extinf": raw_extinf
            }
            channels.append(channel)
            # move i to j+1
            i = j + 1
            continue
        else:
            i += 1
    if verbose:
        # finish progress line if needed
        print_progress_bar(estimated_total_lines, estimated_total_lines, prefix="  Parsing lines", length=30)
        print(C.G + f"  Parsed {len(channels)} channels." + C.RESET)
    return channels

def save_playlist_json(safe_name, username, channels):
    """
    Stream-write JSON file per-channel so we can show progress.
    Produces pretty formatted JSON with each item indented.
    """
    ensure_dirs()
    fname = f"{safe_name}_{username}_playlist.json"
    path = os.path.join(OUTPUT_DIR, fname)
    try:
        total = len(channels) if channels else 0
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[\n")
            for idx, ch in enumerate(channels):
                # dump each channel with indent 2
                dumped = json.dumps(ch, ensure_ascii=False, indent=2)
                # add indentation to lines to maintain array formatting
                indented = "\n".join(["  " + line for line in dumped.splitlines()])
                fh.write(indented)
                if idx < total - 1:
                    fh.write(",\n")
                else:
                    fh.write("\n")
                # update progress
                print_progress_bar(idx + 1, total, prefix="  Saving JSON", length=40)
            fh.write("]\n")
        return path
    except Exception as e:
        print(C.R + f"Failed to save JSON playlist: {e}" + C.RESET)
        return None

def load_playlist_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        print(C.R + f"Failed to load JSON: {e}" + C.RESET)
        return None

def build_extinf_line(entry):
    # entry: dict with duration, attrs, title
    dur = entry.get("duration", "-1")
    attrs = entry.get("attrs", {}) or {}
    attr_parts = []
    for k, v in attrs.items():
        safe_v = v.replace('"', "'")
        attr_parts.append(f'{k}="{safe_v}"')
    attr_str = " ".join(attr_parts)
    title = entry.get("title", "")
    if attr_str:
        return f'#EXTINF:{dur} {attr_str},{title}'
    else:
        return f'#EXTINF:{dur},{title}'

def create_m3u_from_channels(channels, out_path):
    """
    Build M3U by iterating channels and show a progress bar.
    """
    try:
        total = len(channels) if channels else 0
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("#EXTM3U\n")
            for idx, ch in enumerate(channels):
                ext = build_extinf_line(ch)
                fh.write(ext + "\n")
                fh.write((ch.get("url") or "") + "\n")
                print_progress_bar(idx + 1, total, prefix="  Building M3U", length=40)
        return True
    except Exception as e:
        print(C.R + f"Failed to write M3U: {e}" + C.RESET)
        return False

def list_output_playlists():
    ensure_dirs()
    files = sorted(os.listdir(OUTPUT_DIR))
    m3us = [f for f in files if f.lower().endswith(".m3u")]
    jsons = [f for f in files if f.lower().endswith(".json")]
    return m3us, jsons

def filter_channels(channels, field, keyword):
    """
    field: 'title', 'group', 'tvg-name', 'tvg-id', etc.
    keyword: substring (case-insensitive)
    Returns filtered list.
    """
    if not keyword:
        return channels[:]
    kw = keyword.strip().lower()
    out = []
    for ch in channels:
        if field == "title":
            if kw in (ch.get("title") or "").lower():
                out.append(ch)
        elif field == "group":
            grp = (ch.get("attrs") or {}).get("group-title", "")
            if kw in grp.lower():
                out.append(ch)
        else:
            val = (ch.get("attrs") or {}).get(field, "")
            if kw in val.lower():
                out.append(ch)
    return out

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
    # parse and save JSON automatically with progress
    channels = parse_m3u_to_json(text, verbose=True)
    json_path = save_playlist_json(safe_name, s.get('username'), channels) if channels else None
    # update last_check and last_endpoint
    s["last_check"] = int(time.time())
    s["last_endpoint"] = res.get("endpoint")
    s["last_client"] = res.get("client")
    servers[idx] = s
    save_servers(servers)
    print(C.G + f"✅ Playlist saved: {path}" + C.RESET)
    if json_path:
        print(C.G + f"✅ Parsed JSON saved: {json_path}" + C.RESET)
        print(C.C + f"Parsed {len(channels)} channels." + C.RESET)
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

# Playlist management interactive menu
def manage_playlists_menu():
    while True:
        clear()
        print(C.B + C.C + "🎛️ Playlist Manager" + C.RESET)
        m3us, jsons = list_output_playlists()
        print(C.G + "M3U files:" + C.RESET)
        if m3us:
            for i, f in enumerate(m3us, 1):
                print(f" {i}. {f}")
        else:
            print("  (none)")
        print()
        print(C.G + "Parsed JSON playlists:" + C.RESET)
        if jsons:
            for i, f in enumerate(jsons, 1):
                print(f" {i}. {f}")
        else:
            print("  (none)")
        hr()
        print("Options:")
        print(" [1] Parse an existing M3U -> JSON")
        print(" [2] Search / Filter a parsed JSON and create new M3U")
        print(" [3] List parsed JSON and view sample entries")
        print(" [4] Back")
        choice = input("Choose: ").strip()
        if choice == "1":
            if not m3us:
                print(C.Y + "No M3U files to parse." + C.RESET)
                input("Press ENTER ...")
                continue
            try:
                idx = int(input(f"Select M3U file number (1-{len(m3us)}): ").strip())
                if not (1 <= idx <= len(m3us)):
                    raise ValueError()
                file = m3us[idx-1]
                path = os.path.join(OUTPUT_DIR, file)
                text = open(path, "r", encoding="utf-8", errors="replace").read()
                channels = parse_m3u_to_json(text, verbose=True)
                base = os.path.splitext(file)[0]
                parts = base.split("_")
                if len(parts) >= 2:
                    safe_name = parts[0]
                    username = parts[1]
                else:
                    safe_name = base
                    username = "user"
                json_path = save_playlist_json(safe_name, username, channels)
                if json_path:
                    print(C.G + f"Saved JSON: {json_path} ({len(channels)} channels)" + C.RESET)
                else:
                    print(C.R + "Failed to save JSON." + C.RESET)
            except Exception as e:
                print(C.R + f"Invalid choice: {e}" + C.RESET)
            input("Press ENTER ...")
        elif choice == "2":
            if not jsons:
                print(C.Y + "No parsed JSON files available. Parse an M3U first." + C.RESET)
                input("Press ENTER ...")
                continue
            try:
                idx = int(input(f"Select JSON file number (1-{len(jsons)}): ").strip())
                if not (1 <= idx <= len(jsons)):
                    raise ValueError()
                file = jsons[idx-1]
                path = os.path.join(OUTPUT_DIR, file)
                channels = load_playlist_json(path)
                if channels is None:
                    input("Press ENTER ...")
                    continue
                # Ask filter options
                print("Filter fields: [title] [group] [tvg-name] [tvg-id] (leave blank to skip)")
                field = input("Field to filter by (e.g., title/group): ").strip() or "title"
                keyword = input("Keyword (substring, case-insensitive): ").strip()
                filtered = filter_channels(channels, field, keyword)
                print(C.C + f"Found {len(filtered)} matching channels." + C.RESET)
                if not filtered:
                    input("Press ENTER ...")
                    continue
                out_name = input("Output M3U filename (no extension, press ENTER for auto): ").strip()
                if not out_name:
                    base = os.path.splitext(file)[0]
                    safe_kw = keyword.replace(" ", "_") if keyword else "all"
                    out_name = f"{base}_{field}-{safe_kw}_filtered"
                out_fname = out_name + ".m3u"
                out_path = os.path.join(OUTPUT_DIR, out_fname)
                ok = create_m3u_from_channels(filtered, out_path)
                if ok:
                    print(C.G + f"✅ Created filtered M3U: {out_path}" + C.RESET)
                    # also save as JSON via streaming writer to show progress
                    try:
                        json_out = os.path.splitext(out_fname)[0] + ".json"
                        json_out_path = os.path.join(OUTPUT_DIR, json_out)
                        # reuse save logic by naming accordingly
                        # we will write directly for clarity
                        with open(json_out_path, "w", encoding="utf-8") as fh:
                            fh.write("[\n")
                            total = len(filtered)
                            for i, ch in enumerate(filtered):
                                dumped = json.dumps(ch, ensure_ascii=False, indent=2)
                                indented = "\n".join(["  " + line for line in dumped.splitlines()])
                                fh.write(indented)
                                if i < total - 1:
                                    fh.write(",\n")
                                else:
                                    fh.write("\n")
                                print_progress_bar(i + 1, total, prefix="  Saving JSON", length=40)
                            fh.write("]\n")
                        print(C.G + f"✅ Also saved JSON: {json_out_path}" + C.RESET)
                    except Exception as e:
                        print(C.R + f"Failed to save JSON for filtered list: {e}" + C.RESET)
                else:
                    print(C.R + "Failed to create M3U." + C.RESET)
            except Exception as e:
                print(C.R + f"Invalid input: {e}" + C.RESET)
            input("Press ENTER ...")
        elif choice == "3":
            if not jsons:
                print(C.Y + "No parsed JSON files available." + C.RESET)
                input("Press ENTER ...")
                continue
            try:
                idx = int(input(f"Select JSON file number (1-{len(jsons)}): ").strip())
                if not (1 <= idx <= len(jsons)):
                    raise ValueError()
                file = jsons[idx-1]
                path = os.path.join(OUTPUT_DIR, file)
                channels = load_playlist_json(path)
                if channels is None:
                    input("Press ENTER ...")
                    continue
                print(C.C + f"Loaded {len(channels)} channels from {file}" + C.RESET)
                sample_n = int(input("How many sample entries to show? (0 to cancel): ").strip() or "0")
                if sample_n > 0:
                    total = min(sample_n, len(channels))
                    for i, ch in enumerate(channels[:total], 1):
                        print_progress_bar(i, total, prefix="  Showing samples", length=30)
                        print(f"\n[{i}] Title: {ch.get('title')}")
                        print(f"     URL: {ch.get('url')}")
                        print(f"     Group: {(ch.get('attrs') or {}).get('group-title')}")
                        print(f"     tvg-name: {(ch.get('attrs') or {}).get('tvg-name')}")
                    # ensure newline after progress
                    if total:
                        print()
                input("Press ENTER ...")
            except Exception as e:
                print(C.R + f"Invalid input: {e}" + C.RESET)
                input("Press ENTER ...")
        elif choice == "4":
            break
        else:
            print(C.R + "Invalid choice." + C.RESET)
            time.sleep(0.8)

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
        print(C.G + "[7]" + C.RESET + " Manage Playlists (parse/search/create)")
        print(C.G + "[8]" + C.RESET + " Exit")
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
            manage_playlists_menu()
        elif choice == "8":
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
