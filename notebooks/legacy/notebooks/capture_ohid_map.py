"""Screenshot the OHID sandbox at high DPI, waiting until MapLibre is idle."""
import asyncio, base64, json, subprocess, sys, time
import requests, websockets

CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
URL    = sys.argv[1]
OUT    = sys.argv[2]
SCALE  = int(sys.argv[3])
W, H   = int(sys.argv[4]), int(sys.argv[5])
PORT   = 9333

chrome = subprocess.Popen([
    CHROME, '--headless=new', f'--remote-debugging-port={PORT}',
    '--enable-unsafe-swiftshader', '--hide-scrollbars', '--no-first-run',
    f'--window-size={W},{H}', f'--force-device-scale-factor={SCALE}',
    '--user-data-dir=' + OUT + '.profile', 'about:blank',
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def target():
    for _ in range(60):
        try:
            for t in requests.get(f'http://localhost:{PORT}/json/list', timeout=2).json():
                if t['type'] == 'page':
                    return t['webSocketDebuggerUrl']
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError('no devtools target')

async def main():
    ws_url = target()
    async with websockets.connect(ws_url, max_size=512 * 1024 * 1024) as ws:
        msg_id = 0
        async def send(method, **params):
            nonlocal msg_id
            msg_id += 1
            await ws.send(json.dumps({'id': msg_id, 'method': method, 'params': params}))
            while True:
                reply = json.loads(await ws.recv())
                if reply.get('id') == msg_id:
                    return reply.get('result', {})

        async def evaluate(expr):
            r = await send('Runtime.evaluate', expression=expr, returnByValue=True, awaitPromise=True)
            return r.get('result', {}).get('value')

        await send('Page.enable')
        await send('Page.navigate', url=URL)
        await asyncio.sleep(6)

        for attempt in range(80):
            state = await evaluate(
                "(() => { const m = window.ohid && window.ohid.map;"
                " if (!m) return 'no-map';"
                " return (m.loaded() && m.areTilesLoaded()) ? 'idle' : 'busy'; })()"
            )
            if state == 'idle':
                print(f'map idle after {6 + attempt * 0.5:.1f}s')
                break
            await asyncio.sleep(0.5)
        else:
            print(f'WARNING: map never reported idle (last state: {state})')

        # Optional JS to run once the map is up (e.g. raise the zoom to match a
        # larger viewport, so the framing is unchanged but the map draws more detail).
        if len(sys.argv) > 6:
            print('pre-shot js ->', await evaluate(sys.argv[6]))
            await asyncio.sleep(2)
            for _ in range(80):
                if await evaluate("window.ohid.map.loaded() && window.ohid.map.areTilesLoaded()"):
                    break
                await asyncio.sleep(0.5)

        await asyncio.sleep(3)   # let the final frame paint
        shot = await send('Page.captureScreenshot', format='png', captureBeyondViewport=False)
        open(OUT, 'wb').write(base64.b64decode(shot['data']))
        print('written', OUT)

try:
    asyncio.run(main())
finally:
    chrome.terminate()
