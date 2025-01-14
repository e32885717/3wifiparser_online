#MAP
map_async_level = 5
rescan_on_error = True
limit_rescans = True
use_https = False

#INTERFACE
only_ascii_progressbar = False

#ONLINE
#api_url = bytes.fromhex("68747470733a2f2f7766706172736572332e64646e732e6e65742f7061727365725f626173652f70726f7879").decode()
api_url = "https://wifibase.zapto.org:7000"
login = "public"
password = "public"

#AUTO
always_offline = False
always_online = True

#PASSWORDS
pass_scan_type = 1
pass_async_level = 8
pass_threads_cnt = 1
direct_api = True

#SPEED
json_lib = "ujson" # "standart"(slow), "ujson"(medium), "orjson"(fastest, hard to install)