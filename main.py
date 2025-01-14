import aiohttp
import config
import utils
utils.init_json_lib()

import asyncio
import cloud
import tqdm
import time
import fw_parser
import database
import logging
import online_logic
import offline_logic
import passwords

#VERSION
#3wifiparser2.0

utils.set_log()
if not(config.api_url.endswith("/")):
    config.api_url += "/"
headers = { 
  "Content-type": "application/json",  
  "Accept": "text/plain", 
  "Host": "3wifi.stascorp.com" 
}
server_ip = "134.0.119.34"
api_path = f"{'https' if config.use_https else 'http'}://{server_ip}"
passwords.set_api_url(api_path)

async def anon_upload():
    nets = database.get_non_shared()
    if len(nets) > 0:
        try:
            await cloud.anonymous_upload(nets)
            database.set_shared([i[1] for i in nets])
            return True
        except:
            return False
    else:
        return False

async def ping_task(task: utils.Task, progress=0, local=False):
    if local:
        database.update_task(task, progress)
        await anon_upload()
    else:
        await cloud.ping_task(task.server_id)
    return {"ok": True}

async def load(session: aiohttp.ClientSession, tile, zoom, random_subtask=0, rescan_level=0, tqdm_bar: tqdm.tqdm=None): # create map scan request and save results to db
    if rescan_level > 8 and config.limit_rescans:
        return {"ok": False, "desc": "Too many rescans"}
    try:
        resp = await session.get(f"{api_path}/3wifi.php?a=map&scat=1&tileNumber={tile}&zoom={zoom}", headers=headers)
    except:
        await asyncio.sleep(2)
        return await load(session, tile, zoom, random_subtask=random_subtask, rescan_level=rescan_level + 1, tqdm_bar=tqdm_bar)
    parsing_result = fw_parser.parse_map(await resp.text())
    if not(parsing_result["ok"]):
        if tqdm_bar is None:
            logging.error(f"main.load parsing_result not ok: {parsing_result}")
        else:
            tqdm_bar.write(parsing_result["desc"])
        if parsing_result["rescan"]:
            await asyncio.sleep(0.5)
            return await load(session, tile, zoom, random_subtask=random_subtask, rescan_level=rescan_level + 1, tqdm_bar=tqdm_bar)
        else:
            return {"ok": False, "desc": parsing_result["desc"]}
    if len(parsing_result["result"]) == 0:
        return {"ok": True, "nets": 0}
    database.save_networks(parsing_result["result"], random_subtask)
    return {"ok": True, "nets": len(parsing_result["result"])}

async def load_tasks(tasks, progressbar): # calls multiple load functions asynchronously
    total_found = 0
    responses = await asyncio.gather(*tasks)
    for resp in responses:
        if resp == None:
            continue
        if not(not(resp["ok"])) and "nets" in resp:
            total_found += int(resp.get("nets"))
        elif not(resp["ok"]):
            progressbar.write("Function load_tasks() error: " + str(resp.get("desc")))
    tasks.clear()
    return total_found

async def scan_task(task: utils.Task, pinging=True): # scans task
    global last_uploaded_id
    last_ping_time = time.time()
    ping_interval = 30 if pinging else 2
    total_found = 0
    passwords.start_passwords_scan()
    tiles = task.get_tiles()
    tiles = [",".join([str(y) for y in i]) for i in tiles]
    progressbar = tqdm.tqdm(total=len(tiles), ascii=config.only_ascii_progressbar)
    utils.set_tqdm_log(progressbar)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(force_close=True, ssl=False)) as session:
        tasks = []
        for tile in tiles:
            try:
                tasks.append(asyncio.create_task(load(session, tile, 17, random_subtask=task.local_id, tqdm_bar=progressbar)))
                if time.time() - last_ping_time > ping_interval: # ping task
                    tasks.append(asyncio.create_task(ping_task(task, progressbar.n, not(pinging))))
                    last_ping_time = time.time()
                if len(tasks) >= min(config.map_async_level, 8):
                    total_found += await load_tasks(tasks, progressbar)
            except Exception as e:
                logging.exception("scan_task for exception")
            progressbar.update(1)
            progressbar.set_postfix_str(f"{total_found} networks found")
        if len(tasks) > 0:
            total_found += await load_tasks(tasks, progressbar)
    passwords.set_map_end(True)
    progressbar.close()
    utils.set_log()
    cnter = 0
    no_loaded = database.get_cnt_null_pass()
    if no_loaded != 0:
        progressbar = tqdm.tqdm(total=no_loaded, ascii=config.only_ascii_progressbar)
        progressbar.set_description_str("Loading passwords")
        utils.set_tqdm_log(progressbar)
        while passwords.is_pooling():
            if cnter > ping_interval * 10:
                await ping_task(task, len(tiles) - 1, not(pinging))
                cnter = 0
            n = database.get_cnt_null_pass()
            progressbar.update(no_loaded - n)
            no_loaded = n
            await asyncio.sleep(0.5)
            cnter += 5
        progressbar.close()
        utils.set_log()
    if not(pinging):
        while(await anon_upload()): # load all unloaded to server
            pass
    passwords.join()
    passwords.clear()

async def scan_from_server():
    task = await online_logic.get_task_from_server()
    if task is None:
        return
    logging.info("Task privated")
    await scan_task(task)
    logging.info("\nSending scan results to server")
    await online_logic.load_task_to_server(task.local_id, task.server_id)
    if database.get_total_nets() > 50000:
        database.rotate_base()
    logging.info("Completed!")
    
async def scan_from_user():
    database.load_db("main.db")
    task = offline_logic.get_task_argv()
    if task is None:
        pos = offline_logic.get_pos1_pos2()
        task = offline_logic.pos2task(pos)
        database.create_task(task)
    await scan_task(task, False)
    await cloud.close_session()

async def rescan_passwords():
    database.load_db("main.db")
    passwords.start_passwords_scan()
    passwords.set_map_end(True)
    no_loaded = database.get_cnt_null_pass()
    if no_loaded != 0:
        progressbar = tqdm.tqdm(total=no_loaded, ascii=config.only_ascii_progressbar)
        progressbar.set_description_str("Loading passwords")
        utils.set_tqdm_log(progressbar)
        while passwords.is_pooling():
            n = database.get_cnt_null_pass()
            progressbar.n = (no_loaded - n) - 1
            progressbar.update(1)
            await asyncio.sleep(0.5)
        progressbar.close()
        utils.set_log()
    passwords.clear()

async def pool_from_server():
    database.init_temp_db()
    while True:
        try:
            await scan_from_server()
        except Exception as e:
            logging.exception("scan_from_server exception")
            if str(e) == "Wrong login or password":
                await asyncio.sleep(120)
            await asyncio.sleep(2)

if __name__ == "__main__":
    mode = 1
    if offline_logic.check_offline_argv():
        mode = 2
    elif not(config.always_offline or config.always_online):
        mode = input("Specify operating mode.\n1 - online\n2 - offline\nMode: ")
        if not(mode in ["1", "2", "3"]):
            raise Exception("Invalid input")
        mode = int(mode)
    elif config.always_offline:
        mode = 2
    if mode == 1:
        asyncio.run(pool_from_server())
    elif mode == 2:
        asyncio.run(scan_from_user())
    elif mode == 3:
        asyncio.run(rescan_passwords())
    logging.info("End")
