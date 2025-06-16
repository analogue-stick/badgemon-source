import sys, os
if sys.implementation.name == "micropython":
    apps = os.listdir("/apps")
    path = ""
    for app in apps:
        if app.startswith("badgemon_source"):
            path = "/apps/" + app
    ASSET_PATH = path + "/assets/"
    SAVE_PATH = "/bmon_gr_saves/"
else:
    ASSET_PATH = "./apps/badgemon_source/assets/"
    SAVE_PATH = "./apps/badgemon_source/saves/"