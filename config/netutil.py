"""내부망(LAN) 접속 허용을 위한 도우미. settings.py의 LAN_ACCESS에서 사용."""

import ipaddress
import socket


def _private_ipv4s():
    """이 컴퓨터에 붙은 사설 IPv4 주소들 (192.168.x.x, 10.x.x.x, 172.16~31.x.x)."""
    found = set()
    # 기본 경로의 IP: 실제로 패킷을 보내지 않는 UDP connect 로 확인
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    result = []
    for ip in sorted(found):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_private and not addr.is_loopback and not addr.is_link_local:
            result.append(ip)
    return result


def local_network_hosts():
    """ALLOWED_HOSTS에 더할 이 컴퓨터의 사설 IP와 호스트명 목록."""
    hosts = _private_ipv4s()
    name = socket.gethostname().lower()
    if name:
        hosts.append(name)
        if not name.endswith(".local"):
            hosts.append(f"{name}.local")
    return hosts


def https_origins(hosts):
    """ALLOWED_HOSTS의 도메인마다 https://도메인 (IP, localhost 등 점 없는 이름, *, .local 제외)."""
    origins = []
    for host in hosts:
        name = host.lstrip(".")
        if host == "*" or "." not in name or name.endswith(".local"):
            continue
        try:
            ipaddress.ip_address(name.strip("[]"))
            continue
        except ValueError:
            pass
        origins.append(f"https://{host}" if not host.startswith(".") else f"https://*{host}")
    return origins
