"""
Direct SDK test — exact same pattern that works in babylon-laser.
Run: python test_circle.py
"""
import ctypes, math, time, socket

# Step 1: Load DLL
dll = ctypes.CDLL(r'C:\Program Files\MadMapper 5.7.1\BEYONDIOx64.dll')

# Step 2: Point structure (16 bytes)
class SdkPoint(ctypes.Structure):
    _fields_ = [
        ('x', ctypes.c_float),
        ('y', ctypes.c_float),
        ('z', ctypes.c_float),
        ('color', ctypes.c_uint32),
        ('rep_count', ctypes.c_uint8),
        ('focus', ctypes.c_uint8),
        ('status', ctypes.c_uint8),
        ('zero', ctypes.c_uint8),
    ]

# Step 3: Function signatures
dll.ldbCreateZoneImage.argtypes = [ctypes.c_int, ctypes.c_char_p]
dll.ldbSendFrameToImage.argtypes = [
    ctypes.c_char_p, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int
]
dll.ldbSendFrameToImage.restype = ctypes.c_int
dll.ldbDeleteZoneImage.argtypes = [ctypes.c_char_p]

# Step 4: Initialize SDK
dll.ldbCreate()
print(f'BEYOND ready: {bool(dll.ldbBeyondExeReady())}')

# Clear existing cues via PangoScript
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    sock.connect(("localhost", 16063))
    sock.sendall(b"StopAllNow\r\n")
    try: sock.recv(1024)
    except: pass
    sock.close()
    print("Cleared cues via PangoScript")
except Exception as e:
    print(f"PangoScript skip: {e}")

# Step 5: Create buffer
image_name = b'Circle'
dll.ldbCreateZoneImage(0, image_name)
dll.ldbEnableLaserOutput()

# Step 6: Zone array
zone_arr = (ctypes.c_ubyte * 256)()
zone_arr[0] = 1

# Step 7: Build circle points
NUM_POINTS = 64
RADIUS = 15000.0
GREEN = 0 | (255 << 8) | (0 << 16)

arr = (SdkPoint * NUM_POINTS)()
for i in range(NUM_POINTS):
    angle = 2 * math.pi * i / NUM_POINTS
    arr[i].x = RADIUS * math.cos(angle)
    arr[i].y = RADIUS * math.sin(angle)
    arr[i].z = 0.0
    arr[i].color = GREEN
    arr[i].rep_count = 0
    arr[i].focus = 0
    arr[i].status = 0
    arr[i].zero = 0

print(f'Built {NUM_POINTS} points, radius {RADIUS}, color={GREEN}')
print(f'First point: x={arr[0].x:.0f} y={arr[0].y:.0f} color={arr[0].color}')

# Step 8: Send at 30fps for 10 seconds
print('Streaming circle for 10 seconds...')
start = time.time()
frames = 0
while time.time() - start < 10:
    result = dll.ldbSendFrameToImage(
        image_name, NUM_POINTS,
        ctypes.byref(arr), ctypes.byref(zone_arr), -30000
    )
    frames += 1
    if frames == 1:
        print(f'First frame result={result}')
    time.sleep(1/30)

print(f'Done. Sent {frames} frames in {time.time()-start:.1f}s')

# Step 9: Cleanup
dll.ldbDeleteZoneImage(image_name)
dll.ldbDestroy()
print('Cleaned up.')
