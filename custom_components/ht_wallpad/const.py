"""상수와 우리 집 기기 배치 (RS485 캡처로 확인한 값)."""
DOMAIN = "ht_wallpad"
SIGNAL_UPDATE = f"{DOMAIN}_update"
EVENT = f"{DOMAIN}_event"

CONF_ELEVATOR_HOST = "elevator_host"  # 채널1: 일괄 스위치 · 엘리베이터
CONF_LIGHT_HOST = "light_host"  # 채널2: 조명 · 대기전력 콘센트
CONF_HEAT_HOST = "heat_host"  # 채널3: 난방 · 환기 · 가스
CONF_PORT = "port"
CONF_PROTECTED_OUTLETS = "protected_outlets"
DEFAULT_PORT = 8899

CONF_ROOMS = "rooms"

# 기본 방 배치 (힐스테이트 자이 아산센텀 96㎡A형). configuration.yaml 의 rooms 로 바꿀 수 있음.
# (영문 id, 이름, 조명 그룹, 조명 회로 이름들, 난방 번호 또는 None)
DEFAULT_ROOMS = [
    ("living", "거실", 0x10, ["1", "2", "3"], 0x11),
    ("room1", "침실1", 0x20, ["1", "2", "3"], 0x12),
    ("room2", "침실2", 0x30, ["1", "2"], 0x13),
    ("room3", "침실3", 0x40, ["1", "2"], 0x14),
    ("alpha", "알파룸", 0x50, ["1"], 0x15),
    ("kitchen", "주방", 0x60, ["1", "2", "3"], None),
]
OUTLETS_PER_ROOM = 2
# 차단 스위치를 만들지 않을 콘센트 번호 (예: 서버 전원). 기본은 없음.
DEFAULT_PROTECTED_OUTLETS: list[int] = []

FAN_SUB = 0x11
FAN_MIN_TOGGLE_SECONDS = 20  # 환기는 기동이 느려 켜고 끄는 간격 20초 이상
