# -*- coding: utf-8 -*-
"""Capture real screenshots of both apps for the video."""
import time, sys
from playwright.sync_api import sync_playwright

OUT = '/tmp/vidscenes'
import os; os.makedirs(OUT, exist_ok=True)

def shot(page, name, w=1600, h=900, wait=2500, full=False):
    page.set_viewport_size({'width': w, 'height': h})
    page.wait_for_timeout(wait)
    page.screenshot(path=f'{OUT}/{name}.png', full_page=full)
    print('shot', name)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={'width': 1600, 'height': 900})

    # 1. Station dashboard
    pg.goto('http://127.0.0.1:8765/#/dashboard', wait_until='networkidle')
    shot(pg, '01_station_dash', wait=3500)

    # 2. Station faxes list
    pg.goto('http://127.0.0.1:8765/#/faxes', wait_until='networkidle')
    shot(pg, '02_station_faxes', wait=2500)

    # 3. Station new fax modal
    pg.goto('http://127.0.0.1:8765/#/faxes?new=1', wait_until='networkidle')
    shot(pg, '03_station_newfax', wait=3000)
    # close modal via Escape
    pg.keyboard.press('Escape'); pg.wait_for_timeout(400)

    # 4. Station workbench — first ticket
    pg.goto('http://127.0.0.1:8765/#/faxes', wait_until='networkidle')
    pg.wait_for_timeout(1500)
    row = pg.query_selector('#fbody tr[data-id]')
    if row:
        row.click(); pg.wait_for_timeout(4000)
        shot(pg, '04_station_workbench', wait=2000)
        # estimate tab
        est = pg.query_selector('#wbTabs button[data-tab="estimate"]')
        if est:
            est.click(); pg.wait_for_timeout(2500)
            shot(pg, '05_station_estimate', wait=1500)
        # original tab
        org = pg.query_selector('#wbTabs button[data-tab="original"]')
        if org:
            org.click(); pg.wait_for_timeout(1500)
            shot(pg, '06_station_original', wait=1500)
    else:
        print('no ticket row!')

    # 5. Command screen map
    pg.goto('http://127.0.0.1:8766/#/map', wait_until='networkidle')
    shot(pg, '07_command_map', wait=5000)

    # 6. Command ops log
    pg.goto('http://127.0.0.1:8766/#/ops', wait_until='networkidle')
    shot(pg, '08_command_ops', wait=2500)

    # 7. Command reference
    pg.goto('http://127.0.0.1:8766/#/ref', wait_until='networkidle')
    shot(pg, '09_command_ref', wait=2500)

    # 8. Command ticket detail (modal) — open first row if exists
    pg.goto('http://127.0.0.1:8766/#/ops', wait_until='networkidle')
    pg.wait_for_timeout(1500)
    tr = pg.query_selector('#opsBody tr[data-id]')
    if tr:
        tr.click(); pg.wait_for_timeout(2500)
        shot(pg, '10_command_detail', wait=1500)

    b.close()
print('done')
